"""What a model may do to their own record.

Gated on `current_affiliate` - ownership, never a permission (§6.1). Every
route here acts on the caller's own profile and takes no affiliate id at all,
so there is no parameter to tamper with: reaching another model's record is
not refused, it is unexpressible.

§6.5 bounds what appears here. They may correct how to reach them and where their
money goes. They may not touch a rate, a target, an order, or a month state.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_affiliate, current_user
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.models.payments import PaymentTransaction
from app.services.applications import REQUIRED_PAYOUT_FIELDS, application_state
from app.services.auth import authenticate
from app.services.codes import codes_with_status
from app.services.payouts import (
    changed_recently,
    current_destination,
    mask_destination,
    set_destination,
)
from app.services.policy import get_policy_version
from app.services.portal import (
    months_for,
    my_month,
    my_orders,
    my_payments,
    my_year,
)
from app.services.proof import readable_by

router = APIRouter(prefix="/api/me")


class PayoutChangeBody(BaseModel):
    #: §6.4.1. Not the session - a session is what an attacker already has.
    password: str = Field(min_length=1, max_length=256)
    method: str

    instapay_address_url: str | None = Field(default=None, max_length=500)
    instapay_phone: str | None = Field(default=None, max_length=40)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_holder: str | None = Field(default=None, max_length=120)
    bank_account_number: str | None = Field(default=None, max_length=60)
    wallet_phone: str | None = Field(default=None, max_length=40)


@router.get("")
def me(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Their own record, as they are allowed to see it.

    The payout destination is **masked even to them**. They supplied it, so it
    tells them nothing they do not know - and a screen that prints a full
    account number is a screen worth photographing over somebody's shoulder.
    Recognising which account is theirs is all this has to do.
    """
    destination = current_destination(db, affiliate)
    return {
        "name": affiliate.name,
        "phone": affiliate.phone,
        "status": affiliate.status,
        "state": application_state(db, affiliate),
        "codes": codes_with_status(db, affiliate, affiliate.created_at.strftime("%Y-%m"))
        if affiliate.created_at
        else [],
        "payout_destination": mask_destination(destination),
        "required_fields": {
            method: list(fields) for method, fields in REQUIRED_PAYOUT_FIELDS.items()
        },
    }


