"""WhatsApp, through Meta's Cloud API. The only code that talks to it.

Three rules, the same ones the Shopify client keeps:

- **No key ever reaches an exception, a log line or the ``repr``.** Meta's
  error bodies can carry a phone number or echo a request back, so a refusal
  is said in our own words with Meta's error *code* and nothing else of
  Meta's.
- **The access key travels in a header, never in an address**, where a proxy
  or a log would keep it.
- **A file is fetched only from Meta.** The address of a customer's photo
  arrives inside a callback, and following it anywhere it points would let a
  forged callback make this server fetch from wherever it liked.

Whether a number may be messaged at all is not decided here: see
``app.modules.inbox.services.sending``.
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import settings

GRAPH = "https://graph.facebook.com"

#: WhatsApp's own ceiling for a file is 100 MB (a document); nothing larger is
#: a file it sent.
MAX_MEDIA_BYTES = 100 * 1024 * 1024

#: Where Meta serves a customer's file from. Matched on the whole host or a
#: dot-separated ending, never a bare ``endswith``.
MEDIA_HOSTS = ("facebook.com", "fbsbx.com", "fbcdn.net", "whatsapp.net")

MEDIA_KINDS = ("image", "audio", "video", "document", "sticker")


class MetaError(RuntimeError):
    """WhatsApp refused, or did not answer. The text is safe to show.

    ``kind`` is what the caller branches on; ``retryable`` says whether the
    same request is worth sending again later.
    """

    def __init__(
        self, message: str, *, kind: str = "refused", code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retryable = retryable


#: Meta's error code -> (kind, our words, worth retrying).
_KNOWN: dict[int, tuple[str, str, bool]] = {
    190: ("auth", "WhatsApp did not accept the access key", False),
    10: ("auth", "The access key may not use this WhatsApp number", False),
    200: ("auth", "The access key may not use this WhatsApp number", False),
    100: ("invalid", "WhatsApp did not understand the request", False),
    4: ("throttled", "WhatsApp is limiting how fast we send", True),
    80007: ("throttled", "WhatsApp is limiting how fast we send", True),
    130429: ("throttled", "WhatsApp is limiting how fast we send", True),
    131056: ("throttled", "Too many messages to this number in a short time", True),
    131026: ("undeliverable", "WhatsApp could not reach this number", False),
    131047: (
        "window_closed",
        "More than 24 hours have passed since the customer's last message",
        False,
    ),
    131051: ("invalid", "WhatsApp does not support this kind of message", False),
    131052: ("media", "WhatsApp could not fetch the file", False),
    131053: ("media", "WhatsApp could not accept the file", False),
    132000: ("template", "The approved message was sent with the wrong number of details", False),
    132001: ("template", "WhatsApp has no approved message by that name and language", False),
    132012: ("template", "The approved message's details are in the wrong form", False),
    132015: ("template", "WhatsApp has paused this approved message", False),
    132016: ("template", "WhatsApp has switched this approved message off", False),
    131000: ("unavailable", "WhatsApp did not answer", True),
    131016: ("unavailable", "WhatsApp did not answer", True),
    1: ("unavailable", "WhatsApp did not answer", True),
    2: ("unavailable", "WhatsApp did not answer", True),
}


def failure_words(code: object) -> tuple[str, str]:
    """``(kind, words)`` for the code Meta gives when a message is not delivered.

    A delivery failure arrives later, in a callback, with the same codes a
    refused request carries. Said in the same words, and with nothing of
    Meta's own text - which can name the customer's number.
    """
    code = code if isinstance(code, int) and not isinstance(code, bool) else None
    if code in _KNOWN:
        kind, words, _ = _KNOWN[code]
        return kind, f"{words} (code {code})"
    suffix = f" (code {code})" if code is not None else ""
    return "refused", f"WhatsApp could not deliver the message{suffix}"


def verify_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    """Whether a callback was signed by Meta. Fails closed.

    Meta signs the exact bytes it sends with the app secret and puts
    ``sha256=<hex>`` in ``X-Hub-Signature-256``. An unset secret returns
    False: a missing key must never turn into "accept everything".
    """
    if not app_secret or not header_value or not header_value.startswith("sha256="):
        return False
    provided = header_value[len("sha256="):].strip().lower()
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


def is_meta_media_url(url: str) -> bool:
    """Whether ``url`` is an https address on one of Meta's file hosts."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    return any(host == allowed or host.endswith("." + allowed) for allowed in MEDIA_HOSTS)


