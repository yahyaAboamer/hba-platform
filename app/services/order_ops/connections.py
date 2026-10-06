"""The Bosta and E-stebdal keys: saved from Settings, or the server's own.

ADR 0057 §10, and the same three rules as the Shopify connection (ADR 0045):

- **Only an admin changes them** - the routes require ``settings.manage``.
- **The key is protected**: stored encrypted (Fernet, keyed by
  ``SETTINGS_ENCRYPTION_KEY``), never put in a response, a log line, an
  exception message or the audit trail. Settings shows only its last four
  characters, as the approved mockup does, to tell two keys apart.
- **A failed update never breaks the key in use**: a new key is tried
  against its provider first, with one read, and nothing is written unless
  it answers.

Without a saved key, the server's variable (``BOSTA_API_KEY``,
``ESTEBDAL_API_KEY``) is used; without either, the tab is "not connected".
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.core.secrets import fernet, key_problem
from app.models.order_ops import OpsIntegrationKey
from app.services.audit import record_audit
from app.services.order_ops.polling import NotConnected, SourceUnavailable

PROVIDERS = {"bosta": "Bosta", "estebdal": "E-stebdal"}

#: Longer than any key either provider issues; a bound on what is stored.
MAX_KEY_LENGTH = 512


class KeyNotSaved(ValueError):
    """Why a key was not saved. Its text is safe to show."""


@dataclass(frozen=True)
class EffectiveKey:
    key: str
    #: ``saved``, ``environment``, or None when there is no key at all.
    source: str | None
    #: Something wrong with the saved key that made the server's be used.
    problem: str | None = None


def _require(provider: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider!r}")
    return provider


def _environment(provider: str, problem: str | None = None) -> EffectiveKey:
    key = (getattr(settings, f"{provider}_api_key") or "").strip()
    return EffectiveKey(key=key, source="environment" if key else None, problem=problem)


def effective(db: Session, provider: str) -> EffectiveKey:
    """The key in use: the saved one if it can be read, else the server's."""
    row = db.get(OpsIntegrationKey, _require(provider))
    if row is None:
        return _environment(provider)
    protector = fernet()
    if protector is None:
        return _environment(
            provider,
            f"A key is saved, but this server cannot read it ({key_problem()}); "
            "the server's own key is in use.",
        )
    try:
        key = protector.decrypt(row.secret_encrypted.encode()).decode()
    except InvalidToken:
        return _environment(
            provider,
            "The saved key cannot be read with this server's key; the server's "
            "own key is in use until it is saved again.",
        )
    return EffectiveKey(key=key, source="saved")


def api_key(db: Session, provider: str) -> str:
    """The key a read uses; empty when there is none ("not connected")."""
    return effective(db, provider).key


def _hint(key: str) -> str | None:
    """"ends in a1b2" - only for a key long enough that four characters
    give nothing away."""
    return f"ends in {key[-4:]}" if len(key) >= 12 else None


def describe(db: Session, provider: str) -> dict:
    """What Settings shows. **Never the key**, only its last four characters."""
    current = effective(db, provider)
    row = db.get(OpsIntegrationKey, provider)
    saved = current.source == "saved" and row is not None
    return {
        "provider": provider,
        "label": PROVIDERS[provider],
        "source": current.source,
        "hint": _hint(current.key) if current.key else None,
        "verified_at": row.verified_at.isoformat() if saved else None,
        "problem": current.problem,
        "can_save": fernet() is not None,
        "key_problem": key_problem(),
    }


def check(provider: str, key: str) -> None:
    """One read with this key. Raises if the provider does not answer it."""
    if provider == "bosta":
        from app.services.order_ops.bosta import BostaClient

        client = BostaClient(key)
        try:
            client.check()
        finally:
            client.close()
    else:
        from app.services.order_ops.estebdal import EstebdalClient

        EstebdalClient(key).check()


def save(
    db: Session,
    provider: str,
    key: str,
    *,
    actor_id: int | None,
    actor_email: str | None,
    checker: Callable[[str, str], None] | None = None,
) -> dict:
    """Try the new key and, only if it answers, save it encrypted."""
    label = PROVIDERS[_require(provider)]
    protector = fernet()
    if protector is None:
        raise KeyNotSaved(
            f"This server cannot protect a saved key yet: {key_problem()}. Nothing was changed."
        )
    key = (key or "").strip()
    if not key:
        raise KeyNotSaved(f"Enter the {label} key. Nothing was changed.")
    # Printable ASCII only: a header carries nothing else, and a pasted smart
    # quote would otherwise fail inside the client rather than be refused here.
    if len(key) > MAX_KEY_LENGTH or not (key.isascii() and key.isprintable()) or " " in key:
        raise KeyNotSaved(f"That doesn't look like a {label} key. Nothing was changed.")

    try:
        (checker or check)(provider, key)
    except (SourceUnavailable, NotConnected) as exc:
        # Our own words (polling), never the provider's answer or the key.
        reason = str(exc) or f"{label} didn't answer."
        raise KeyNotSaved(
            f"{label} did not accept this key ({reason}). The key in use has not changed."
        ) from None

    before = effective(db, provider).source
    row = db.get(OpsIntegrationKey, provider)
    if row is None:
        row = OpsIntegrationKey(provider=provider)
        db.add(row)
    now = datetime.now(timezone.utc)
    row.secret_encrypted = protector.encrypt(key.encode()).decode()
    row.hint = key[-4:] if _hint(key) else ""
    row.verified_at = now
    row.updated_by = actor_id
    row.updated_at = now
    record_audit(
        db,
        action="order_ops.key_saved",
        subject=f"{provider}_key",
        actor_id=actor_id,
        actor_email=actor_email,
        # Where the key in use came from, and that it was replaced - never
        # any of its text.
        before={"provider": provider, "source": before},
        after={"provider": provider, "source": "saved"},
    )
    db.flush()
    return describe(db, provider)
