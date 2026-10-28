"""The inbox's two connections, saved from Settings (ADR 0059).

**WhatsApp**: the number's ID, its business account's ID, and three secrets -
the access key, the app secret that signs Meta's callbacks, and the check
word Meta repeats back when the callback address is set.

**Shopify, for tags**: a second app on the same store, used only to add and
remove the five confirmation tags (ADR 0059, point 11). The connection that
reads money stays read-only (ADR 0015), so this one must be a different app.

The same three rules as the Shopify connection (ADR 0045):

- **Only an admin changes them** - the routes require ``settings.manage``.
- **Every secret is protected**: stored encrypted (Fernet, keyed by
  ``SETTINGS_ENCRYPTION_KEY``), never put in a response, a log line, an
  exception message or the audit trail. Settings shows only the last four
  characters of a key, to tell two apart.
- **A failed update never breaks what is in use**: new keys are tried against
  their provider first, and nothing is written unless they answer.

There is no fallback to the server's own variables: unlike Shopify, nothing
ran on environment keys before this, so there is nothing to fall back to.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from cryptography.fernet import InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.core.secrets import fernet, key_problem
from app.modules.inbox.models import InboxConnection, ShopifyTagsConnection
from app.shared.services.audit import record_audit
from app.modules.inbox.services.meta import MetaClient, MetaError, NumberInfo
from app.shared.services.shopify.client import ShopifyClient, ShopifyError
from app.shared.services.shopify.connection import effective as shopify_effective

#: Longer than any key Meta or Shopify issues; a bound on what is stored.
MAX_SECRET_LENGTH = 1024

#: What the tags connection must be allowed to do, and all it is used for.
TAGS_SCOPE = "write_orders"


class NotSaved(ValueError):
    """Why a connection was not saved. Its text is safe to show."""


@dataclass(frozen=True)
class WhatsApp:
    """The WhatsApp connection in use, with its secrets. Never serialised."""

    phone_number_id: str
    business_account_id: str
    access_token: str
    app_secret: str
    verify_token: str
    sending_enabled: bool

    def __repr__(self) -> str:
        return f"WhatsApp(phone_number_id={self.phone_number_id!r})"


@dataclass(frozen=True)
class TagsApp:
    """The second Shopify connection, with its secret. Never serialised."""

    shop_domain: str
    client_id: str
    client_secret: str

    def __repr__(self) -> str:
        return f"TagsApp(shop_domain={self.shop_domain!r})"


def _unreadable() -> str:
    reason = key_problem()
    if reason:
        return f"It is saved, but this server cannot read it ({reason})."
    return "It is saved, but cannot be read with this server's key. Save it again."


def _decrypt(*tokens: str) -> tuple[str, ...] | None:
    """Every token decrypted, or None if this server cannot read them."""
    protector = fernet()
    if protector is None:
        return None
    try:
        return tuple(protector.decrypt(token.encode()).decode() for token in tokens)
    except InvalidToken:
        return None


def _hint(secret: str) -> str:
    """Its last four characters - only for a secret long enough that four
    give nothing away."""
    return secret[-4:] if len(secret) >= 12 else ""


def _clean(value: str | None, label: str) -> str:
    """A pasted secret, trimmed and checked. Refused in words, never echoed."""
    value = (value or "").strip()
    # Printable ASCII only: a header carries nothing else, and a pasted smart
    # quote would otherwise fail inside the client rather than be refused here.
    if len(value) > MAX_SECRET_LENGTH or not (value.isascii() and value.isprintable()) or " " in value:
        raise NotSaved(f"That doesn't look like {label}. Nothing was changed.")
    return value


def _protector():
    protector = fernet()
    if protector is None:
        raise NotSaved(
            f"This server cannot protect a saved key yet: {key_problem()}. Nothing was changed."
        )
    return protector


# ── WhatsApp ──────────────────────────────────────────────────────────────────


def whatsapp(db: Session) -> WhatsApp | None:
    """The connection in use, or None when there is none this server can read."""
    row = db.get(InboxConnection, 1)
    if row is None:
        return None
    secrets = _decrypt(
        row.access_token_encrypted, row.app_secret_encrypted, row.verify_token_encrypted
    )
    if secrets is None:
        return None
    return WhatsApp(
        phone_number_id=row.phone_number_id,
        business_account_id=row.business_account_id,
        access_token=secrets[0],
        app_secret=secrets[1],
        verify_token=secrets[2],
        sending_enabled=row.sending_enabled,
    )


def describe_whatsapp(db: Session) -> dict:
    """What Settings shows. **No secret**, only two keys' last four characters."""
    row = db.get(InboxConnection, 1)
    readable = row is not None and whatsapp(db) is not None
    return {
        "connected": readable,
        "phone_number_id": row.phone_number_id if row else None,
        "business_account_id": row.business_account_id if row else None,
        "display_number": row.display_number if row else None,
        "verified_name": row.verified_name if row else None,
        "access_token_hint": (row.access_token_hint or None) if row else None,
        "app_secret_hint": (row.app_secret_hint or None) if row else None,
        "verified_at": row.verified_at.isoformat() if row else None,
        "sending_enabled": bool(row and readable and row.sending_enabled),
        "problem": _unreadable() if row is not None and not readable else None,
        "can_save": fernet() is not None,
        "key_problem": key_problem(),
        # Said beside the switch, so nobody expects a staging server to send.
        "test_numbers_only": not settings.inbox_send_to_customers,
    }


