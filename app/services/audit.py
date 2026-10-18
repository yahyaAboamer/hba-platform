"""Recording audit events, with sensitive values masked before storage.

Masking happens on the way in, never on the way out. The table is append-only,
so a secret written into it could never be removed afterwards — the only safe
moment to mask is before the insert.

Two matching strategies run together. An exact list covers the fields known
today; a set of substring patterns catches the ones nobody has added yet.
Matching only an exact list would leak the next field someone introduces, and
in an audit trail that mistake is permanent.

record_audit only stages the row. The caller commits, so the audit entry and
the change it describes land in the same transaction: either both happen or
neither does.
"""

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditEvent

MAX_DEPTH = 12
VISIBLE_SUFFIX = 4

#: Fields known to be sensitive today.
SENSITIVE_FIELDS = frozenset(
    {
        "instapay_address_url",
        "instapay_phone",
        "bank_account_number",
        "bank_account_holder",
        "wallet_phone",
        "password",
        "password_hash",
        "token",
        "token_hash",
        "csrf",
        "csrf_hash",
    }
)

#: Substrings that make a field sensitive whatever it is called. Deliberately
#: specific: "account" alone would swallow account_status and make the trail
#: useless, while "account_number" cannot match anything innocent.
SENSITIVE_PATTERNS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "account_number",
    "instapay",
    "wallet_phone",
    "iban",
    "cvv",
    "card_number",
)


def _is_sensitive(key: str) -> bool:
    lowered = str(key).lower()
    if lowered in SENSITIVE_FIELDS:
        return True
    return any(pattern in lowered for pattern in SENSITIVE_PATTERNS)


def _mask_value(value: Any) -> Any:
    """Show only enough to recognise a value, never enough to reuse it.

    None is preserved. Masking a null would imply a value existed where none
    did, which is its own small lie in a record meant to be trustworthy.
    """
    if value is None:
        return None
    text_value = str(value)
    if len(text_value) <= VISIBLE_SUFFIX:
        return "*" * VISIBLE_SUFFIX
    return f"{'*' * VISIBLE_SUFFIX}{text_value[-VISIBLE_SUFFIX:]}"


def mask_sensitive(payload: Any, _depth: int = 0) -> Any:
    """Recursively mask sensitive fields in a structure bound for the audit log."""
    if _depth >= MAX_DEPTH:
        return "<truncated>"
    if isinstance(payload, dict):
        return {
            key: (
                _mask_value(value)
                if _is_sensitive(key)
                else mask_sensitive(value, _depth + 1)
            )
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple)):
        return [mask_sensitive(item, _depth + 1) for item in payload]
    return payload


def record_audit(
    db: Session,
    *,
    action: str,
    subject: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
) -> AuditEvent:
    """Stage an audit event. The caller commits it with the change it describes."""
    event = AuditEvent(
        action=action,
        subject=subject,
        actor_id=actor_id,
        actor_email=actor_email,
        before_json=mask_sensitive(before) if before is not None else None,
        after_json=mask_sensitive(after) if after is not None else None,
        reason=reason,
        ip_address=ip_address,
    )
    db.add(event)
    return event


#: The activity log's kinds (Settings audit R1), by the start of an action.
#: Every action the platform records falls in exactly one - a test walks the
#: source to keep that true.
KINDS: dict[str, tuple[str, ...]] = {
    "money": ("payroll.", "payment.", "payout_destination.", "compensation."),
    "access": (
        "auth.",
        "invitation.",
        "staff.role_changed",
        "staff.suspended",
        "staff.reactivated",
    ),
    # `portal.previewed`: staff looking at her portal, read only (ADR 0064).
    "models": ("affiliate.", "application.", "code.", "parcel.", "portal."),
    "content": ("target.",),
    "settings": (
        "shopify.",
        "order_ops.key_saved",
        "inbox.whatsapp_saved",
        "inbox.sending_changed",
        "inbox.tags_connection_saved",
        "policy_version.",
        "staff.preference_changed",
    ),
    # What staff did to an order's confirmation from the Inbox (ADR 0059).
    "inbox": ("inbox.confirmation_resent", "inbox.answer_set"),
}

#: Signing in and out: true, recorded, and the thing that buried every payment
#: under a busy day's log-ins (R3). Hidden unless asked for.
SIGN_IN_ACTIONS = ("auth.login", "auth.logout")

