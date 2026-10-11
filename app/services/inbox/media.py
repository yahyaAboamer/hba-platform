"""A chat's files: photos, voice notes, videos and documents (ADR 0059,
point 12).

**Copied when it arrives.** WhatsApp deletes a customer's file after 7 days,
so the callback that brings a message queues its file to be fetched from
Meta and put in our own bucket. Until then the chat shows it as waiting; if
WhatsApp no longer has it, as gone.

**Served only to someone signed in who holds the inbox**, and never straight
from the bucket: the browser asks this server, which checks who is asking.

**A customer's file is never run by our own page.** What a file claims to be
is hers to choose, so only a short list of kinds is shown in place - a photo,
audio, a video, a PDF - and everything else is handed over as a download,
with the browser told not to guess.

A file's place in the bucket is ``inbox/<conversation>/<message>/<file>``:
numbers of ours, and no name or phone.
"""

import hashlib
import logging

from sqlalchemy.orm import Session

from app.models.inbox import InboxConversation, InboxMedia, InboxMessage
from app.services.inbox import connection, outbound, storage
from app.services.inbox.meta import MetaClient, MetaError
from app.services.jobs import JobKind, PermanentFailure, enqueue
from app.worker import register_handler

logger = logging.getLogger(__name__)

#: The largest file copied from a customer. WhatsApp allows a document of
#: 100 MB; this server holds a file in memory while it copies it, and is small.
INBOUND_MAX_BYTES = 25 * 1024 * 1024

#: What may be shown in the page itself, and the ending its copy is kept under.
#: Anything else is a download.
SHOWN_IN_PLACE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/amr": "amr",
    "video/mp4": "mp4",
    "video/3gpp": "3gp",
    "application/pdf": "pdf",
}

#: What staff may send: the kind WhatsApp treats it as, and its own limit for
#: that kind (documents capped at ours).
SENDABLE: dict[str, tuple[str, int]] = {
    "image/jpeg": ("image", 5 * 1024 * 1024),
    "image/png": ("image", 5 * 1024 * 1024),
    "audio/ogg": ("audio", 16 * 1024 * 1024),
    "audio/mpeg": ("audio", 16 * 1024 * 1024),
    "audio/mp4": ("audio", 16 * 1024 * 1024),
    "audio/aac": ("audio", 16 * 1024 * 1024),
    "audio/amr": ("audio", 16 * 1024 * 1024),
    "video/mp4": ("video", 16 * 1024 * 1024),
    "video/3gpp": ("video", 16 * 1024 * 1024),
    "application/pdf": ("document", INBOUND_MAX_BYTES),
    "application/msword": ("document", INBOUND_MAX_BYTES),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ("document", INBOUND_MAX_BYTES),
    "application/vnd.ms-excel": ("document", INBOUND_MAX_BYTES),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ("document", INBOUND_MAX_BYTES),
    "text/plain": ("document", INBOUND_MAX_BYTES),
}
MAX_UPLOAD_BYTES = max(limit for _, limit in SENDABLE.values())

TOO_LARGE = "The file is larger than this inbox keeps."
NOT_KEPT = "The file was sent, but this inbox could not keep its own copy."


class Unavailable(LookupError):
    """The file cannot be handed over. The text is safe to show."""


class NotSendable(ValueError):
    """Why a file cannot be sent. The text is safe to show."""


def mime_of(raw: object) -> str:
    """``audio/ogg; codecs=opus`` -> ``audio/ogg``."""
    return str(raw or "").split(";")[0].strip().lower()


def storage_key(media: InboxMedia, conversation_id: int) -> str:
    ending = SHOWN_IN_PLACE.get(mime_of(media.mime_type), "bin")
    return f"inbox/{conversation_id}/{media.message_id}/{media.id}.{ending}"


# ── Copying a customer's file ─────────────────────────────────────────────────


def queue_fetch(db: Session, media_id: int) -> None:
    enqueue(
        db,
        JobKind.INBOX_FETCH_MEDIA,
        {"media_id": media_id},
        dedupe_key=f"{JobKind.INBOX_FETCH_MEDIA}:{media_id}",
    )


def fetch(
    db: Session,
    media_id: int,
    *,
    client: MetaClient | None = None,
    store: storage.Bucket | None = None,
) -> InboxMedia | None:
    """Copy one waiting file from Meta into the bucket.

    A file Meta no longer has becomes ``gone``, and one that cannot be kept -
    too large, or refused for good - ``failed``. Anything that might pass on
    another try raises, so the job is tried again while Meta still has it.
    A server with no bucket, or no readable WhatsApp keys, leaves the file
    waiting and does nothing.
    """
    media = db.get(InboxMedia, media_id)
    if media is None or media.state != "pending" or not media.wa_media_id:
        return media
    message = db.get(InboxMessage, media.message_id)
    keys = connection.whatsapp(db)
    if message is None or keys is None or (store is None and not storage.configured()):
        return media

    owned_client, owned_store = client is None, store is None
    client = client or MetaClient(keys.access_token, keys.phone_number_id)
    try:
        try:
            info = client.media_info(media.wa_media_id)
            if info.size_bytes and info.size_bytes > INBOUND_MAX_BYTES:
                media.state = "failed"
                return media
            content = client.download(info.url, max_bytes=INBOUND_MAX_BYTES)
        except MetaError as exc:
            if exc.kind == "gone":
                media.state = "gone"
                return media
            if exc.retryable or exc.kind == "auth":
                raise
            media.state = "failed"
            return media

        media.mime_type = mime_of(info.mime_type or media.mime_type) or None
        media.size_bytes = len(content)
        media.sha256 = hashlib.sha256(content).hexdigest()
        key = storage_key(media, message.conversation_id)
        store = store or storage.bucket()
        try:
            store.put(key, content, media.mime_type or "application/octet-stream")
        except storage.StorageError as exc:
            if exc.retryable:
                raise
            media.state = "failed"
            return media
        media.storage_key = key
        media.state = "stored"
        return media
    finally:
        if owned_client:
            client.close()
        if owned_store and store is not None:
            store.close()
        db.flush()


