"""What a model fills in for herself.

§13 step 2. She has already accepted an invitation, so an account exists and a
password is set; this is the record that hangs off it - her name, her phone,
the code she wants to use, and where her money should go.

**Nothing here decides what she is paid.** §6.5 is absolute: a model may never
edit anything determining what she is owed. Compensation type, rate, fixed
amount, base amount and targets are all the maintainer's, set at review. That
is enforced by this module simply having no parameter for any of them - a
form that merely omits a field is not a control, but a service that cannot
express the value is.

**The code is registered unverified, deliberately.** §10.4 makes Shopify
verification a required gate before approval and `set_status` already enforces
it. Registering here gives the maintainer's review something concrete to
verify rather than a free-text field to retype, and the existing gate does the
refusing.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliates import AccountKind, AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.models.payouts import VALID_METHODS, PayoutMethod
from app.services.affiliates import create_affiliate
from app.services.audit import record_audit
from app.services.codes import normalise_code, register_code, start_month_for
from app.services.payouts import set_destination

#: What each method needs before an application is worth submitting. InstaPay
#: wants both: the address feeds the deep link, the number is what somebody
#: types when the link does not open (ADR 0028).
REQUIRED_PAYOUT_FIELDS = {
    PayoutMethod.INSTAPAY: ("instapay_address_url", "instapay_phone"),
    PayoutMethod.BANK: ("bank_name", "bank_account_holder", "bank_account_number"),
    PayoutMethod.WALLET: ("wallet_phone",),
}


def existing_application(db: Session, user: UserAccount) -> AffiliateProfile | None:
    """The profile this account already owns, if any."""
    return db.scalar(
        select(AffiliateProfile).where(AffiliateProfile.user_account_id == user.id)
    )


def submit_application(
    db: Session,
    user: UserAccount,
    *,
    name: str,
    phone: str,
    code: str,
    payout_method: str,
    payout_fields: dict[str, str | None],
) -> AffiliateProfile:
    """Create the affiliate record a model has applied with.

    One transaction, three rows: the profile, her proposed code, and her payout
    destination. Partially applying would leave a `pending` row that looks like
    an application somebody made and did not finish, which is indistinguishable
    from one they never started.

    **Applying twice is refused.** A double-tapped submit would otherwise
    produce two pending profiles and two code registrations for one person, one
    of which quietly wins.
    """
    if existing_application(db, user) is not None:
        raise ValueError("You have already applied")

    name = str(name or "").strip()
    if not name:
        raise ValueError("Tell us your name")

    phone = str(phone or "").strip()
    if not phone:
        raise ValueError("Tell us your phone number")

    if payout_method not in VALID_METHODS:
        raise ValueError(f"Unknown payout method: {payout_method!r}")

    cleaned = {
        field: (str(value).strip() or None) if value else None
        for field, value in payout_fields.items()
        if field in REQUIRED_PAYOUT_FIELDS[payout_method]
    }
    missing = [
        field
        for field in REQUIRED_PAYOUT_FIELDS[payout_method]
        if not cleaned.get(field)
    ]
    if missing:
        raise ValueError(
            "These are needed before we can pay you: "
            + ", ".join(field.replace("_", " ") for field in missing)
        )

    # normalise_code raises on an empty or malformed code, so this refuses
    # before anything is written rather than half way through.
    code = normalise_code(code)

    affiliate = create_affiliate(
        db,
        user_account_id=user.id,
        name=name,
        phone=phone,
        account_kind=AccountKind.MODEL,
        actor_id=user.id,
        actor_email=user.email,
    )

    # Unverified. §10.4's gate is `set_status`, and it stays the only gate.
    #
    # The start month is derived, never asked for: there is exactly one right
    # answer and asking a person can only produce a wrong one (see
    # `start_month_for`). A model choosing "this month" would orphan every
    # order her code had already earned.
    register_code(
        db,
        affiliate,
        code,
        start_month_for(None),
        actor_id=user.id,
        actor_email=user.email,
    )

    set_destination(
        db,
        affiliate,
        method=payout_method,
        actor_id=user.id,
        actor_email=user.email,
        **cleaned,
    )

    record_audit(
        db,
        action="affiliate.applied",
        subject=f"affiliate:{affiliate.id}",
        actor_id=user.id,
        actor_email=user.email,
        # The code is not a secret and is the thing being applied *with*; the
        # payout details are masked by `record_audit` on the way in regardless.
        after={"name": name, "code": code, "payout_method": payout_method},
    )
    return affiliate


def application_state(db: Session, affiliate: AffiliateProfile) -> str:
    """What to tell her about where her application stands.

    Three answers, not two. "Applied and waiting" and "on the programme" are
    completely different messages to the one person they are about, and an
    empty dashboard says neither.
    """
    if affiliate.status == AffiliateStatus.PENDING:
        return "waiting"
    if affiliate.status == AffiliateStatus.ACTIVE:
        return "active"
    return "paused"
