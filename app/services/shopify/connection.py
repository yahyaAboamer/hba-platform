"""The Shopify connection: saved from Settings, or the environment's.

Owner, decision b (25 September): the connection is edited in Settings, with
*Store domain*, *Client ID* and *Client secret* (HBA's app is a Dev Dashboard
app, ADR 0015 - there is no permanent Admin API key to enter). Three rules,
all his:

- **Only authorised staff change it** - the route requires `settings.manage`.
- **The secret is protected**: stored encrypted (Fernet, keyed by
  `SETTINGS_ENCRYPTION_KEY`), and never put in a response, a log line, an
  exception message or the audit trail - not even its last characters.
- **A failed update never destroys the working connection**: new credentials
  are tried against Shopify first, and nothing is written unless they answer
  and hold every scope the platform needs.

It reads Shopify only (`{ shop { name } }`). Nothing here, and nothing the
connection is used for, edits an order or a product; the app holds read scopes
only (ADR 0015).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models.integration import ShopifyConnection
from app.services.audit import record_audit
from app.services.shopify.client import (
    REQUIRED_SCOPES,
    ShopifyClient,
    ShopifyError,
)

SHOP_QUERY = "{ shop { name } }"


class ConnectionRefused(ValueError):
    """Why a new connection was not saved. Its text is safe to show."""


@dataclass(frozen=True)
class Effective:
    shop_domain: str
    client_id: str
    client_secret: str
    access_token: str
    #: `saved`, `environment`, or `None` when there is no connection at all.
    source: str | None
    #: Something wrong with the saved connection that made us fall back.
    problem: str | None = None


def _fernet() -> Fernet | None:
    key = (settings.settings_encryption_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        # A malformed key is a configuration fault; saying so beats storing a
        # secret under something that is not a key.
        return None


def _environment(problem: str | None = None) -> Effective:
    configured = settings.shopify_configured
    return Effective(
        shop_domain=settings.shopify_shop_domain,
        client_id=settings.shopify_client_id,
        client_secret=settings.shopify_client_secret,
        access_token=settings.shopify_access_token,
        source="environment" if configured else None,
        problem=problem,
    )


def effective(db: Session) -> Effective:
    """The connection in use: the saved one if it can be read, else the
    environment's."""
    row = db.get(ShopifyConnection, 1)
    if row is None:
        return _environment()
    fernet = _fernet()
    if fernet is None:
        return _environment(
            "A connection is saved, but this server has no key to read it "
            "(SETTINGS_ENCRYPTION_KEY); the environment's connection is in use."
        )
    try:
        secret = fernet.decrypt(row.client_secret_encrypted.encode()).decode()
    except InvalidToken:
        return _environment(
            "The saved connection cannot be read with this server's key; the "
            "environment's connection is in use until it is saved again."
        )
    return Effective(
        shop_domain=row.shop_domain,
        client_id=row.client_id,
        client_secret=secret,
        access_token="",
        source="saved",
    )


def client_for(connection: Effective) -> ShopifyClient:
    return ShopifyClient(
        shop_domain=connection.shop_domain,
        client_id=connection.client_id,
        client_secret=connection.client_secret,
        access_token=connection.access_token,
        api_version=settings.shopify_api_version,
        timeout_seconds=settings.shopify_timeout_seconds,
    )


def _hint(value: str) -> str:
    """The last four characters of a client ID, so a person can tell two apart.

    Never used for the secret."""
    value = value or ""
    return f"••••{value[-4:]}" if len(value) > 4 else "••••"


def describe(db: Session) -> dict:
    """What Settings shows. **No secret, in any form.**"""
    connection = effective(db)
    row = db.get(ShopifyConnection, 1)
    return {
        "source": connection.source,
        "shop_domain": connection.shop_domain or None,
        "client_id_hint": _hint(connection.client_id) if connection.client_id else None,
        "secret_saved": bool(connection.client_secret or connection.access_token),
        "verified_at": row.verified_at.isoformat() if row and connection.source == "saved" else None,
        "shop_name": row.shop_name if row and connection.source == "saved" else None,
        "problem": connection.problem,
        "can_save": _fernet() is not None,
    }


