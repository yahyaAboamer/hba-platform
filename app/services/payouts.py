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


#: InstaPay issues payment addresses on this domain. Confirmed by the
#: business tapping one on a phone: the OS handed it to the InstaPay app,
#: which is the entire reason §13.1 collects a link rather than a number.
INSTAPAY_HOST = "ipn.eg"


def normalise_instapay_address(value: str) -> str:
    """Check an InstaPay payment address is one, and return it cleaned.

    **The host is checked; the path is not.** The purpose of this field is the
    deep link, and a URL anywhere other than ipn.eg cannot open InstaPay - so
    the domain is a principled line rather than a guess. The path shape is a
    guess: no real address has ever been seen by this codebase, and refusing a
    genuine one because its path looks unfamiliar would block a model from
    joining at all. That is a far worse failure than accepting an odd-looking
    ipn.eg link.

    The mistake actually worth catching is a **phone number in the link
    field** - §13.1 collects both, they sit next to each other, and a model
    who mixes them up leaves the Pay button with nothing to open. Nothing
    errors at the time; it surfaces at month end when somebody tries to pay
    her.

    A missing scheme is added rather than refused. Somebody typing the address
    by hand omits `https://` far more often than they mean a different site.
    """
    import re
    from urllib.parse import urlparse

    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("An InstaPay payment address is needed")

    # Named before anything else, because it is the mistake this function
    # exists for and it deserves its own words. Left to the host check below
    # it produced "that one points at 01001234567", which is true and reads
    # as nonsense to the person who has to fix it.
    if re.fullmatch(r"[+\d][\d\s\-()]*", cleaned):
        raise ValueError(
            "That looks like a phone number. The payment address is a link "
            "starting https://ipn.eg/ - tap Link in InstaPay and copy it. "
            "Your number goes in the field below."
        )

    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").lower()

    if not host:
        raise ValueError(
            "That is not a payment address. It should be a link starting "
            "https://ipn.eg/ - copied from the Link button in InstaPay, not "
            "your phone number."
        )

    # Subdomains count: ipn.eg and anything.ipn.eg, never notipn.eg.
    if host != INSTAPAY_HOST and not host.endswith(f".{INSTAPAY_HOST}"):
        raise ValueError(
            f"An InstaPay payment address is a link on {INSTAPAY_HOST}. "
            f"That one points at {host}."
        )

    return cleaned


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

    # Here rather than at each caller, so the application, a model changing
    # her own destination, and a maintainer correcting one are all checked by
    # the same rule. A validator on one path is a validator with a way around
    # it.
    if method == PayoutMethod.INSTAPAY and instapay_address_url:
        instapay_address_url = normalise_instapay_address(instapay_address_url)

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


#: What the person sending the money needs, per method.
#:
#: InstaPay carries **both** its address and the phone number behind it. The
#: address feeds the deep link; the number is what a person types when the deep
#: link does not open - on a desktop it never will, and month-end payroll is
#: desktop work. Withholding the number would leave the payer stuck on the one
#: machine they are most likely using (ADR 0028, amended).
#:
#: It costs nothing to include. The address *is* the means of payment, so
#: anyone who may see it may see the number beside it.
PAYABLE_FIELDS = {
    PayoutMethod.INSTAPAY: ("instapay_address_url", "instapay_phone"),
    PayoutMethod.BANK: ("bank_name", "bank_account_holder", "bank_account_number"),
    PayoutMethod.WALLET: ("wallet_phone",),
}


def reveal_destination(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    actor_id: int,
    actor_email: str,
) -> dict:
    """The real values, for the one person about to send money. ADR 0028.

    Masking protects **records** - audit rows, logs, notifications, the
    confirmation shown when a destination changes. It was never meant to stop
    the payer paying: a bank account number rendered `…291` cannot be typed
    into a banking app, and reading the rule as absolute made the task
    impossible rather than safe.

    So the values are available, and getting them is a deliberate, recorded
    act rather than a side effect of opening a screen. The audit row says who
    looked at whose destination and when. **It never carries the value** -
    that would recreate exactly the leak the masking exists to prevent.
    """
    destination = current_destination(db, affiliate)
    if destination is None:
        raise ValueError("No payout destination on file")

    record_audit(
        db,
        action="payout_destination.revealed",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"method": destination.method},
    )

    fields = PAYABLE_FIELDS.get(destination.method, ())
    return {
        "method": destination.method,
        **{field: getattr(destination, field) for field in fields},
    }
