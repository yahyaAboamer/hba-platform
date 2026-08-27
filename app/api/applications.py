"""A model applying for herself, over HTTP.

§13 step 2. The only write endpoint in the platform reached by ownership
rather than by a permission, and the only one whose caller is not staff.

`current_affiliate` cannot gate this route: the whole point is that no profile
exists yet, and that dependency refuses precisely that case. So the gate here
is narrower and stated explicitly - a signed-in account that owns no profile,
holding the `affiliate` role. An administrator cannot apply; there is nothing
for them to apply as.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import active_role, current_user
from app.db import get_session
from app.models.identity import UserAccount
from app.services.applications import (
    REQUIRED_PAYOUT_FIELDS,
    existing_application,
    submit_application,
)

router = APIRouter(prefix="/api/applications")


class ApplicationBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=40)
    code: str = Field(min_length=1, max_length=120)
    payout_method: str

    instapay_address_url: str | None = Field(default=None, max_length=500)
    instapay_phone: str | None = Field(default=None, max_length=40)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_holder: str | None = Field(default=None, max_length=120)
    bank_account_number: str | None = Field(default=None, max_length=60)
    wallet_phone: str | None = Field(default=None, max_length=40)

    # No compensation_type, no commission_rate_bp, no fixed_amount_piastres,
    # no base_amount_piastres, no targets. §6.5 - and their absence from the
    # body is what makes the rule enforceable rather than merely intended.


def _applicant(
    user: UserAccount = Depends(current_user), db: Session = Depends(get_session)
) -> UserAccount:
    """A signed-in account that may apply.

    Staff are refused: an administrator has no affiliate record to create and
    letting them make one would produce a profile whose owner is the person who
    approves it.
    """
    if active_role(db, user) != "affiliate":
        raise HTTPException(403, "This account is not an affiliate")
    return user


@router.get("/mine")
def my_application(
    user: UserAccount = Depends(_applicant),
    db: Session = Depends(get_session),
) -> dict:
    """Whether this account has applied yet, and the shape the form needs.

    `required_fields` is served rather than duplicated in the client so the
    form and the service cannot disagree about what a bank transfer needs.
    """
    profile = existing_application(db, user)
    return {
        "applied": profile is not None,
        "status": profile.status if profile else None,
        "required_fields": {
            method: list(fields)
            for method, fields in REQUIRED_PAYOUT_FIELDS.items()
        },
    }


@router.post("", status_code=201)
def apply(
    body: ApplicationBody,
    user: UserAccount = Depends(_applicant),
    db: Session = Depends(get_session),
) -> dict:
    try:
        affiliate = submit_application(
            db,
            user,
            name=body.name,
            phone=body.phone,
            code=body.code,
            payout_method=body.payout_method,
            payout_fields={
                "instapay_address_url": body.instapay_address_url,
                "instapay_phone": body.instapay_phone,
                "bank_name": body.bank_name,
                "bank_account_holder": body.bank_account_holder,
                "bank_account_number": body.bank_account_number,
                "wallet_phone": body.wallet_phone,
            },
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return {"id": affiliate.id, "status": affiliate.status}