@register_handler(JobKind.INBOX_FETCH_MEDIA)
def _handle_fetch_media(db: Session, payload: dict) -> None:
    media_id = payload.get("media_id")
    if not isinstance(media_id, int):
        raise PermanentFailure(
            f"{JobKind.INBOX_FETCH_MEDIA} requires a media_id; got payload keys {sorted(payload)!r}"
        )
    fetch(db, media_id)


# ── Handing a file to the page ────────────────────────────────────────────────


def read(db: Session, media_id: int, *, store: storage.Bucket | None = None) -> dict:
    """A stored file, and how the browser is to treat it."""
    media = db.get(InboxMedia, media_id)
    if media is None:
        raise Unavailable("No such file.")
    if media.state != "stored" or not media.storage_key:
        raise Unavailable(
            "This file is no longer available." if media.state == "gone" else "This file is not ready yet."
        )
    owned = store is None
    try:
        store = store or storage.bucket()
        content = store.get(media.storage_key)
    except storage.StorageError as exc:
        raise Unavailable(str(exc)) from None
    finally:
        if owned and store is not None:
            store.close()

    mime = mime_of(media.mime_type)
    in_place = mime in SHOWN_IN_PLACE
    # The name she gave it, cut down to what is safe inside a header.
    name = "".join(c for c in (media.filename or "") if c.isalnum() or c in " ._-")[:120].strip()
    return {
        "content": content,
        # Never her own claim for anything not on the list: a page of hers
        # must not be run as a page of ours.
        "mime_type": mime if in_place else "application/octet-stream",
        "filename": name or f"file-{media.id}.{SHOWN_IN_PLACE.get(mime, 'bin')}",
        "inline": in_place,
    }


# ── A file staff send ─────────────────────────────────────────────────────────


def send_file(
    db: Session,
    conversation_id: int,
    *,
    content: bytes,
    mime_type: str,
    filename: str,
    caption: str | None,
    voice: bool,
    actor_id: int,
    reply_to: str | None = None,
    client: MetaClient | None = None,
    store: storage.Bucket | None = None,
) -> tuple[InboxMessage, InboxMedia | None]:
    """Send a photo, a voice note, a video or a document, and keep our copy.

    Refused before WhatsApp is asked when it is a kind or a size WhatsApp
    will not take. The message goes out through ``outbound`` like every
    other, so under the same rule on who may be messaged.
    """
    conversation = db.get(InboxConversation, conversation_id)
    if conversation is None:
        raise LookupError("No such conversation.")
    mime = mime_of(mime_type)
    if mime not in SENDABLE:
        raise NotSendable("WhatsApp does not take this kind of file.")
    kind, limit = SENDABLE[mime]
    if not content:
        raise NotSendable("The file is empty.")
    if len(content) > limit:
        raise NotSendable(f"That is larger than WhatsApp allows for this kind of file ({limit // (1024 * 1024)} MB).")
    safe_name = "".join(c for c in (filename or "") if c.isalnum() or c in " ._-")[:120].strip() or "file"

    message = outbound.send_file(
        db,
        conversation,
        kind=kind,
        content=content,
        mime_type=mime,
        filename=safe_name,
        caption=(caption or "").strip()[:1024] or None,
        # A voice note is Opus in an Ogg file; anything else is an audio file.
        voice=bool(voice and mime == "audio/ogg"),
        sent_by=actor_id,
        reply_to=reply_to,
        client=client,
    )
    media = InboxMedia(
        message_id=message.id,
        mime_type=mime,
        filename=safe_name,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        state="pending",
    )
    db.add(media)
    db.flush()
    # Our own copy, so the chat can show what was sent. Without a bucket, or
    # if it refuses, the message has still gone and says its copy was not kept.
    owned = store is None
    try:
        store = store or storage.bucket()
        key = storage_key(media, conversation.id)
        store.put(key, content, mime)
        media.storage_key = key
        media.state = "stored"
    except storage.StorageError as exc:
        logger.warning("a sent file's copy was not kept: %s", exc)
        media.state = "failed"
    finally:
        if owned and store is not None:
            store.close()
    db.flush()
    return message, media
