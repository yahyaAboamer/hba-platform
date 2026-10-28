"""The WhatsApp client (ADR 0059). Meta is never called: a mock transport
stands in, and every key and number here is made up."""

import hashlib
import hmac
import json

import httpx
import pytest

from app.modules.inbox.services.meta import (
    MetaClient,
    MetaError,
    is_meta_media_url,
    verify_signature,
)

TOKEN = "EAAG-made-up-access-key-0000a1b2"
NUMBER_ID = "100200300400500"
TO = "201005550188"


def _client(handler) -> MetaClient:
    return MetaClient(TOKEN, NUMBER_ID, api_version="v23.0", transport=httpx.MockTransport(handler))


def _sent(seen):
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.NEW"}]})

    return handler


def _body(request) -> dict:
    return json.loads(request.content)


# ── Sending ───────────────────────────────────────────────────────────────────


def test_a_text_goes_to_the_numbers_own_address_with_the_key_in_a_header():
    seen = []
    assert _client(_sent(seen)).send_text(TO, "Hello") == "wamid.NEW"
    (request,) = seen
    assert str(request.url) == f"https://graph.facebook.com/v23.0/{NUMBER_ID}/messages"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert _body(request) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": TO,
        "type": "text",
        "text": {"body": "Hello", "preview_url": False},
    }


def test_a_reply_names_the_message_it_answers():
    seen = []
    _client(_sent(seen)).send_text(TO, "Yes", reply_to="wamid.HERS")
    assert _body(seen[0])["context"] == {"message_id": "wamid.HERS"}


def test_the_order_confirmation_is_sent_as_the_approved_message():
    seen = []
    components = [
        {"type": "body", "parameters": [{"type": "text", "text": "#31044"}]},
        {
            "type": "button",
            "sub_type": "quick_reply",
            "index": "0",
            "parameters": [{"type": "payload", "payload": "confirm_5001"}],
        },
    ]
    _client(_sent(seen)).send_template(TO, "order_confirmation", "en", components)
    assert _body(seen[0])["template"] == {
        "name": "order_confirmation",
        "language": {"code": "en"},
        "components": components,
    }


def test_a_voice_note_is_sent_as_a_voice_note_and_a_file_keeps_its_name():
    seen = []
    client = _client(_sent(seen))
    client.send_media(TO, "audio", "9001", voice=True)
    client.send_media(TO, "document", "9002", caption="Receipt", filename="receipt.pdf")
    client.send_media(TO, "image", "9003", caption="This one", filename="ignored.jpg")
    assert _body(seen[0])["audio"] == {"id": "9001", "voice": True}
    assert _body(seen[1])["document"] == {
        "id": "9002", "caption": "Receipt", "filename": "receipt.pdf"
    }
    assert _body(seen[2])["image"] == {"id": "9003", "caption": "This one"}


def test_a_kind_whatsapp_does_not_have_is_refused_before_asking():
    seen = []
    with pytest.raises(MetaError, match="does not support this kind of file"):
        _client(_sent(seen)).send_media(TO, "hologram", "9001")
    assert seen == []


def test_a_reaction_and_a_read_mark_name_her_message():
    seen = []
    client = _client(_sent(seen))
    client.send_reaction(TO, "wamid.HERS", "❤️")
    client.mark_read("wamid.HERS")
    assert _body(seen[0])["reaction"] == {"message_id": "wamid.HERS", "emoji": "❤️"}
    assert _body(seen[1]) == {
        "messaging_product": "whatsapp", "status": "read", "message_id": "wamid.HERS"
    }


# ── Refusals ──────────────────────────────────────────────────────────────────


def _refusing(status: int, code: int | None, message: str = "(#x) echo 201005550188"):
    error = {"message": message, "type": "OAuthException"}
    if code is not None:
        error["code"] = code
    return lambda request: httpx.Response(status, json={"error": error})


@pytest.mark.parametrize(
    ("status", "code", "kind", "retryable", "words"),
    [
        (401, 190, "auth", False, "did not accept the access key"),
        (400, 131026, "undeliverable", False, "could not reach this number"),
        (400, 131047, "window_closed", False, "More than 24 hours"),
        (400, 132001, "template", False, "no approved message by that name"),
        (429, 130429, "throttled", True, "limiting how fast we send"),
        (500, None, "unavailable", True, "did not answer"),
        (400, 987654, "refused", False, "refused the request (code 987654)"),
    ],
)
def test_a_refusal_is_said_in_our_words_with_metas_code(status, code, kind, retryable, words):
    with pytest.raises(MetaError) as refused:
        _client(_refusing(status, code)).send_text(TO, "Hello")
    assert refused.value.kind == kind
    assert refused.value.retryable is retryable
    assert words in str(refused.value)


def test_nothing_of_metas_answer_or_the_key_reaches_the_refusal():
    """Meta's message can carry a phone number or echo the request back."""
    with pytest.raises(MetaError) as refused:
        _client(_refusing(400, 131026, f"to 201005550188 with {TOKEN}")).send_text(TO, "Hello")
    assert "201005550188" not in str(refused.value)
    assert TOKEN not in str(refused.value)


def test_a_network_failure_is_worth_trying_again_and_names_no_key():
    def handler(request):
        raise httpx.ConnectError(f"boom {TOKEN}")

    with pytest.raises(MetaError) as refused:
        _client(handler).send_text(TO, "Hello")
    assert refused.value.retryable is True
    assert TOKEN not in str(refused.value)
    assert refused.value.__cause__ is None


