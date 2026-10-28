"""The inbox's own copy of a customer's files (ADR 0059, point 12).

An S3-compatible bucket on Railway, one per environment. WhatsApp deletes an
incoming file after 7 days, so each is copied here when it arrives.

**A small client of its own, not a library.** Three calls are all the inbox
makes - put, get, delete - and the platform runs on a small server where a
full S3 library would be most of the memory it uses. The signing below is
AWS Signature Version 4, checked in the tests against the worked example in
AWS's own documentation.

Railway's buckets are addressed with the bucket name as a subdomain of the
endpoint (as ``ops/backup`` also pins).

No credential reaches an exception, a log line or the ``repr``.
"""

import hashlib
import hmac
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit

import httpx

from app.config import settings

#: The only keys this module will sign for: ones the inbox built itself.
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.-]{0,399}")

EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class StorageError(RuntimeError):
    """The bucket refused, or did not answer. The text is safe to show."""

    def __init__(self, message: str, *, retryable: bool = False, missing: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.missing = missing


class NotConfigured(StorageError):
    """This server has no bucket to keep files in."""


def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).digest()


def sign(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    payload_sha256: str,
    amz_date: str,
    region: str,
    access_key_id: str,
    secret_access_key: str,
) -> str:
    """The ``Authorization`` header for one request (AWS Signature Version 4).

    ``headers`` are the headers to sign, lower-cased, and must include
    ``host``. ``path`` is already URI-encoded; the inbox sends no query.
    """
    names = sorted(headers)
    canonical_headers = "".join(f"{name}:{' '.join(headers[name].split())}\n" for name in names)
    signed = ";".join(names)
    canonical_request = "\n".join([method, path, "", canonical_headers, signed, payload_sha256])
    date = amz_date[:8]
    scope = f"{date}/{region}/s3/aws4_request"
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    key = _hmac(("AWS4" + secret_access_key).encode("utf-8"), date)
    for part in (region, "s3", "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
        f"SignedHeaders={signed}, Signature={signature}"
    )


class Bucket:
    def __init__(
        self,
        *,
        bucket: str,
        endpoint: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parts = urlsplit(endpoint if "://" in endpoint else f"https://{endpoint}")
        # A bucket name is built into the host. Anything but a plain name
        # would send the credentials somewhere else.
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,62}", bucket or "")
            or not access_key_id
            or not secret_access_key
        ):
            raise NotConfigured("This server has no place to keep files yet.")
        self.host = f"{bucket}.{parts.hostname}" + (f":{parts.port}" if parts.port else "")
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._region = region or "auto"
        self._http = httpx.Client(transport=transport, timeout=timeout_seconds)

    def __repr__(self) -> str:
        return f"Bucket(host={self.host!r})"

    def close(self) -> None:
        self._http.close()

    def _request(
        self, method: str, key: str, *, content: bytes = b"", content_type: str | None = None
    ) -> httpx.Response:
        if not _KEY.fullmatch(key) or ".." in key:
            raise StorageError("That is not a file the inbox keeps.")
        path = "/" + quote(key, safe="/-_.~")
        payload_sha256 = hashlib.sha256(content).hexdigest() if content else EMPTY_SHA256
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        signed = {
            "host": self.host,
            "x-amz-content-sha256": payload_sha256,
            "x-amz-date": amz_date,
        }
        headers = dict(signed)
        headers["authorization"] = sign(
            method=method,
            path=path,
            headers=signed,
            payload_sha256=payload_sha256,
            amz_date=amz_date,
            region=self._region,
            access_key_id=self._access_key_id,
            secret_access_key=self._secret_access_key,
        )
        if content_type:
            headers["content-type"] = content_type
        try:
            response = self._http.request(
                method, f"https://{self.host}{path}", headers=headers, content=content or None
            )
        except httpx.HTTPError:
            raise StorageError("The file store did not answer.", retryable=True) from None
        if response.status_code == 404:
            raise StorageError("The file store does not have this file.", missing=True)
        if response.status_code >= 400:
            # The body can echo the request; only the status is safe.
            raise StorageError(
                f"The file store refused the request ({response.status_code}).",
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        return response

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self._request("PUT", key, content=content, content_type=content_type)

    def get(self, key: str) -> bytes:
        return self._request("GET", key).content

    def delete(self, key: str) -> None:
        try:
            self._request("DELETE", key)
        except StorageError as exc:
            if not exc.missing:
                raise


def configured() -> bool:
    return bool(
        settings.inbox_media_bucket.strip()
        and settings.inbox_media_endpoint.strip()
        and settings.inbox_media_access_key_id.strip()
        and settings.inbox_media_secret_access_key.strip()
    )


def bucket() -> Bucket:
    """This server's bucket. Raises ``NotConfigured`` when it has none."""
    return Bucket(
        bucket=settings.inbox_media_bucket.strip(),
        endpoint=settings.inbox_media_endpoint.strip(),
        access_key_id=settings.inbox_media_access_key_id.strip(),
        secret_access_key=settings.inbox_media_secret_access_key.strip(),
        region=settings.inbox_media_region.strip() or "auto",
    )