#: `affiliate:12`, `user:3`, `invitation:nour@example.com` - an exact subject,
#: copied from somewhere. Matched whole, so `affiliate:1` is not also 10 to 19.
_SUBJECT = re.compile(r"^(affiliate|user|invitation|policy_version):\S+$")

#: The escape character for LIKE patterns below.
_ESCAPE = "\\"


def kind_of(action: str) -> str | None:
    """Which of `KINDS` an action belongs to, or `None`."""
    for name, prefixes in KINDS.items():
        if any(action.startswith(prefix) for prefix in prefixes):
            return name
    return None


def _like(text: str) -> str:
    """`%` and `_` typed into a search are letters, not wildcards."""
    escaped = (
        text.replace(_ESCAPE, _ESCAPE * 2)
        .replace("%", _ESCAPE + "%")
        .replace("_", _ESCAPE + "_")
    )
    return f"%{escaped}%"


def recent_events(
    db: Session,
    *,
    limit: int = 50,
    subject_contains: str | None = None,
    q: str | None = None,
    affiliate_id: int | None = None,
    actor_id: int | None = None,
    kind: str | None = None,
    include_sign_ins: bool = True,
    before_id: int | None = None,
) -> list[AuditEvent]:
    """The most recent business events, newest first. Read-only counterpart to
    `record_audit` - nothing here writes, and this is the only function in the
    module that reads.

    `q` is what a person types: a model's name, a colleague's name or address,
    a word from a reason - or an exact subject such as `affiliate:12`. The box
    promised "or a name" and searched only subjects, which never hold one:
    *Sara* found nothing while a dozen entries were about her (R1).

    `subject_contains` is the older substring filter, kept for its callers.
    `before_id` pages backwards: everything older than the last entry already
    shown (R2).
    """
    from sqlalchemy import or_, tuple_

    from app.models.affiliates import AffiliateProfile
    from app.models.identity import UserAccount

    query = select(AuditEvent)
    if subject_contains:
        query = query.where(
            AuditEvent.subject.ilike(_like(subject_contains), escape=_ESCAPE)
        )
    if affiliate_id is not None:
        query = query.where(AuditEvent.subject == f"affiliate:{affiliate_id}")
    if actor_id is not None:
        query = query.where(AuditEvent.actor_id == actor_id)
    if kind:
        prefixes = KINDS.get(kind)
        if prefixes is None:
            raise ValueError(f"No such kind: {kind!r}")
        query = query.where(
            or_(*(AuditEvent.action.startswith(p, autoescape=True) for p in prefixes))
        )
    if not include_sign_ins:
        query = query.where(AuditEvent.action.notin_(SIGN_IN_ACTIONS))

    text = (q or "").strip()
    if text and _SUBJECT.match(text):
        query = query.where(AuditEvent.subject == text)
    elif text:
        pattern = _like(text)
        model_ids = list(
            db.scalars(
                select(AffiliateProfile.id).where(
                    AffiliateProfile.name.ilike(pattern, escape=_ESCAPE)
                )
            )
        )
        people_ids = list(
            db.scalars(
                select(UserAccount.id).where(
                    or_(
                        UserAccount.display_name.ilike(pattern, escape=_ESCAPE),
                        UserAccount.email.ilike(pattern, escape=_ESCAPE),
                    )
                )
            )
        )
        query = query.where(
            or_(
                AuditEvent.subject.ilike(pattern, escape=_ESCAPE),
                AuditEvent.reason.ilike(pattern, escape=_ESCAPE),
                AuditEvent.actor_email.ilike(pattern, escape=_ESCAPE),
                AuditEvent.subject.in_([f"affiliate:{m}" for m in model_ids]),
                AuditEvent.subject.in_([f"user:{p}" for p in people_ids]),
                AuditEvent.actor_id.in_(people_ids),
            )
        )

    if before_id is not None:
        anchor = db.get(AuditEvent, before_id)
        # An anchor that is not there means nothing older can be named -
        # answering with page one again would loop a caller for ever.
        if anchor is None:
            return []
        if anchor is not None:
            query = query.where(
                tuple_(AuditEvent.created_at, AuditEvent.id)
                < tuple_(anchor.created_at, anchor.id)
            )
    query = query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    return list(db.scalars(query.limit(limit)))