def check_whatsapp(access_token: str, phone_number_id: str, business_account_id: str) -> NumberInfo:
    """Two reads with these keys: the number, and its business account.

    The second proves the business account ID is this number's, which is what
    the approved messages are later read from. The app secret cannot be proved
    here - Meta offers nothing to try it against - so it is proved by the
    first signed callback instead.
    """
    with MetaClient(access_token, phone_number_id) as client:
        info = client.check()
        client.templates(business_account_id)
    return info


def save_whatsapp(
    db: Session,
    *,
    phone_number_id: str,
    business_account_id: str,
    access_token: str = "",
    app_secret: str = "",
    verify_token: str = "",
    actor_id: int | None,
    actor_email: str | None,
    checker: Callable[[str, str, str], NumberInfo] | None = None,
) -> dict:
    """Try the new keys and, only if Meta answers them, save them encrypted.

    A secret left blank keeps the saved one, so one key can be replaced
    without retyping the other two. The first save needs all three.
    """
    protector = _protector()
    phone_number_id = (phone_number_id or "").strip()
    business_account_id = (business_account_id or "").strip()
    if not (phone_number_id.isdigit() and len(phone_number_id) <= 40):
        raise NotSaved("The WhatsApp number ID is a number. Nothing was changed.")
    if not (business_account_id.isdigit() and len(business_account_id) <= 40):
        raise NotSaved("The WhatsApp business account ID is a number. Nothing was changed.")
    access_token = _clean(access_token, "a WhatsApp access key")
    app_secret = _clean(app_secret, "an app secret")
    verify_token = _clean(verify_token, "a check word")

    row = db.get(InboxConnection, 1)
    current = whatsapp(db)
    if current is None and row is not None and not (access_token and app_secret and verify_token):
        raise NotSaved(
            "The saved keys cannot be read by this server, so all three are "
            "needed again. Nothing was changed."
        )
    access_token = access_token or (current.access_token if current else "")
    app_secret = app_secret or (current.app_secret if current else "")
    verify_token = verify_token or (current.verify_token if current else "")
    if not (access_token and app_secret and verify_token):
        raise NotSaved(
            "Enter the access key, the app secret and the check word. Nothing was changed."
        )

    try:
        info = (checker or check_whatsapp)(access_token, phone_number_id, business_account_id)
    except MetaError as exc:
        # Our own words (meta), never Meta's answer or a key.
        raise NotSaved(
            f"WhatsApp did not accept these details ({exc}). The connection in use has not changed."
        ) from None

    before = {"phone_number_id": row.phone_number_id} if row else None
    # A different number is a different inbox: it does not inherit the switch.
    same_number = row is not None and row.phone_number_id == phone_number_id
    if row is None:
        row = InboxConnection(id=1)
        db.add(row)
    now = datetime.now(timezone.utc)
    row.phone_number_id = phone_number_id
    row.business_account_id = business_account_id
    row.display_number = info.display_number
    row.verified_name = info.verified_name
    row.access_token_encrypted = protector.encrypt(access_token.encode()).decode()
    row.app_secret_encrypted = protector.encrypt(app_secret.encode()).decode()
    row.verify_token_encrypted = protector.encrypt(verify_token.encode()).decode()
    row.access_token_hint = _hint(access_token)
    row.app_secret_hint = _hint(app_secret)
    row.verified_at = now
    row.sending_enabled = bool(same_number and row.sending_enabled)
    row.updated_by = actor_id
    row.updated_at = now
    record_audit(
        db,
        action="inbox.whatsapp_saved",
        subject="whatsapp_connection",
        actor_id=actor_id,
        actor_email=actor_email,
        # Which number, and that its keys were replaced - never any of them.
        before=before,
        after={"phone_number_id": phone_number_id},
    )
    db.flush()
    return describe_whatsapp(db)


