"""What a model may do to her own record.

Gated on `current_affiliate` - ownership, never a permission (§6.1). Every
route here acts on the caller's own profile and takes no affiliate id at all,
so there is no parameter to tamper with: reaching another model's record is
not refused, it is unexpressible.

§6.5 bounds what appears here. She may correct how to reach her and where her
money goes. She may not touch a rate, a target, an order, or a month state.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_affiliate, current_user
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.identity import UserAccount
from app.services.applications import REQUIRED_PAYOUT_FIELDS, application_state
from app.services.auth import authenticate
from app.services.codes import codes_with_status
from app.services.payouts import (
    changed_recently,
    current_destination,
    mask_destination,
    set_destination,
)

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
    """Her own record, as she is allowed to see it.

    The payout destination is **masked even to her**. She supplied it, so it
    tells her nothing she does not know - and a screen that prints a full
    account number is a screen worth photographing over somebody's shoulder.
    Recognising which account is hers is all this has to do.
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
    """§6.4. Move where her money goes.

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
        # §6.4.2. Both sides, masked, so she can confirm what she changed
        # without the screen printing either in full.
        "before": before,
        "after": mask_destination(destination),
    }


@router.get("/payout-destination/changed-recently")
def destination_changed_recently(
    affiliate: AffiliateProfile = Depends(current_affiliate),
    db: Session = Depends(get_session),
) -> dict:
    """When her destination last moved, if it was lately.

    Hers to see as well as the maintainer's. A model who did not make that
    change is the first person who would notice, and the only one who can say
    so.
    """
    changed = changed_recently(db, affiliate)
    return {"changed_at": changed.isoformat() if changed else None}
