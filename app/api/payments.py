"""Recording that money moved, over HTTP.

§14. Every endpoint here describes something a person did **outside** the
platform: opened InstaPay, sent money, screenshotted the confirmation. Nothing
initiates a payment, and nothing marks one settled on its own.

## The amount is pre-filled and editable, and a difference needs a note

§14 lists why it must be editable: partial payments, InstaPay limits forcing a
split, one transfer covering two months, transfer fees, and mistakes where the
record must show the truth.

**Any amount differing from `balance_due` requires a short note** — and it is a
refusal, not a warning. The note is the only thing separating a deliberate
partial payment from a typo, and only the person recording it knows which.

## Proof is served per request, never by URL

§14 and ADR 0017. The check is against the session, in the same place as every
other permission check. A URL that is its own permission leaks the moment
somebody forwards a message.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.businesstime import parse_month
from app.core.money import format_egp
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.models.payments import AdjustmentType, PaymentTransaction
from app.services.affiliates import list_affiliates
from app.services.corrections import open_corrections
from app.services.payments import (
    PaymentOperationConflict,
    adjust,
    adjustments_for,
    assert_same_payment,
    balance_for,
    payment_for_operation_key,
    payments_for,
    record_payment,
)
from app.services.payroll import blockers_for, is_historical
from app.services.payouts import (
    changed_recently,
    current_destination,
    mask_destination,
)
from app.services.proof import ProofRejected, readable_by, store_proof

router = APIRouter(prefix="/api")


class AllocationBody(BaseModel):
    payroll_snapshot_id: int
    piastres: int = Field(gt=0)


class PaymentBody(BaseModel):
    operation_key: str | None = Field(default=None, min_length=8, max_length=64)
    affiliate_id: int
    amount_piastres: int = Field(gt=0)
    allocations: list[AllocationBody] = Field(default_factory=list)
    occurred_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=120)
    #: §14. Required when the amount differs from what was owed.
    note: str | None = Field(default=None, max_length=500)
    proof_file_id: str | None = Field(default=None, max_length=64)


class AdjustmentBody(BaseModel):
    affiliate_id: int
    type: str
    source_month: str
    amount_piastres: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)
    destination_month: str | None = None


def _month_or_400(month: str) -> str:
    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


def _affiliate_or_404(db: Session, affiliate_id: int) -> AffiliateProfile:
    affiliate = db.get(AffiliateProfile, affiliate_id)
    if affiliate is None:
        raise HTTPException(404, "No such affiliate")
    return affiliate


def _terms_label(db: Session, affiliate: AffiliateProfile, month: str) -> str | None:
    """Her arrangement **for the month being paid**, as a type rather than a
    sentence.

    Dated, not current: terms change, and a row that labelled September with
    October's arrangement would put the wrong explanation beside a figure
    somebody is about to send.

    The *wording* stays in the browser, where every other screen already
    labels an arrangement. Two copies of "Guaranteed minimum" is two places to
    change it and one of them to forget.
    """
    from app.services.compensation import terms_for

    terms = terms_for(db, affiliate, month)
    return terms.compensation_type if terms else None


def _render_balance(
    db: Session,
    affiliate: AffiliateProfile,
    month: str,
    balance: dict,
    destination_changed_at=None,
) -> dict:
    row = {
        **balance,
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "status": affiliate.status,
        # §6.4.5. Surfaced at the moment a redirected payout would actually
        # cost money. `changed_recently` has existed since Phase 3 and reached
        # no screen until now - it had nothing to warn about while only the
        # maintainer could change a destination, and from Phase 8 it does.
        "destination_changed_at": (
            destination_changed_at.isoformat() if destination_changed_at else None
        ),
        "obligation": format_egp(balance["obligation_piastres"]),
        "paid": format_egp(balance["paid_piastres"]),
        "balance": format_egp(balance["balance_piastres"]),
        # **Her arrangement and where the money goes**, both on the row.
        #
        # The approved month-end screen puts the terms under her name and the
        # destination in its own column with a copy button, because the person
        # working through this list is about to open a banking app and type
        # one of them in. Making them open a profile for it is how a transfer
        # goes to the previous destination.
        #
        # The destination is **masked** by the same function the profile uses
        # (ADR 0028): enough to recognise on a list of twenty. The copy button
        # beside it asks for the real value through the audited reveal, gated
        # on `payments.record`, so every number that reaches a clipboard is
        # one somebody is recorded as having looked at.
        "terms": _terms_label(db, affiliate, month),
        "destination": mask_destination(current_destination(db, affiliate)),
    }

    # F14. An approved obligation is a debt; a forecast is still moving. The
    # payments desk needs both, but they must never share a label or silently
    # add an incomplete calculation to the cash request.
    if balance["state"] == "not_approved" and not is_historical(month):
        blockers, calculation = blockers_for(db, affiliate, month)
        forecast = calculation.payout_piastres if not blockers else None
        row.update(
            forecast_piastres=forecast,
            forecast_blockers=blockers,
            required_kind="forecast" if forecast is not None else "unavailable",
            required_piastres=forecast or 0,
        )
    elif balance["state"] == "settled_externally":
        row.update(
            forecast_piastres=None,
            forecast_blockers=[],
            required_kind="settled_externally",
            required_piastres=0,
        )
    else:
        # Funds required is the bank movement for this month, not its gross
        # approved earnings. A credit is money already in her hands, so D04's
        # valid zero-transfer month must contribute zero here while retaining
        # the approved obligation beside it. Recorded + remaining also keeps
        # this figure stable as ordinary partial transfers are entered.
        transfer_requirement = balance["paid_piastres"] + max(
            balance["balance_piastres"], 0
        )
        row.update(
            forecast_piastres=None,
            forecast_blockers=[],
            required_kind="approved",
            required_piastres=transfer_requirement,
        )

    row["required"] = format_egp(row["required_piastres"])
    return row


def _all_open_corrections(db: Session) -> list[dict]:
    """Every unresolved recovery choice, including for someone archived.

    05C deliberately answered the per-model question. Month end asks a
    different one: *is there any money HBA has already advanced and not dealt
    with?* Scanning every payable profile here is what stops an inactive or
    departed model's correction disappearing from the only place finance is
    certain to visit.
    """
    rows = []
    for affiliate in list_affiliates(db, include_archived=True):
        if not affiliate.is_payable:
            continue
        rows.extend(
            {
                **_render_correction(correction),
                "name": affiliate.name,
                "status": affiliate.status,
            }
            for correction in open_corrections(db, affiliate)
        )
    return rows


@router.get("/payments/{month}")
def outstanding(
    month: str,
    include_archived: bool = False,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """What is still owed for one month, per model.

    Every figure is derived from the ledger. Nothing here reads a stored
    settlement state, because there isn't one (§11.1).
    """
    month = _month_or_400(month)
    # A house code has real sales and no payee. Filtering it before any
    # calculation prevents it entering model counts as well as money totals;
    # inactive models stay because an old obligation does not leave with them.
    affiliates = [
        affiliate
        for affiliate in list_affiliates(db, include_archived=include_archived)
        if affiliate.is_payable
    ]
    rows = [
        _render_balance(
            db,
            affiliate,
            month,
            balance_for(db, affiliate, month),
            changed_recently(db, affiliate),
        )
        for affiliate in affiliates
    ]
    outstanding_rows = [row for row in rows if row["balance_piastres"] > 0]
    corrections = _all_open_corrections(db)
    required = sum(row["required_piastres"] for row in rows)
    forecast = sum(
        row["required_piastres"]
        for row in rows
        if row["required_kind"] == "forecast"
    )
    approved = sum(
        row["obligation_piastres"]
        for row in rows
        if row["required_kind"] == "approved"
    )
    recorded = sum(row["paid_piastres"] for row in rows)
    still_owed = sum(row["balance_piastres"] for row in outstanding_rows)
    open_correction_total = sum(
        row["recoverable_piastres"] for row in corrections
    )

    return {
        "month": month,
        "affiliates": rows,
        "open_corrections": corrections,
        "totals": {
            "affiliates": len(rows),
            "required_piastres": required,
            "required": format_egp(required),
            "forecast_piastres": forecast,
            "forecast": format_egp(forecast),
            "approved_piastres": approved,
            "approved": format_egp(approved),
            "recorded_piastres": recorded,
            "recorded": format_egp(recorded),
            "still_owed_affiliates": len(outstanding_rows),
            "still_owed_piastres": still_owed,
            "still_owed": format_egp(still_owed),
            "open_corrections": len(corrections),
            "open_corrections_piastres": open_correction_total,
            "open_corrections_amount": format_egp(open_correction_total),
        },
    }


@router.post("/payments", status_code=201)
def record(
    body: PaymentBody,
    actor: UserAccount = Depends(require_permission(Permission.PAYMENTS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """Record a transfer that has already been sent.

    **Nothing here sends money.** §14's first line: the Pay button changes
    nothing, and neither does this - it is a record of something that already
    happened.
    """
    affiliate = _affiliate_or_404(db, body.affiliate_id)
    allocations = {row.payroll_snapshot_id: row.piastres for row in body.allocations}

    # Resolve a retry before asking what is owed now. The first request may
    # have committed and lost its response; in that case the balance is already
    # zero, which made the old endpoint reject the retry as a different amount.
    existing = payment_for_operation_key(db, body.operation_key)
    if existing is not None:
        try:
            assert_same_payment(
                existing,
                affiliate=affiliate,
                amount_piastres=body.amount_piastres,
                allocations=allocations,
                occurred_at=body.occurred_at,
                reference=body.reference,
                note=body.note,
                proof_file_id=body.proof_file_id,
            )
        except PaymentOperationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return _render_recorded_payment(existing, replayed=True)

    # §14. A difference from what was owed is refused without a note - the note
    # is what separates a deliberate partial payment from a typo, and only the
    # person recording it knows which.
    if allocations and not (body.note or "").strip():
        for snapshot_id, piastres in allocations.items():
            owed = _owed_against(db, affiliate, snapshot_id)
            if owed is not None and piastres != owed:
                raise HTTPException(
                    400,
                    f"That allocates {format_egp(piastres)} against a balance of "
                    f"{format_egp(owed)}. Any difference needs a short note "
                    "saying why - a partial payment and a typo look identical "
                    "without one.",
                )

    try:
        transaction = record_payment(
            db,
            affiliate,
            amount_piastres=body.amount_piastres,
            operation_key=body.operation_key,
            allocations=allocations,
            occurred_at=body.occurred_at,
            reference=body.reference,
            note=body.note,
            proof_file_id=body.proof_file_id,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except PaymentOperationConflict as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError:
        # A genuine double-click can pass the read above twice. The unique key
        # chooses the winner; after rollback the loser returns that same row.
        db.rollback()
        existing = payment_for_operation_key(db, body.operation_key)
        if existing is None:
            raise
        try:
            assert_same_payment(
                existing,
                affiliate=affiliate,
                amount_piastres=body.amount_piastres,
                allocations=allocations,
                occurred_at=body.occurred_at,
                reference=body.reference,
                note=body.note,
                proof_file_id=body.proof_file_id,
            )
        except PaymentOperationConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return _render_recorded_payment(existing, replayed=True)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return _render_recorded_payment(transaction, replayed=False)


def _render_recorded_payment(
    transaction: PaymentTransaction, *, replayed: bool
) -> dict:
    return {
        "id": transaction.id,
        "affiliate_id": transaction.affiliate_id,
        "amount_piastres": transaction.amount_piastres,
        "amount": format_egp(transaction.amount_piastres),
        "unallocated_piastres": transaction.unallocated_piastres,
        "has_proof": transaction.proof_file_id is not None,
        "replayed": replayed,
    }


def _owed_against(db: Session, affiliate: AffiliateProfile, snapshot_id: int):
    """What is still owed on the month a snapshot belongs to, or None."""
    from app.models.payroll import PayrollSnapshot

    snapshot = db.get(PayrollSnapshot, snapshot_id)
    if snapshot is None:
        return None
    return balance_for(db, affiliate, snapshot.month.month)["balance_piastres"]


@router.post("/affiliates/{affiliate_id}/proof", status_code=201)
def upload_proof(
    affiliate_id: int,
    file: UploadFile = File(...),
    actor: UserAccount = Depends(require_permission(Permission.PAYMENTS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """Store a confirmation screenshot, and return the id to record with it.

    **Uploaded before the payment, not attached afterwards**, because
    `payment_transaction` is append-only: attaching later would mean updating a
    row the trigger refuses, and carving an exception for one column is how a
    table stops being append-only in practice while still claiming to be.

    It also matches §14's own flow - amount plus screenshot, then one Submit.

    Stripped of EXIF, compressed, capped and re-encoded before it is stored.
    ADR 0017 records why those are conditions rather than niceties.
    """
    affiliate = _affiliate_or_404(db, affiliate_id)

    try:
        stored = store_proof(db, affiliate, file.file.read(), actor_id=actor.id)
    except ProofRejected as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        "proof_file_id": stored.id,
        "size_bytes": stored.size_bytes,
        "content_type": stored.content_type,
    }


@router.get("/payments/{payment_id}/proof")
def fetch_proof(
    payment_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> Response:
    """The screenshot, checked against who it belongs to.

    §14: served only to the affiliate it belongs to. The maintainer reaches it
    through this route because they hold `affiliates.view`; the affiliate's own
    route arrives in Phase 9 and calls the same `readable_by`, so the two
    cannot drift apart on the rule.
    """
    transaction = db.get(PaymentTransaction, payment_id)
    if transaction is None or transaction.proof_file_id is None:
        raise HTTPException(404, "No proof for that payment")

    stored = readable_by(
        db, transaction.proof_file_id, affiliate_id=transaction.affiliate_id
    )
    if stored is None:
        raise HTTPException(404, "No proof for that payment")

    return Response(content=stored.content, media_type=stored.content_type)


@router.post("/adjustments", status_code=201)
def make_adjustment(
    body: AdjustmentBody,
    actor: UserAccount = Depends(require_permission(Permission.PAYMENTS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """A credit or a write-off (§11.5).

    Where the maintainer's choice after an agreed month's source facts change
    is recorded. The platform reports that a model was overpaid and refuses to
    decide which of these it is - that is a judgement about a person HBA knows.
    """
    affiliate = _affiliate_or_404(db, body.affiliate_id)
    _month_or_400(body.source_month)
    if body.destination_month:
        _month_or_400(body.destination_month)

    try:
        adjustment = adjust(
            db,
            affiliate,
            kind=body.type,
            source_month=body.source_month,
            amount_piastres=body.amount_piastres,
            reason=body.reason,
            destination_month=body.destination_month,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        "id": adjustment.id,
        "type": adjustment.type,
        "amount_piastres": adjustment.amount_piastres,
        "amount": format_egp(adjustment.amount_piastres),
    }


@router.get("/affiliates/{affiliate_id}/payments")
def affiliate_payments(
    affiliate_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Everything one model has been paid, and every adjustment touching them.

    §11.5 requires adjustments to be visible to them - a credit they cannot see
    is a credit they cannot check. This is the maintainer's view of the same
    facts; theirs arrives in Phase 9.
    """
    affiliate = _affiliate_or_404(db, affiliate_id)

    return {
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "payments": [
            {
                "id": row.id,
                "amount_piastres": row.amount_piastres,
                "amount": format_egp(row.amount_piastres),
                "occurred_at": row.occurred_at.isoformat(),
                "reference": row.reference,
                "note": row.note,
                "has_proof": row.proof_file_id is not None,
                # Already masked when it was written (§6.4.4).
                "destination": row.destination_snapshot_json,
                "allocated_piastres": row.allocated_piastres,
                "unallocated_piastres": row.unallocated_piastres,
                # The receipt must identify the agreed statement the transfer
                # settled. An aggregate alone is real money with its month
                # erased, which cannot answer a later payment question.
                "allocations": [
                    {
                        "month": allocation.snapshot.month.month,
                        "snapshot_id": allocation.payroll_snapshot_id,
                        "snapshot_version": allocation.snapshot.version,
                        "allocated_piastres": allocation.allocated_piastres,
                    }
                    for allocation in row.allocations
                ],
            }
            for row in payments_for(db, affiliate)
        ],
        "adjustments": [
            {
                "id": row.id,
                "type": row.type,
                "amount_piastres": row.amount_piastres,
                "amount": format_egp(row.amount_piastres),
                "from_month": row.source_month.month,
                "to_month": (
                    row.destination_month.month if row.destination_month else None
                ),
                "reason": row.reason,
            }
            for row in adjustments_for(db, affiliate)
        ],
    }


