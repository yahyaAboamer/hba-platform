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
from app.services.payments import (
    adjust,
    adjustments_for,
    balance_for,
    payments_for,
    record_payment,
)
from app.services.proof import ProofRejected, readable_by, store_proof

router = APIRouter(prefix="/api")


class AllocationBody(BaseModel):
    payroll_snapshot_id: int
    piastres: int = Field(gt=0)


class PaymentBody(BaseModel):
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


def _render_balance(affiliate: AffiliateProfile, balance: dict) -> dict:
    return {
        **balance,
        "affiliate_id": affiliate.id,
        "name": affiliate.name,
        "obligation": format_egp(balance["obligation_piastres"]),
        "paid": format_egp(balance["paid_piastres"]),
        "balance": format_egp(balance["balance_piastres"]),
    }


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
    rows = [
        _render_balance(affiliate, balance_for(db, affiliate, month))
        for affiliate in list_affiliates(db, include_archived=include_archived)
    ]
    outstanding_rows = [row for row in rows if row["balance_piastres"] > 0]

    return {
        "month": month,
        "affiliates": rows,
        "totals": {
            "affiliates": len(rows),
            "still_owed_affiliates": len(outstanding_rows),
            "still_owed_piastres": sum(
                row["balance_piastres"] for row in outstanding_rows
            ),
            "still_owed": format_egp(
                sum(row["balance_piastres"] for row in outstanding_rows)
            ),
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
            allocations=allocations,
            occurred_at=body.occurred_at,
            reference=body.reference,
            note=body.note,
            proof_file_id=body.proof_file_id,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        "id": transaction.id,
        "affiliate_id": affiliate.id,
        "amount_piastres": transaction.amount_piastres,
        "amount": format_egp(transaction.amount_piastres),
        "unallocated_piastres": transaction.unallocated_piastres,
        "has_proof": transaction.proof_file_id is not None,
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

    Where the maintainer's choice after a reopen is recorded. The platform
    reports that a model was overpaid and refuses to decide which of these it
    is - that is a judgement about a person HBA knows.
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
    """Everything one model has been paid, and every adjustment touching her.

    §11.5 requires adjustments to be visible to her - a credit she cannot see
    is a credit she cannot check. This is the maintainer's view of the same
    facts; hers arrives in Phase 9.
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
