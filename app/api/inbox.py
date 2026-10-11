"""The customer inbox: WhatsApp chats and order confirmations (ADR 0059).

Every route here is behind ``inbox.use``, held by customer service, the
operations manager and the admin, and by nobody else. The guard is on the
router itself rather than repeated per route, so a route added later cannot
be added without it.

So far only the connections, for Settings. The chats come with the inbox's
own screens.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import UserAccount
from app.services.inbox import connection

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.INBOX_USE)

router = APIRouter(prefix="/api/inbox", tags=["inbox"], dependencies=[Depends(GUARD)])

# ── The connections, for Settings ─────────────────────────────────────────────

#: Changing a key is an admin's: ``settings.manage`` on top of the router's
#: own guard, which an admin holds as well. Customer service and the
#: operations manager use the inbox and never see its keys.
SETTINGS_GUARD = require_permission(Permission.SETTINGS_MANAGE)


class WhatsAppBody(BaseModel):
    #: No length or shape rule here: a validation error would echo the value
    #: back. ``connection.save_whatsapp`` checks each and refuses in its own
    #: words. A secret left blank keeps the saved one.
    phone_number_id: str = ""
    business_account_id: str = ""
    access_token: str = ""
    app_secret: str = ""
    verify_token: str = ""


class TagsBody(BaseModel):
    client_id: str = ""
    client_secret: str = ""


class SendingBody(BaseModel):
    enabled: bool


def _described(db: Session) -> dict:
    return {
        "whatsapp": connection.describe_whatsapp(db),
        "tags": connection.describe_tags(db),
    }


@router.get("/connection")
def connection_state(
    _actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Both connections, for Settings. **Never a key**, only last-four hints."""
    return _described(db)


@router.put("/connection/whatsapp")
def save_whatsapp(
    body: WhatsAppBody,
    actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Save the WhatsApp keys - only if Meta answers them.

    A refusal leaves the connection in use exactly as it was, and says why in
    words safe to show; no key is ever echoed back, logged or audited.
    """
    try:
        connection.save_whatsapp(
            db,
            phone_number_id=body.phone_number_id,
            business_account_id=body.business_account_id,
            access_token=body.access_token,
            app_secret=body.app_secret,
            verify_token=body.verify_token,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except connection.NotSaved as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _described(db)


@router.put("/connection/tags")
def save_tags(
    body: TagsBody,
    actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Save the second Shopify app - only if Shopify answers it, it may change
    orders, and it is not the app the platform reads money with."""
    try:
        connection.save_tags(
            db,
            client_id=body.client_id,
            client_secret=body.client_secret,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except connection.NotSaved as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _described(db)


@router.put("/connection/sending")
def set_sending(
    body: SendingBody,
    actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Turn sending on or off. Off by default, and off again after the number
    is changed."""
    try:
        connection.set_sending(
            db, body.enabled, actor_id=actor.id, actor_email=actor.email
        )
    except connection.NotSaved as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return _described(db)