class CorrectionBody(BaseModel):
    affiliate_id: int
    month: str
    #: `credit` carries it into a later month; `writeoff` absorbs it. §11.5's
    #: two words, not a third vocabulary for the same two acts.
    choice: str
    reason: str = Field(min_length=1, max_length=500)
    destination_month: str | None = None
    #: What the screen showed as outstanding. **Required** (R2): this decides
    #: real money, and a caller that cannot say what it was looking at cannot
    #: be given permission to act on it. Its omission used to be treated as
    #: *proceed anyway*, which made the protection optional for exactly the
    #: callers most likely to need it.
    expected_outstanding_piastres: int = Field(ge=0)

    #: What this decision is called, so the same one arriving twice is one
    #: recovery. **Required**, and the browser sends a value it keeps across
    #: retries - a figure alone is not an identity, because two people
    #: recovering the same correction produce identical figures.
    operation_key: str = Field(min_length=8, max_length=80)


def _render_correction(row) -> dict:
    return {
        "affiliate_id": row.affiliate_id,
        "month": row.month,
        "outcome": row.outcome,
        "agreed_piastres": row.agreed_piastres,
        "agreed": format_egp(row.agreed_piastres),
        "now_piastres": row.now_piastres,
        "now": format_egp(row.now_piastres),
        "paid_piastres": row.paid_piastres,
        "paid": format_egp(row.paid_piastres),
        "recoverable_piastres": row.recoverable_piastres,
        "recoverable": format_egp(row.recoverable_piastres),
        # F11. The whole difference this month has come to, how much of it has
        # already been carried or absorbed, and what is left - separate
        # figures, because a month can be corrected twice and settled in
        # parts, and one boolean could not say which.
        "shortfall_piastres": row.shortfall_piastres,
        "shortfall": format_egp(row.shortfall_piastres),
        "resolved_piastres": row.resolved_piastres,
        "resolved_amount": format_egp(row.resolved_piastres),
        "outstanding_piastres": row.outstanding_piastres,
        "outstanding": format_egp(row.outstanding_piastres),
        "snapshot_version": row.snapshot_version,
        "resolved": row.resolved,
        "resolution": row.resolution,
        # F09. Something to look at, even where there is no money to move.
        "needs_review": row.needs_review,
        "review_reason": row.review_reason,
    }