@router.put("/payout-destination")
def change_payout_destination(
    body: PayoutChangeBody,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """§6.4. Move where their money goes.

    The highest-risk thing a model can do: a compromised account that can
    silently repoint an InstaPay address can redirect an entire payout.

    **The password is re-entered, not the session.** A session is what an
    attacker has - a hijacked cookie, a borrowed phone. The password is what
    they may not, and this is the one action where that distinction is worth
    the friction.

    Checked with `authenticate`, the same function that checks it at sign-in,
    so the two can never disagree about what a correct password is.

    The response is **masked**, even though the caller just typed the raw
    value. Echoing it back is a second place it could be logged, and a
    response body gets captured by more things than a request body does.
    """
    if authenticate(db, user.email, body.password) is None:
        # Deliberately not "wrong password" versus "account problem": both
        # answers are the same to somebody who should not be here.
        raise HTTPException(403, "That password is not right")

    fields = {
        field: getattr(body, field)
        for field in REQUIRED_PAYOUT_FIELDS.get(body.method, ())
    }
    missing = [field for field, value in fields.items() if not str(value or "").strip()]
    if missing:
        raise HTTPException(
            400,
            "These are needed before we can pay you: "
            + ", ".join(field.replace("_", " ") for field in missing),
        )

    before = mask_destination(current_destination(db, affiliate))

    try:
        destination = set_destination(
            db,
            affiliate,
            method=body.method,
            actor_id=user.id,
            actor_email=user.email,
            **fields,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {
        # §6.4.2. Both sides, masked, so they can confirm what they changed
        # without the screen printing either in full.
        "before": before,
        "after": mask_destination(destination),
    }


@router.get("/payout-destination/changed-recently")
def destination_changed_recently(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """When their destination last moved, if it was lately.

    Theirs to see as well as the maintainer's. A model who did not make that
    change is the first person who would notice, and the only one who can say
    so.
    """
    changed = changed_recently(db, affiliate)
    return {"changed_at": changed.isoformat() if changed else None}


# -- What they have earned (Phase 9, §11.1 and §11.4) ---------------------------


def _month_or_400(month: str) -> str:
    from app.core.businesstime import parse_month

    try:
        return parse_month(month)
    except ValueError as exc:
        raise HTTPException(400, "A month looks like 2026-04") from exc


@router.get("/months")
def my_months(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """The months they can look at, newest first.

    Theirs, not the calendar's. The maintainer's picker offers every month
    because they are choosing which payroll to run; a model offered a month from
    before they joined would find an empty screen and no way to tell whether
    that meant nothing happened or something broke.
    """
    months = months_for(db, affiliate)
    return {"months": months, "working_month": months[0] if months else None}


@router.get("/earnings/{month}")
def my_earnings(
    month: str,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """One of their months, and every order behind the figure.

    The orders travel with the month deliberately. The first thing anybody does
    with a payment figure is try to reconcile it against what they think they
    sold, and a screen that makes them ask for the detail separately is a screen
    that makes them ask HBA instead.

    Nothing here is recalculated for them: an agreed month is read out of its
    snapshot, an open one out of the same `calculate_month` the payroll screen
    uses. Two implementations of what they are owed would be two answers waiting
    to disagree, and they would be paid the other one.
    """
    month = _month_or_400(month)
    return {
        **my_month(db, affiliate, month),
        "orders_detail": my_orders(db, affiliate, month),
    }


@router.get("/payments")
def my_payment_history(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """What has arrived, and what is still outstanding.

    §14. A different route from their earnings on purpose, and it stays
    different: *what I have earned* and *what has arrived* have different
    answers for most of any month.

    Ownership again, and no affiliate id anywhere - the settlement figures come
    from the same `balance_for` the maintainer's payment screen uses, so the
    number they chase and the number they see cannot disagree.
    """
    return my_payments(db, affiliate)


@router.get("/payments/{payment_id}/proof")
def my_payment_proof(
    payment_id: int,
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> Response:
    """The transfer screenshot for one of their payments.

    §14 and ADR 0017: proof is shown to the affiliate because visible proof
    removes an entire category of *"did you send it?"* messages. The business
    accepted the recorded risk that a screenshot may expose HBA's own banking
    details to about twenty people; the mitigations that made that acceptable -
    EXIF stripped, re-encoded, size-capped, and **served only to the owner** -
    are conditions, not extras.

    The last of those lives in `readable_by`, whose docstring has named this
    route since Phase 7: *"the affiliate's own route arrives in Phase 9 and
    calls the same `readable_by`, so the two cannot drift apart on the rule."*
    This is that route, and it calls it rather than re-checking the rule here.

    The ownership check on the transaction comes first all the same. Without
    it, asking for a payment id that is not theirs would be answered by whether
    the *file* was theirs - a slower path to the same 404, and one that reveals
    which payment ids exist by how long it takes.
    """
    transaction = db.get(PaymentTransaction, payment_id)
    if (
        transaction is None
        or transaction.affiliate_id != affiliate.id
        or transaction.proof_file_id is None
    ):
        raise HTTPException(404, "No proof for that payment")

    stored = readable_by(db, transaction.proof_file_id, affiliate_id=affiliate.id)
    if stored is None:
        raise HTTPException(404, "No proof for that payment")

    return Response(content=stored.content, media_type=stored.content_type)


@router.get("/year")
def my_year_view(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """Every month they have, for the charts.

    Nothing here is new arithmetic - each month is the same figure the Earnings
    screen shows, gathered. A second way of working out what they earned would
    be a second answer waiting to disagree with the first.
    """
    return my_year(db, affiliate)


@router.get("/policy/{policy_version_id}")
def my_policy_version(
    policy_version_id: int,
    _affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """The rules a settled month names, in full.

    Not ownership-scoped like everything else here - a policy version is a
    platform-wide fact, the same text whoever reads it, not a record that
    belongs to one affiliate. `current_affiliate` still gates it: signed in
    as a model is what this route requires, not signed in as this model.
    """
    version = get_policy_version(db, policy_version_id)
    if version is None:
        raise HTTPException(404, "No such policy version")
    return {
        "id": version.id,
        "effective_month": version.effective_month,
        "summary_markdown": version.summary_markdown,
    }