def check(shop_domain: str, client_id: str, client_secret: str) -> tuple[str, set[str]]:
    """Ask Shopify with these credentials. Returns the shop's name and the
    scopes granted; raises `ShopifyError` if it does not answer."""
    client = client_for(
        Effective(shop_domain, client_id, client_secret, "", source="candidate")
    )
    data = client.execute(SHOP_QUERY)
    return str((data.get("shop") or {}).get("name") or ""), client.granted_scopes()


def save(
    db: Session,
    *,
    shop_domain: str,
    client_id: str,
    client_secret: str | None,
    actor_id: int | None,
    actor_email: str | None,
    checker: Callable[[str, str, str], tuple[str, set[str]]] | None = None,
) -> dict:
    """Try the new connection and, only if it works, save it.

    `client_secret` blank keeps the saved one - the field is never sent back
    to the browser, so an unchanged form arrives without it.
    """
    fernet = _fernet()
    if fernet is None:
        raise ConnectionRefused(
            "This server cannot protect a saved secret yet: SETTINGS_ENCRYPTION_KEY "
            "is not set. Nothing was changed."
        )
    domain = (shop_domain or "").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    if not domain:
        raise ConnectionRefused("Enter the store domain. Nothing was changed.")
    if "/" in domain or not domain.endswith(".myshopify.com"):
        raise ConnectionRefused(
            "The store domain should look like your-store.myshopify.com. Nothing was changed."
        )

    row = db.get(ShopifyConnection, 1)
    current = effective(db)
    # Neither the client ID nor the secret is sent back to the browser in
    # full, so a field left blank means *keep the saved one* - and there must
    # be a saved one to keep.
    client_id = (client_id or "").strip()
    if not client_id:
        if current.source != "saved":
            raise ConnectionRefused("Enter the client ID. Nothing was changed.")
        client_id = current.client_id
    secret = (client_secret or "").strip()
    secret_changed = bool(secret)
    if not secret:
        if current.source != "saved":
            raise ConnectionRefused("Enter the client secret. Nothing was changed.")
        secret = current.client_secret

    try:
        shop_name, granted = (checker or check)(domain, client_id, secret)
    except ShopifyError as exc:
        # The client's messages are our own text, never a credential (ADR 0015).
        raise ConnectionRefused(
            f"Shopify did not accept this connection ({exc}). The connection in use has not changed."
        ) from None
    missing = sorted(REQUIRED_SCOPES - granted) if granted else []
    if missing:
        raise ConnectionRefused(
            "Shopify answered, but the app is missing "
            + ", ".join(missing)
            + ". The connection in use has not changed."
        )

    before = {"shop_domain": row.shop_domain} if row else {"shop_domain": settings.shopify_shop_domain or None}
    row_client_before = row.client_id if row else (settings.shopify_client_id or None)
    if row is None:
        row = ShopifyConnection(id=1)
        db.add(row)
    row.shop_domain = domain
    row.client_id = client_id
    row.client_secret_encrypted = fernet.encrypt(secret.encode()).decode()
    row.verified_at = datetime.now(timezone.utc)
    row.shop_name = shop_name or None
    row.updated_by = actor_id
    row.updated_at = datetime.now(timezone.utc)
    record_audit(
        db,
        action="shopify.connection_updated",
        subject="shopify_connection",
        actor_id=actor_id,
        actor_email=actor_email,
        before=before,
        # The domain and *whether* the credentials changed - never any of
        # their text (decision b).
        after={
            "shop_domain": domain,
            "credentials": ("secret replaced" if secret_changed else "secret kept")
            + ("; client ID changed" if row_client_before not in (None, client_id) else ""),
        },
    )
    db.flush()
    return describe(db)