@router.get("/affiliates/{affiliate_id}/corrections")
def affiliate_corrections(
    affiliate_id: int,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Agreed months of hers whose evidence has moved and still cost money.

    05C. An agreed month is not unmade any more (05B), so this is how a
    difference gets acted on: it is reported here, a person chooses, and the
    choice is recorded against the month rather than replacing it.

    **Read-only, and it decides nothing.** §11.5 says whether an overpayment is
    carried or absorbed is a judgement about a person HBA knows, and that has
    not changed.
    """
    from app.services.corrections import open_corrections, outstanding_piastres

    affiliate = _affiliate_or_404(db, affiliate_id)
    rows = open_corrections(db, affiliate)
    # Handed the list rather than recomputing it: each correction runs its
    # month's whole calculation.
    total = outstanding_piastres(db, affiliate, rows)
    return {
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "corrections": [_render_correction(row) for row in rows],
        # The cumulative figure, because deciding one month at a time is how
        # the second one gets forgotten - the failure §11.5 named about reopens
        # and which retiring them did not remove.
        "outstanding_piastres": total,
        "outstanding": format_egp(total),
    }


@router.post("/corrections", status_code=201)
def resolve_correction(
    body: CorrectionBody,
    actor: UserAccount = Depends(require_permission(Permission.PAYMENTS_RECORD)),
    db: Session = Depends(get_session),
) -> dict:
    """Carry an overpayment into a later month, or absorb it.

    **No amount is accepted.** It is computed from the frozen snapshot and the
    current calculation, because a caller supplying its own could recover more
    than was ever paid, or recover twice, and the ledger would afterwards
    record only that somebody chose that.
    """
    from app.services.corrections import CorrectionMoved, resolve

    affiliate = _affiliate_or_404(db, body.affiliate_id)
    _month_or_400(body.month)
    if body.destination_month:
        _month_or_400(body.destination_month)

    try:
        adjustment = resolve(
            db,
            affiliate,
            body.month,
            choice=body.choice,
            reason=body.reason,
            destination_month=body.destination_month,
            expected_outstanding_piastres=body.expected_outstanding_piastres,
            operation_key=body.operation_key,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    # Before the plain refusal below: a correction that moved is a different
    # answer from one that cannot be acted on, and 409 is what tells a browser
    # to look again rather than to correct its request.
    except CorrectionMoved as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        "id": adjustment.id,
        "type": adjustment.type,
        "amount_piastres": adjustment.amount_piastres,
        "amount": format_egp(adjustment.amount_piastres),
        "source_month": body.month,
        "destination_month": body.destination_month,
    }
