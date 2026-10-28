"""The customer inbox: WhatsApp chats and order confirmations (ADR 0059).

Every route here is behind ``inbox.use``, held by customer service, the
operations manager and the admin, and by nobody else. The guard is on the
router itself rather than repeated per route, so a route added later cannot
be added without it.

The chats, the Confirmations screen, and the connections for Settings.
These are the only routes that return a customer's name, phone and words.

A refusal says why in words safe to show: 404 for a chat or an order that is
not there, 422 for something that cannot be done as asked, and 409 for a
message that may not be sent - sending is off, this server may not message
that customer, or her 24 hours have passed.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.shared.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.shared.models.identity import UserAccount
from app.modules.inbox.models import InboxMessage
from app.modules.inbox.services import chats, connection, health, media, outbound, sending
from app.modules.inbox.services.meta import MetaClient, MetaError

logger = logging.getLogger(__name__)

#: The one guard, kept by name so a test can find it on every route.
GUARD = require_permission(Permission.INBOX_USE)

router = APIRouter(prefix="/api/inbox", tags=["inbox"], dependencies=[Depends(GUARD)])

# ── The chats ─────────────────────────────────────────────────────────────────


def _answering(call):
    """Run ``call``, turning each refusal into its status."""
    try:
        return call()
    except chats.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except chats.Refused as exc:
        raise HTTPException(422, str(exc)) from None
    except outbound.NotSent as exc:
        raise HTTPException(409, str(exc)) from None


class ReplyBody(BaseModel):
    body: str = ""
    #: The message this answers, by our own id.
    reply_to: int | None = None


class ReactionBody(BaseModel):
    message_id: int
    #: One emoji; empty takes the reaction back.
    emoji: str = ""


class AnswerBody(BaseModel):
    answer: str


@router.get("/conversations")
def conversations(
    view: Literal["all", "unread", "edit", "cancelled"] = "all",
    q: str | None = Query(None, max_length=120),
    before: str | None = Query(None, max_length=80),
    limit: int | None = Query(None, ge=1, le=100),
    db: Session = Depends(get_session),
) -> dict:
    """One page of the list, newest first, with the chips' counts."""
    body = _answering(lambda: chats.list_conversations(db, view=view, q=q, before=before, limit=limit))
    body["counts"] = chats.counts(db)
    return body


@router.get("/health")
def inbox_health(db: Session = Depends(get_session)) -> dict:
    """Whether WhatsApp is connected, sending and being heard from."""
    return health.pulse(db)


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: int, db: Session = Depends(get_session)) -> dict:
    """A chat's header, and the customer's orders beside it."""
    return _answering(lambda: chats.conversation_detail(db, conversation_id))


@router.get("/conversations/{conversation_id}/messages")
def messages(
    conversation_id: int,
    before: str | None = Query(None, max_length=80),
    limit: int | None = Query(None, ge=1, le=100),
    db: Session = Depends(get_session),
) -> dict:
    """One page of the chat, ending at its newest message or at ``before``."""
    return _answering(lambda: chats.list_messages(db, conversation_id, before=before, limit=limit))


@router.get("/conversations/{conversation_id}/search")
def search(
    conversation_id: int,
    q: str = Query(..., max_length=120),
    db: Session = Depends(get_session),
) -> dict:
    """The messages in this chat that hold ``q``, newest first."""
    return _answering(lambda: chats.search_messages(db, conversation_id, q))


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    body: ReplyBody,
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """A reply from a member of staff. It carries their name.

    A message WhatsApp refuses is still returned, as failed with the reason:
    it is in the chat, so whoever sent it sees that it did not go.
    """
    sent = _answering(
        lambda: chats.reply(db, conversation_id, body.body, actor_id=actor.id, reply_to=body.reply_to)
    )
    db.commit()
    return sent


