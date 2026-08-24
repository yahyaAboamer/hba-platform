"""Setting and reading payout destinations, and masking them.

**Nothing may put a raw destination into an audit record, a log line, or a
notification.** ``mask_destination`` is the only thing that may render one for
anywhere other than the screen of the person it belongs to (§6.4.4).

The masking rule: keep enough to *recognise*, never enough to *use*. Somebody
confirming a change has to be able to tell one destination from another, so
masking everything would make the confirmation meaningless - but the audit
trail must not become a way to read everybody's banking details.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.models.affiliates import AffiliateProfile
from app.models.payouts import VALID_METHODS, PayoutDestination, PayoutMethod
from app.services.audit import record_audit

#: How many trailing characters a mask keeps.
VISIBLE_TAIL = 3

#: Below this length, nothing is shown at all. Keeping the last three of a
#: four-character value has masked nothing.
MIN_MASKABLE_LENGTH = 8

#: Which fields each method requires. The others must be absent, so a bank row
#: cannot carry a stale InstaPay address that somebody later reads as current.
_REQUIRED_FIELD = {
    PayoutMethod.INSTAPAY: "instapay_address_url",
    PayoutMethod.BANK: "bank_account_number",
    PayoutMethod.WALLET: "wallet_phone",
}

#: Fields that are credentials. Masked everywhere, always.
_SENSITIVE = (
    "instapay_address_url",
    "instapay_phone",
    "bank_account_number",
    "wallet_phone",
)

#: Fields safe to show in full. The account holder's name is what a person
#: actually checks, and it is not a credential.
_VISIBLE = ("method", "bank_name", "bank_account_holder")


def mask_value(value: str | None) -> str | None:
    """Keep enough to recognise, never enough to use."""
    if value is None:
        return None
    text_value = str(value)
    if len(text_value) < MIN_MASKABLE_LENGTH:
        # Too short to mask meaningfully. Showing a tail of it would be showing
        # most of it.
        return "…"
    return f"…{text_value[-VISIBLE_TAIL:]}"


def mask_destination(destination: PayoutDestination | None) -> dict | None:
    """A destination rendered safe for an audit record, a log, or a message.

    The only sanctioned way to represent one outside the screen of the person
    it belongs to.
    """
    if destination is None:
        return None

    masked = {field: getattr(destination, field) for field in _VISIBLE}
    masked.update(
        {field: mask_value(getattr(destination, field)) for field in _SENSITIVE}
    )
    return masked


def current_destination(
    db: Session, affiliate: AffiliateProfile
) -> PayoutDestination | None:
    """Where this affiliate's money goes now."""
    return db.scalar(
        select(PayoutDestination)
        .where(PayoutDestination.affiliate_id == affiliate.id)
        .where(PayoutDestination.superseded_at.is_(None))
    )


def destination_history(
    db: Session, affiliate: AffiliateProfile
) -> list[PayoutDestination]:
    """Every destination this affiliate has had, newest first."""
    return list(
        db.scalars(
            select(PayoutDestination)
            .where(PayoutDestination.affiliate_id == affiliate.id)
            .order_by(PayoutDestination.id.desc())
        )
    )


def set_destination(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    method: str,
    instapay_address_url: str | None = None,
    instapay_phone: str | None = None,
    bank_name: str | None = None,
    bank_account_holder: str | None = None,
    bank_account_number: str | None = None,
    wallet_phone: str | None = None,
    approved_by: int | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayoutDestination:
    """Point an affiliate's money somewhere new.

    Writes a new row and supersedes the old one. Nothing is updated in place,
    so a payment made in March always resolves the destination in force then.

    The audit record carries **masked** values on both sides - what it changed
    from matters as much as what it changed to, and neither may be raw.
    """
    if method not in VALID_METHODS:
        raise ValueError(f"Unknown payout method: {method!r}")

    fields = {
        "instapay_address_url": instapay_address_url,
        "instapay_phone": instapay_phone,
        "bank_name": bank_name,
        "bank_account_holder": bank_account_holder,
        "bank_account_number": bank_account_number,
        "wallet_phone": wallet_phone,
    }

    required = _REQUIRED_FIELD[method]
    if not (fields[required] or "").strip():
        raise ValueError(f"A {method} destination requires {required}")

    previous = current_destination(db, affiliate)
    now = utcnow()

    destination = PayoutDestination(
        affiliate_id=affiliate.id,
        method=method,
        approved_by=approved_by,
        approved_at=now if approved_by else None,
        **{name: (value.strip() if isinstance(value, str) else value)
           for name, value in fields.items()},
    )
    db.add(destination)
    db.flush()

    if previous is not None:
        previous.superseded_at = now

    record_audit(
        db,
        action="payout_destination.changed" if previous else "payout_destination.set",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        before=mask_destination(previous),
        after=mask_destination(destination),
    )
    return destination


def changed_recently(
    db: Session, affiliate: AffiliateProfile, within_days: int = 7
) -> datetime | None:
    """When the destination last changed, if it was recent.

    §6.4.5 wants a prominent warning on the payment screen when a destination
    changed lately - the moment a redirected payout would actually cost money.
    The screen is Phase 8; this is the fact it will ask for.
    """
    current = current_destination(db, affiliate)
    if current is None:
        return None

    age = (utcnow() - current.created_at).days
    if age > within_days:
        return None

    # Only a *change* counts. The first destination an affiliate ever has is
    # not a redirection.
    has_history = db.scalar(
        select(PayoutDestination.id)
        .where(PayoutDestination.affiliate_id == affiliate.id)
        .where(PayoutDestination.superseded_at.is_not(None))
        .limit(1)
    )
    return current.created_at if has_history else None