def set_sending(
    db: Session, enabled: bool, *, actor_id: int | None, actor_email: str | None
) -> dict:
    """Turn sending on or off. On needs a connection this server can read."""
    row = db.get(InboxConnection, 1)
    if row is None or whatsapp(db) is None:
        raise NotSaved("Connect WhatsApp before turning sending on. Nothing was changed.")
    if row.sending_enabled != enabled:
        record_audit(
            db,
            action="inbox.sending_changed",
            subject="whatsapp_connection",
            actor_id=actor_id,
            actor_email=actor_email,
            before={"sending": row.sending_enabled},
            after={"sending": enabled},
        )
        row.sending_enabled = enabled
        row.updated_by = actor_id
        row.updated_at = datetime.now(timezone.utc)
        db.flush()
    return describe_whatsapp(db)


# ── Shopify, for tags ─────────────────────────────────────────────────────────


def tags_app(db: Session) -> TagsApp | None:
    """The tags connection in use, or None when there is none readable."""
    row = db.get(ShopifyTagsConnection, 1)
    shop_domain = shopify_effective(db).shop_domain
    if row is None or not shop_domain:
        return None
    secrets = _decrypt(row.client_secret_encrypted)
    if secrets is None:
        return None
    return TagsApp(shop_domain=shop_domain, client_id=row.client_id, client_secret=secrets[0])


def describe_tags(db: Session) -> dict:
    """What Settings shows. **No secret.**"""
    row = db.get(ShopifyTagsConnection, 1)
    readable = row is not None and _decrypt(row.client_secret_encrypted) is not None
    return {
        "connected": readable,
        "shop_domain": shopify_effective(db).shop_domain or None,
        "client_id_hint": row.client_id[-4:] if row and len(row.client_id) > 4 else None,
        "client_secret_hint": (row.client_secret_hint or None) if row else None,
        "verified_at": row.verified_at.isoformat() if row else None,
        "problem": _unreadable() if row is not None and not readable else None,
        "can_save": fernet() is not None,
        "key_problem": key_problem(),
    }


def check_tags(shop_domain: str, client_id: str, client_secret: str) -> set[str]:
    """Exchange the credentials for a token and return what it may do."""
    client = ShopifyClient(
        shop_domain=shop_domain,
        client_id=client_id,
        client_secret=client_secret,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_timeout_seconds,
    )
    client.execute("{ shop { name } }")
    return client.granted_scopes()


def save_tags(
    db: Session,
    *,
    client_id: str,
    client_secret: str,
    actor_id: int | None,
    actor_email: str | None,
    checker: Callable[[str, str, str], set[str]] | None = None,
) -> dict:
    """Try the second app's credentials and, only if Shopify answers them and
    they may write order tags, save them encrypted."""
    protector = _protector()
    main = shopify_effective(db)
    if not main.shop_domain:
        raise NotSaved("Connect Shopify first: this uses the same store. Nothing was changed.")
    client_id = _clean(client_id, "a Shopify client ID")
    client_secret = _clean(client_secret, "a Shopify client secret")
    if not client_id or not client_secret or len(client_id) > 255:
        raise NotSaved("Enter the app's client ID and client secret. Nothing was changed.")
    # ADR 0059, point 11: the connection that reads money never gains the
    # power to write. Saving its own app here would do exactly that.
    if main.client_id and client_id == main.client_id:
        raise NotSaved(
            "That is the app the platform already reads Shopify with, which must "
            "stay read-only. Use the other app. Nothing was changed."
        )

    try:
        scopes = (checker or check_tags)(main.shop_domain, client_id, client_secret)
    except ShopifyError as exc:
        # The client's own words: a status code at most, never a credential.
        raise NotSaved(
            f"Shopify did not accept these details ({exc}). The connection in use has not changed."
        ) from None
    if TAGS_SCOPE not in scopes:
        raise NotSaved(
            "Shopify accepted that app, but it may not change orders "
            f"(it lacks {TAGS_SCOPE}), so it cannot write tags. Nothing was changed."
        )

    row = db.get(ShopifyTagsConnection, 1)
    replaced = row is not None
    if row is None:
        row = ShopifyTagsConnection(id=1)
        db.add(row)
    now = datetime.now(timezone.utc)
    row.client_id = client_id
    row.client_secret_encrypted = protector.encrypt(client_secret.encode()).decode()
    row.client_secret_hint = _hint(client_secret)
    row.verified_at = now
    row.updated_by = actor_id
    row.updated_at = now
    record_audit(
        db,
        action="inbox.tags_connection_saved",
        subject="shopify_tags_connection",
        actor_id=actor_id,
        actor_email=actor_email,
        before={"saved": replaced},
        after={"saved": True},
    )
    db.flush()
    return describe_tags(db)
