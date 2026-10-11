"""The inbox's bucket client (ADR 0059, point 12). No bucket is called: a
mock transport answers. The one real thing here is the signature, checked
against the worked example in AWS's own documentation.
"""

import hashlib

import httpx
import pytest

from app.services.inbox import storage
from app.services.inbox.storage import Bucket, NotConfigured, StorageError, sign

ACCESS = "made-up-access-key-id"
SECRET = "made-up-secret-access-key-0000"


def _bucket(handler, **changes) -> Bucket:
    values = dict(
        bucket="inbox-media-test", endpoint="https://storage.example.test",
        access_key_id=ACCESS, secret_access_key=SECRET, region="auto",
        transport=httpx.MockTransport(handler),
    )
    values.update(changes)
    return Bucket(**values)


def test_the_signature_matches_awss_own_worked_example():
    """"Example: GET Object" from AWS's Signature Version 4 documentation.
    If this passes, the signing is the real algorithm and not a lookalike."""
    header = sign(
        method="GET",
        path="/test.txt",
        headers={
            "host": "examplebucket.s3.amazonaws.com",
            "range": "bytes=0-9",
            "x-amz-content-sha256": storage.EMPTY_SHA256,
            "x-amz-date": "20130524T000000Z",
        },
        payload_sha256=storage.EMPTY_SHA256,
        amz_date="20130524T000000Z",
        region="us-east-1",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    assert header == (
        "AWS4-HMAC-SHA256 "
        "Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
        "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    )


def test_a_file_is_put_at_the_buckets_own_address_signed_and_typed():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200)

    _bucket(handler).put("inbox/7/41/9.jpg", b"photo", "image/jpeg")
    (request,) = seen
    assert request.method == "PUT"
    assert str(request.url) == "https://inbox-media-test.storage.example.test/inbox/7/41/9.jpg"
    assert request.headers["content-type"] == "image/jpeg"
    assert request.headers["x-amz-content-sha256"] == hashlib.sha256(b"photo").hexdigest()
    assert request.headers["authorization"].startswith(f"AWS4-HMAC-SHA256 Credential={ACCESS}/")
    assert SECRET not in str(request.headers)
    assert request.content == b"photo"


def test_a_file_is_read_back_and_a_missing_one_says_so():
    bucket = _bucket(lambda request: httpx.Response(200, content=b"photo"))
    assert bucket.get("inbox/7/41/9.jpg") == b"photo"

    missing = _bucket(lambda request: httpx.Response(404))
    with pytest.raises(StorageError) as refused:
        missing.get("inbox/7/41/9.jpg")
    assert refused.value.missing is True
    missing.delete("inbox/7/41/9.jpg")  # already gone: nothing to do


@pytest.mark.parametrize(("status", "retryable"), [(500, True), (503, True), (429, True), (403, False)])
def test_a_refusal_says_whether_trying_again_can_help_and_echoes_nothing(status, retryable):
    bucket = _bucket(lambda request: httpx.Response(status, text=f"denied {SECRET}"))
    with pytest.raises(StorageError) as refused:
        bucket.put("inbox/1/1/1.jpg", b"x", "image/jpeg")
    assert refused.value.retryable is retryable
    assert SECRET not in str(refused.value)


def test_a_network_failure_is_worth_trying_again_and_names_no_key():
    def handler(request):
        raise httpx.ConnectError(f"boom {SECRET}")

    with pytest.raises(StorageError) as refused:
        _bucket(handler).get("inbox/1/1/1.jpg")
    assert refused.value.retryable is True
    assert SECRET not in str(refused.value)
    assert refused.value.__cause__ is None


@pytest.mark.parametrize(
    "key",
    ["", "/etc/passwd", "inbox/../secrets", "inbox/1/1/a b.jpg", "inbox/1/1/x?acl", "inbox/1/1/x#y", "http://elsewhere"],
)
def test_only_a_key_the_inbox_built_is_ever_asked_for(key):
    asked = []
    bucket = _bucket(lambda request: asked.append(request) or httpx.Response(200))
    with pytest.raises(StorageError):
        bucket.get(key)
    assert asked == []


@pytest.mark.parametrize(
    "changes",
    [
        {"bucket": ""},
        {"bucket": "elsewhere.example/x"},
        {"bucket": "Bucket_Name"},
        {"endpoint": "http://storage.example.test"},
        {"endpoint": "https://user:pass@storage.example.test"},
        {"endpoint": ""},
        {"access_key_id": ""},
        {"secret_access_key": ""},
    ],
)
def test_a_bucket_that_is_not_set_up_right_is_refused_before_anything_is_sent(changes):
    """The bucket name becomes part of the host: a wrong one would send the
    credentials somewhere else."""
    with pytest.raises(NotConfigured):
        _bucket(lambda request: httpx.Response(200), **changes)


def test_the_secret_is_not_in_the_repr():
    assert SECRET not in repr(_bucket(lambda request: httpx.Response(200)))


def test_a_server_with_no_bucket_says_so(monkeypatch):
    for name in ("bucket", "endpoint", "access_key_id", "secret_access_key"):
        monkeypatch.setattr(f"app.config.settings.inbox_media_{name}", "")
    assert storage.configured() is False
    with pytest.raises(NotConfigured):
        storage.bucket()