@dataclass(frozen=True)
class NumberInfo:
    """What Meta says about the number the keys belong to."""

    display_number: str | None
    verified_name: str | None
    quality_rating: str | None


@dataclass(frozen=True)
class MediaInfo:
    url: str
    mime_type: str | None
    sha256: str | None
    size_bytes: int | None


class MetaClient:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        *,
        api_version: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not access_token or not phone_number_id:
            raise MetaError("WhatsApp is not connected", kind="not_connected")
        # An id is digits. Anything else would be built into the address.
        if not str(phone_number_id).isdigit():
            raise MetaError("That is not a WhatsApp number ID", kind="invalid")
        self.phone_number_id = str(phone_number_id)
        self.api_version = api_version or settings.meta_api_version
        self._token = access_token
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout_seconds or settings.meta_timeout_seconds,
        )

    def __repr__(self) -> str:
        return f"MetaClient(phone_number_id={self.phone_number_id!r})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "MetaClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── Requests ──────────────────────────────────────────────────────────────

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.api_version}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(
                method,
                self._url(path),
                headers={"Authorization": f"Bearer {self._token}"},
                **kwargs,
            )
        except httpx.HTTPError:
            raise MetaError(
                "WhatsApp did not answer", kind="unavailable", retryable=True
            ) from None
        return self._read(response)

    @staticmethod
    def _read(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code < 400 and isinstance(body, dict) and "error" not in body:
            return body

        error = body.get("error") if isinstance(body, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        code = code if isinstance(code, int) else None
        if code in _KNOWN:
            kind, words, retryable = _KNOWN[code]
            raise MetaError(f"{words} (code {code})", kind=kind, code=code, retryable=retryable)
        if response.status_code in (401, 403):
            raise MetaError("WhatsApp did not accept the access key", kind="auth", code=code)
        if response.status_code == 429 or response.status_code >= 500:
            raise MetaError(
                "WhatsApp did not answer", kind="unavailable", code=code, retryable=True
            )
        suffix = f" (code {code})" if code is not None else f" ({response.status_code})"
        raise MetaError(f"WhatsApp refused the request{suffix}", code=code)

    def _send(self, to: str, payload: dict[str, Any], reply_to: str | None = None) -> str:
        """Send one message and return WhatsApp's id for it."""
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            **payload,
        }
        if reply_to:
            body["context"] = {"message_id": reply_to}
        answer = self._request("POST", f"{self.phone_number_id}/messages", json=body)
        try:
            return str(answer["messages"][0]["id"])
        except (KeyError, IndexError, TypeError):
            raise MetaError("WhatsApp accepted the message but named no id") from None

    # ── The number ────────────────────────────────────────────────────────────

    def check(self) -> NumberInfo:
        """One read with these keys. Raises if Meta does not answer them."""
        answer = self._request(
            "GET",
            self.phone_number_id,
            params={"fields": "display_phone_number,verified_name,quality_rating"},
        )
        return NumberInfo(
            display_number=answer.get("display_phone_number"),
            verified_name=answer.get("verified_name"),
            quality_rating=answer.get("quality_rating"),
        )

    def templates(self, business_account_id: str) -> list[dict[str, Any]]:
        """The approved messages on the business account, newest page only.

        Each is Meta's own description: ``name``, ``language``, ``status``,
        ``category`` and ``components``.
        """
        if not str(business_account_id).isdigit():
            raise MetaError("That is not a WhatsApp business account ID", kind="invalid")
        answer = self._request(
            "GET",
            f"{business_account_id}/message_templates",
            params={"fields": "name,language,status,category,components", "limit": 100},
        )
        data = answer.get("data")
        return data if isinstance(data, list) else []

    # ── Sending ───────────────────────────────────────────────────────────────

    def send_text(self, to: str, body: str, *, reply_to: str | None = None) -> str:
        return self._send(
            to, {"type": "text", "text": {"body": body, "preview_url": False}}, reply_to
        )

    def send_template(
        self,
        to: str,
        name: str,
        language: str,
        components: list[dict[str, Any]] | None = None,
    ) -> str:
        template: dict[str, Any] = {"name": name, "language": {"code": language}}
        if components:
            template["components"] = components
        return self._send(to, {"type": "template", "template": template})

    def send_media(
        self,
        to: str,
        kind: str,
        media_id: str,
        *,
        caption: str | None = None,
        filename: str | None = None,
        voice: bool = False,
        reply_to: str | None = None,
    ) -> str:
        """Send a file already uploaded with :meth:`upload_media`."""
        if kind not in MEDIA_KINDS:
            raise MetaError("WhatsApp does not support this kind of file", kind="invalid")
        media: dict[str, Any] = {"id": media_id}
        if caption and kind in ("image", "video", "document"):
            media["caption"] = caption
        if filename and kind == "document":
            media["filename"] = filename
        if voice and kind == "audio":
            # Shown as a voice note with a waveform, not as an audio file.
            media["voice"] = True
        return self._send(to, {"type": kind, kind: media}, reply_to)

    def send_reaction(self, to: str, wa_message_id: str, emoji: str) -> str:
        """React to a message. An empty ``emoji`` takes the reaction back."""
        return self._send(
            to, {"type": "reaction", "reaction": {"message_id": wa_message_id, "emoji": emoji}}
        )

    def mark_read(self, wa_message_id: str) -> None:
        """Turn the customer's ticks blue for a message of hers."""
        self._request(
            "POST",
            f"{self.phone_number_id}/messages",
            json={"messaging_product": "whatsapp", "status": "read", "message_id": wa_message_id},
        )

    # ── Files ─────────────────────────────────────────────────────────────────

    def upload_media(self, content: bytes, mime_type: str, filename: str) -> str:
        """Hand Meta a file to send, and return its id."""
        answer = self._request(
            "POST",
            f"{self.phone_number_id}/media",
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": (filename, content, mime_type)},
        )
        media_id = answer.get("id")
        if not media_id:
            raise MetaError("WhatsApp accepted the file but named no id", kind="media")
        return str(media_id)

    def media_info(self, media_id: str) -> MediaInfo:
        """Where a customer's file is, for the next five minutes."""
        if not str(media_id).isdigit():
            raise MetaError("That is not a WhatsApp file ID", kind="invalid")
        try:
            answer = self._request("GET", str(media_id))
        except MetaError as exc:
            # Meta answers "no such object" (code 100) for a file it has
            # deleted - after 7 days for one a customer sent.
            if exc.code == 100:
                raise MetaError("WhatsApp no longer has this file", kind="gone", code=100) from None
            raise
        url = answer.get("url")
        if not isinstance(url, str) or not is_meta_media_url(url):
            raise MetaError("WhatsApp named no usable address for the file", kind="media")
        size = answer.get("file_size")
        return MediaInfo(
            url=url,
            mime_type=answer.get("mime_type"),
            sha256=answer.get("sha256"),
            size_bytes=int(size) if isinstance(size, (int, str)) and str(size).isdigit() else None,
        )

    def download(self, url: str, *, max_bytes: int = MAX_MEDIA_BYTES) -> bytes:
        """Fetch a customer's file. Only from Meta, and only up to ``max_bytes``."""
        if not is_meta_media_url(url):
            raise MetaError("That address is not one of WhatsApp's", kind="media")
        try:
            with self._http.stream(
                "GET", url, headers={"Authorization": f"Bearer {self._token}"}
            ) as response:
                if response.status_code in (401, 403):
                    raise MetaError("WhatsApp did not accept the access key", kind="auth")
                if response.status_code == 404:
                    raise MetaError("WhatsApp no longer has this file", kind="gone")
                if response.status_code >= 400:
                    raise MetaError(
                        "WhatsApp did not hand over the file",
                        kind="unavailable",
                        retryable=response.status_code >= 500,
                    )
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise MetaError("The file is larger than WhatsApp allows", kind="media")
                    chunks.append(chunk)
        except httpx.HTTPError:
            raise MetaError(
                "WhatsApp did not answer", kind="unavailable", retryable=True
            ) from None
        return b"".join(chunks)