@router.post("/conversations/{conversation_id}/reactions")
def send_reaction(
    conversation_id: int,
    body: ReactionBody,
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    sent = _answering(
        lambda: chats.react(db, conversation_id, body.message_id, body.emoji, actor_id=actor.id)
    )
    db.commit()
    return sent


@router.post("/conversations/{conversation_id}/read")
def read(conversation_id: int, db: Session = Depends(get_session)) -> dict:
    """Clear the unread count, and turn her ticks blue where this server may
    message her. The count is ours; the ticks are a courtesy and never fail
    the request."""
    last = _answering(lambda: chats.mark_read(db, conversation_id))
    db.commit()
    detail = chats.conversation_detail(db, conversation_id)
    keys = connection.whatsapp(db)
    if last and keys and sending.refusal(db, detail["phone"]) is None:
        try:
            with MetaClient(keys.access_token, keys.phone_number_id) as client:
                client.mark_read(last)
        except MetaError as exc:
            logger.info("could not mark a chat read on WhatsApp: %s", exc)
    return detail


# ── Files ─────────────────────────────────────────────────────────────────────


@router.get("/media/{media_id}")
def file(media_id: int, db: Session = Depends(get_session)) -> Response:
    """A chat's file, to someone signed in who holds the inbox.

    Never straight from the bucket, and never as a page of ours: only a
    photo, audio, a video or a PDF is shown in place; anything else is a
    download, and the browser is told not to guess what it is.
    """
    try:
        found = media.read(db, media_id)
    except media.Unavailable as exc:
        raise HTTPException(404, str(exc)) from None
    disposition = "inline" if found["inline"] else "attachment"
    return Response(
        content=found["content"],
        media_type=found["mime_type"],
        headers={
            "Content-Disposition": f'{disposition}; filename="{found["filename"]}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            # No Cache-Control here: the app marks every API response
            # no-store, which is right for a customer's file too.
        },
    )


@router.post("/media/{media_id}/try-again")
def try_file_again(media_id: int, db: Session = Depends(get_session)) -> dict:
    """Ask WhatsApp again for one of her files that was not kept.

    Done now rather than queued, so whoever asked sees the photo or the
    reason it still cannot be copied.
    """
    try:
        found, problem = media.try_again(db, media_id)
    except media.Unavailable as exc:
        raise HTTPException(422, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    db.commit()
    message = db.get(InboxMessage, found.message_id)
    return {
        "state": found.state,
        "url": f"/api/inbox/media/{found.id}" if found.state == "stored" else None,
        "can_try_again": media.can_try_again(found, message),
        "problem": problem,
    }


@router.post("/conversations/{conversation_id}/media")
async def send_file(
    conversation_id: int,
    upload: UploadFile = File(...),
    caption: str = Form(""),
    voice: bool = Form(False),
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """A photo, a voice note, a video or a document from a member of staff."""
    # One byte past the largest file WhatsApp takes: enough to know it is
    # too large without holding more of it.
    content = await upload.read(media.MAX_UPLOAD_BYTES + 1)
    if len(content) > media.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That file is larger than WhatsApp allows.")
    try:
        message, kept = media.send_file(
            db,
            conversation_id,
            content=content,
            mime_type=upload.content_type or "",
            filename=upload.filename or "",
            caption=caption,
            voice=voice,
            actor_id=actor.id,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except media.NotSendable as exc:
        raise HTTPException(422, str(exc)) from None
    except outbound.NotSent as exc:
        raise HTTPException(409, str(exc)) from None
    db.commit()
    return chats.describe_message(message, actor.display_name, kept)


@router.get("/templates")
def templates(db: Session = Depends(get_session)) -> dict:
    """The approved messages, read from Meta: what can be sent once her 24
    hours have passed. Only the approved ones, what a person needs to tell
    them apart, and whether each can be sent from a chat as it stands."""
    keys = connection.whatsapp(db)
    if keys is None:
        raise HTTPException(409, sending.NOT_CONNECTED)
    try:
        with MetaClient(keys.access_token, keys.phone_number_id) as client:
            found = client.templates(keys.business_account_id)
    except MetaError as exc:
        raise HTTPException(502, str(exc)) from None
    return {"templates": chats.describe_templates(found)}


class TemplateBody(BaseModel):
    name: str
    language: str


@router.post("/conversations/{conversation_id}/template")
def send_template(
    conversation_id: int,
    body: TemplateBody,
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Send one of the approved messages as it stands: the way to reach a
    customer whose 24 hours have passed.

    Meta's list is read again for the send, so only a message approved now,
    with nothing left to fill in, can go out.
    """
    keys = connection.whatsapp(db)
    if keys is None:
        raise HTTPException(409, sending.NOT_CONNECTED)
    try:
        with MetaClient(keys.access_token, keys.phone_number_id) as client:
            found = client.templates(keys.business_account_id)
            sent = _answering(
                lambda: chats.send_template(
                    db, conversation_id, body.name, body.language,
                    found=found, actor_id=actor.id, client=client,
                )
            )
    except MetaError as exc:
        raise HTTPException(502, str(exc)) from None
    db.commit()
    return sent


# ── Confirmations ─────────────────────────────────────────────────────────────


@router.get("/confirmations")
def confirmations(
    tile: Literal["waiting", "edit", "cancelled", "not_sent", "no_whatsapp", "confirmed"] | None = None,
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_session),
) -> dict:
    """Where each cash-on-delivery order's confirmation stands."""
    return _answering(lambda: chats.confirmations(db, tile=tile, days=days))


@router.post("/confirmations/{order_id}/send-again")
def send_again(
    order_id: str,
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Queue an order's confirmation again. Refused for an order that
    already has one, so it can never become a second message."""
    order = _answering(
        lambda: chats.send_again(db, order_id, actor_id=actor.id, actor_email=actor.email)
    )
    db.commit()
    return order


@router.post("/confirmations/{order_id}/answer")
def set_answer(
    order_id: str,
    body: AnswerBody,
    actor: UserAccount = Depends(GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """Record the customer's answer by hand. Changes the order's tag in
    Shopify; does not cancel or edit the order there."""
    order = _answering(
        lambda: chats.set_answer(db, order_id, body.answer, actor_id=actor.id, actor_email=actor.email)
    )
    db.commit()
    return order


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


@router.get("/connection/health")
def connection_health(
    _actor: UserAccount = Depends(SETTINGS_GUARD),
    db: Session = Depends(get_session),
) -> dict:
    """For the Settings card: when WhatsApp was last heard from, and Meta's
    own rating of the number, read now.

    Apart from the card's other details, so a slow answer from Meta holds up
    one line and not the screen. A rating that cannot be read is absent, not
    guessed.
    """
    rating = None
    keys = connection.whatsapp(db)
    if keys is not None:
        try:
            with MetaClient(keys.access_token, keys.phone_number_id) as client:
                rating = client.check().quality_rating
        except MetaError as exc:
            logger.info("could not read the WhatsApp number's rating: %s", exc)
    return {**health.pulse(db), "rating": rating}


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
