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

from typing import Any

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