def test_the_key_is_not_in_the_clients_repr():
    assert TOKEN not in repr(_client(_sent([])))


@pytest.mark.parametrize(
    ("token", "number_id"),
    [("", NUMBER_ID), (TOKEN, ""), (TOKEN, "123/../456"), (TOKEN, "abc")],
)
def test_a_client_without_a_key_or_with_a_number_that_is_not_one_is_refused(token, number_id):
    with pytest.raises(MetaError):
        MetaClient(token, number_id)


# ── The number and its approved messages ──────────────────────────────────────


def test_the_check_reads_the_number_once():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "display_phone_number": "+20 100 555 0100",
                "verified_name": "HBA Wear",
                "quality_rating": "GREEN",
                "id": NUMBER_ID,
            },
        )

    info = _client(handler).check()
    assert (info.display_number, info.verified_name, info.quality_rating) == (
        "+20 100 555 0100", "HBA Wear", "GREEN",
    )
    assert seen[0].url.path == f"/v23.0/{NUMBER_ID}"


def test_the_approved_messages_are_read_from_the_business_account():
    def handler(request):
        assert request.url.path == "/v23.0/777888999/message_templates"
        return httpx.Response(
            200, json={"data": [{"name": "order_confirmation", "status": "APPROVED"}]}
        )

    assert _client(handler).templates("777888999") == [
        {"name": "order_confirmation", "status": "APPROVED"}
    ]


def test_a_business_account_that_is_not_a_number_is_refused_before_asking():
    with pytest.raises(MetaError, match="business account ID"):
        _client(_sent([])).templates("777/../me")


# ── Files ─────────────────────────────────────────────────────────────────────


def test_a_file_is_uploaded_to_the_numbers_own_address():
    def handler(request):
        assert request.url.path == f"/v23.0/{NUMBER_ID}/media"
        assert b"receipt.pdf" in request.content
        return httpx.Response(200, json={"id": "9002"})

    assert _client(handler).upload_media(b"%PDF", "application/pdf", "receipt.pdf") == "9002"


def test_a_files_address_is_taken_only_from_meta():
    def handler(request):
        return httpx.Response(200, json={"url": "https://elsewhere.example/steal", "id": "9001"})

    with pytest.raises(MetaError, match="no usable address"):
        _client(handler).media_info("9001")


def test_a_file_meta_has_deleted_is_gone_not_broken():
    """After 7 days Meta answers "no such object" for a customer's file."""
    with pytest.raises(MetaError) as refused:
        _client(_refusing(400, 100)).media_info("9001")
    assert refused.value.kind == "gone"


def test_a_file_is_downloaded_with_the_key_and_only_from_meta():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "graph.facebook.com":
            return httpx.Response(
                200,
                json={
                    "url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=9001",
                    "mime_type": "image/jpeg",
                    "sha256": "abc",
                    "file_size": 5,
                },
            )
        return httpx.Response(200, content=b"photo")

    client = _client(handler)
    info = client.media_info("9001")
    assert (info.mime_type, info.size_bytes) == ("image/jpeg", 5)
    assert client.download(info.url) == b"photo"
    assert seen[1].headers["authorization"] == f"Bearer {TOKEN}"

    with pytest.raises(MetaError, match="not one of WhatsApp's"):
        client.download("https://elsewhere.example/steal")
    assert len(seen) == 2


def test_a_file_larger_than_allowed_is_refused():
    client = _client(lambda request: httpx.Response(200, content=b"x" * 64))
    with pytest.raises(MetaError, match="larger than WhatsApp allows"):
        client.download("https://lookaside.fbsbx.com/a", max_bytes=10)


@pytest.mark.parametrize(
    ("url", "ours"),
    [
        ("https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1", True),
        ("https://scontent.whatsapp.net/v/t1/photo.jpg", True),
        ("https://graph.facebook.com/v23.0/1", True),
        ("http://lookaside.fbsbx.com/a", False),
        ("https://fbsbx.com.elsewhere.example/a", False),
        ("https://elsewhere.example/#.fbsbx.com", False),
        ("https://notfbsbx.com/a", False),
        ("https://user:pass@lookaside.fbsbx.com/a", False),
        ("https://169.254.169.254/latest/meta-data", False),
        ("file:///etc/passwd", False),
        ("not an address", False),
    ],
)
def test_which_addresses_count_as_metas(url, ours):
    assert is_meta_media_url(url) is ours


# ── Callbacks ─────────────────────────────────────────────────────────────────


def _signed(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_a_callback_signed_with_the_app_secret_is_accepted():
    body = b'{"entry": []}'
    assert verify_signature(body, _signed(body, "app-secret"), "app-secret") is True


@pytest.mark.parametrize(
    ("header", "secret"),
    [
        (None, "app-secret"),
        ("", "app-secret"),
        ("sha256=" + "0" * 64, "app-secret"),
        ("sha1=abc", "app-secret"),
        ("anything", ""),
    ],
)
def test_a_callback_that_is_not_signed_by_meta_is_refused(header, secret):
    assert verify_signature(b'{"entry": []}', header, secret) is False


def test_a_signature_for_other_bytes_is_refused():
    assert verify_signature(b'{"entry": [1]}', _signed(b'{"entry": []}', "s"), "s") is False


def test_no_app_secret_never_means_accept_everything():
    body = b"{}"
    assert verify_signature(body, _signed(body, ""), "") is False
