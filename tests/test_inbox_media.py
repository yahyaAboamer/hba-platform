"""A chat's files (ADR 0059, point 12; the plan's phase 3). Neither Meta nor
the bucket is called: a mock transport and an in-memory store stand in. Every
number and file here is made up.
"""

import json
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.businesstime import utcnow
from app.db import SessionLocal
from app.main import app
from app.shared.models.identity import UserAccount
from app.modules.inbox.models import InboxConversation, InboxMedia, InboxMessage
from app.modules.inbox.services import connection, media, sending, storage
from app.modules.inbox.services.meta import MetaClient, MetaError, NumberInfo
from app.modules.inbox.services.outbound import NotSent
from app.modules.inbox.services.storage import StorageError

TOKEN = "EAAG-made-up-access-key-0000a1b2"
NUMBER_ID = "100200300400500"
HER = "201005550188"
FILE_URL = "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=9001"


class Store:
    """An in-memory bucket."""

    def __init__(self, fail: StorageError | None = None) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.fail = fail

    def put(self, key, content, content_type):
        if self.fail:
            raise self.fail
        self.files[key] = (content, content_type)

    def get(self, key):
        if key not in self.files:
            raise StorageError("The file store does not have this file.", missing=True)
        return self.files[key][0]

    def close(self):
        pass


@pytest.fixture()
def connected(db, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    connection.save_whatsapp(
        db, phone_number_id=NUMBER_ID, business_account_id="777888999000111",
        access_token=TOKEN, app_secret="made-up-app-secret-000000009f3c",
        verify_token="made-up-check-word-0001", actor_id=None, actor_email=None,
        checker=lambda *args: NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN"),
    )


@pytest.fixture()
def may_send(db, connected, monkeypatch):
    connection.set_sending(db, True, actor_id=None, actor_email=None)
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)


def _meta(*, content=b"photo-bytes", mime="image/jpeg", info_status=200, info_code=None,
          size=None, network_down=False, asked: list | None = None) -> MetaClient:
    sent: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        if network_down:
            raise httpx.ConnectError("down")
        if asked is not None:
            asked.append(request)
        if request.url.host != "graph.facebook.com":
            return httpx.Response(200, content=content)
        if request.method == "POST" and request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "7700"})
        if request.method == "POST":
            sent.append(1)
            return httpx.Response(200, json={"messages": [{"id": f"wamid.SENT{len(sent)}-{id(sent)}"}]})
        if info_status != 200:
            return httpx.Response(info_status, json={"error": {"code": info_code}})
        return httpx.Response(200, json={
            "url": FILE_URL, "mime_type": mime, "sha256": "x",
            "file_size": size if size is not None else len(content),
        })

    return MetaClient(TOKEN, NUMBER_ID, api_version="v23.0", transport=httpx.MockTransport(handler))


def _chat(db, *, wrote_ago=timedelta(minutes=5)) -> InboxConversation:
    conversation = InboxConversation(phone=HER, name="Nour", last_inbound_at=utcnow() - wrote_ago)
    db.add(conversation)
    db.flush()
    return conversation


def _waiting(db, *, mime="image/jpeg", filename=None, state="pending", wa_media_id="9001",
             sent_ago=timedelta(0)) -> InboxMedia:
    conversation = _chat(db)
    message = InboxMessage(
        conversation_id=conversation.id, direction="in", kind="image", wa_message_id="wamid.M",
        status="received", origin="customer", occurred_at=utcnow() - sent_ago,
    )
    db.add(message)
    db.flush()
    file = InboxMedia(message_id=message.id, wa_media_id=wa_media_id, mime_type=mime,
                      filename=filename, state=state,
                      storage_key=f"inbox/{conversation.id}/{message.id}/kept" if state == "stored" else None)
    db.add(file)
    db.flush()
    return file


def _staff(db) -> UserAccount:
    user = UserAccount(email="mariam@example.com", password_hash="x", status="active", display_name="Mariam")
    db.add(user)
    db.flush()
    return user


# ── Copying a customer's file ─────────────────────────────────────────────────


def test_a_waiting_file_is_copied_into_the_bucket(db, connected):
    store = Store()
    file = _waiting(db, mime="image/jpeg; charset=binary")
    media.fetch(db, file.id, client=_meta(), store=store)

    message = db.get(InboxMessage, file.message_id)
    key = f"inbox/{message.conversation_id}/{message.id}/{file.id}.jpg"
    assert (file.state, file.storage_key) == ("stored", key)
    assert store.files[key] == (b"photo-bytes", "image/jpeg")
    assert (file.mime_type, file.size_bytes) == ("image/jpeg", 11)
    assert len(file.sha256) == 64
    # Numbers of ours only: no name and no phone in where it is kept.
    assert HER not in key and "Nour" not in key


def test_a_file_whatsapp_no_longer_has_is_gone_not_broken(db, connected):
    file = _waiting(db)
    media.fetch(db, file.id, client=_meta(info_status=400, info_code=100), store=Store())
    assert (file.state, file.storage_key) == ("gone", None)


def test_a_file_too_large_to_keep_is_not_fetched(db, connected):
    asked: list = []
    file = _waiting(db)
    media.fetch(db, file.id, client=_meta(size=media.INBOUND_MAX_BYTES + 1, asked=asked), store=Store())
    assert file.state == "failed"
    assert [request.url.host for request in asked] == ["graph.facebook.com"]


def test_when_whatsapp_does_not_answer_the_job_is_tried_again(db, connected):
    """Not marked failed: WhatsApp still has the file for 7 days."""
    file = _waiting(db)
    with pytest.raises(media.CopyFailed, match="WhatsApp did not answer"):
        media.fetch(db, file.id, client=_meta(network_down=True), store=Store())
    assert file.state == "pending"


def test_when_the_bucket_does_not_answer_the_job_is_tried_again(db, connected):
    file = _waiting(db)
    down = Store(fail=StorageError("The file store did not answer.", retryable=True))
    with pytest.raises(media.CopyFailed, match="did not answer"):
        media.fetch(db, file.id, client=_meta(), store=down)
    assert file.state == "pending"


@pytest.mark.parametrize(
    ("client_", "store_"),
    [
        # Meta refusing in a way it does not explain (photo 578, 22 October).
        (lambda: _meta(info_status=400, info_code=None), Store),
        (lambda: _meta(info_status=401, info_code=190), Store),
        (_meta, lambda: Store(fail=StorageError("refused (403)"))),
    ],
)
def test_one_refusal_is_not_final_the_last_try_is(db, connected, client_, store_):
    """A photo used to be marked failed on its first refusal, with no reason
    kept and no second try. Now each try says why, and only the last gives up."""
    file = _waiting(db)
    with pytest.raises(media.CopyFailed) as refused:
        media.fetch(db, file.id, client=client_(), store=store_())
    assert file.state == "pending"
    assert str(refused.value)

    media.fetch(db, file.id, client=client_(), store=store_(), last_try=True)
    assert file.state == "failed"


def test_the_jobs_last_try_is_the_one_that_gives_up(db, connected, monkeypatch):
    from app.shared.models.integration import BackgroundJob
    from app.shared.services.jobs import MAX_ATTEMPTS, JobKind, JobStatus

    file = _waiting(db)
    media.queue_fetch(db, file.id)
    job = db.query(BackgroundJob).filter_by(dedupe_key=f"{JobKind.INBOX_FETCH_MEDIA}:{file.id}").one()
    seen: list[bool] = []
    monkeypatch.setattr(media, "fetch", lambda db_, media_id, **kw: seen.append(kw["last_try"]))

    job.status = JobStatus.RUNNING
    db.flush()
    media._handle_fetch_media(db, {"media_id": file.id})
    job.attempts = MAX_ATTEMPTS - 1
    db.flush()
    media._handle_fetch_media(db, {"media_id": file.id})
    assert seen == [False, True]


# ── Asking for a file again ───────────────────────────────────────────────────


def test_a_photo_that_failed_is_copied_when_asked_again(db, connected):
    file = _waiting(db, state="failed", sent_ago=timedelta(days=2))
    found, problem = media.try_again(db, file.id, client=_meta(), store=Store())
    assert (found.state, problem) == ("stored", None)
    assert found.storage_key


def test_asked_again_and_refused_again_it_says_why(db, connected):
    file = _waiting(db, state="failed")
    found, problem = media.try_again(db, file.id, client=_meta(info_status=400), store=Store())
    assert found.state == "failed"
    assert problem.startswith("WhatsApp refused the request")


def test_asked_again_and_still_gone_it_says_so(db, connected):
    file = _waiting(db, state="gone", sent_ago=timedelta(days=1))
    found, problem = media.try_again(db, file.id, client=_meta(info_status=400, info_code=100), store=Store())
    assert (found.state, problem) == ("gone", "WhatsApp no longer has this file.")


@pytest.mark.parametrize(
    ("state", "sent_ago", "words"),
    [
        ("stored", timedelta(hours=1), "already kept"),
        ("pending", timedelta(hours=1), "already being fetched"),
        ("gone", timedelta(days=8), "7 days"),
        ("failed", timedelta(days=8), "7 days"),
    ],
)
def test_only_a_file_whatsapp_still_holds_can_be_asked_for_again(db, connected, state, sent_ago, words):
    asked: list = []
    file = _waiting(db, state=state, sent_ago=sent_ago)
    with pytest.raises(media.Unavailable, match=words):
        media.try_again(db, file.id, client=_meta(asked=asked), store=Store())
    assert asked == []
    assert file.state == state
    with pytest.raises(LookupError):
        media.try_again(db, 987654, client=_meta(asked=asked), store=Store())


def test_the_chat_says_which_files_can_be_asked_for_again(db):
    from app.modules.inbox.services.chats import describe_message

    conversation = _chat(db)
    cases = [
        ("failed", timedelta(days=1), "9001", True),
        ("gone", timedelta(days=1), "9002", True),
        ("gone", timedelta(days=30), "9003", False),
        ("failed", timedelta(hours=1), None, False),  # one of ours: WhatsApp has no copy to give
        ("stored", timedelta(hours=1), "9004", False),
    ]
    for number, (state, sent_ago, wa_media_id, expected) in enumerate(cases):
        message = InboxMessage(
            conversation_id=conversation.id, direction="in", kind="image", wa_message_id=f"wamid.C{number}",
            status="received", origin="customer", occurred_at=utcnow() - sent_ago,
        )
        db.add(message)
        db.flush()
        file = InboxMedia(message_id=message.id, wa_media_id=wa_media_id, mime_type="image/jpeg", state=state,
                          storage_key="inbox/kept" if state == "stored" else None)
        db.add(file)
        db.flush()
        assert describe_message(message, None, file)["media"]["can_try_again"] is expected


def test_a_server_with_no_bucket_leaves_the_file_waiting(db, connected, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_media_bucket", "")
    asked: list = []
    file = _waiting(db)
    media.fetch(db, file.id, client=_meta(asked=asked))
    assert file.state == "pending"
    assert asked == []


def test_a_file_already_dealt_with_is_not_fetched_again(db, connected):
    asked: list = []
    file = _waiting(db, state="gone")
    media.fetch(db, file.id, client=_meta(asked=asked), store=Store())
    assert asked == []
    assert media.fetch(db, 987654, client=_meta(asked=asked), store=Store()) is None


def test_a_customers_file_arriving_queues_its_copy(db, connected):
    from app.modules.inbox.services.events import apply_event

    apply_event(db, {"entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": NUMBER_ID},
        "messages": [{"from": HER, "id": "wamid.P", "timestamp": "1760180000",
                      "type": "image", "image": {"id": "9001", "mime_type": "image/jpeg"}}],
    }}]}]})
    file = db.query(InboxMedia).one()
    db.flush()
    jobs = db.execute(text("SELECT kind, dedupe_key FROM background_job")).all()
    assert jobs == [("inbox_fetch_media", f"inbox_fetch_media:{file.id}")]


# ── Handing it to the page ────────────────────────────────────────────────────


def _stored(db, store, *, mime, filename=None, content=b"bytes") -> InboxMedia:
    file = _waiting(db, mime=mime, filename=filename)
    # Together: a stored file must say where it is.
    file.storage_key = f"inbox/1/{file.message_id}/{file.id}.bin"
    file.state = "stored"
    store.files[file.storage_key] = (content, mime)
    db.flush()
    return file


@pytest.mark.parametrize("mime", ["image/jpeg", "audio/ogg", "video/mp4", "application/pdf"])
def test_a_photo_audio_a_video_or_a_pdf_is_shown_in_place(db, mime):
    store = Store()
    found = media.read(db, _stored(db, store, mime=mime).id, store=store)
    assert (found["mime_type"], found["inline"], found["content"]) == (mime, True, b"bytes")


@pytest.mark.parametrize("mime", ["text/html", "image/svg+xml", "application/javascript", "application/x-msdownload", ""])
def test_anything_else_is_a_download_and_never_what_it_claims_to_be(db, mime):
    """A page a customer sends must not run as a page of ours."""
    store = Store()
    found = media.read(db, _stored(db, store, mime=mime, content=b"<script>").id, store=store)
    assert (found["mime_type"], found["inline"]) == ("application/octet-stream", False)


def test_the_name_she_gave_it_is_cut_down_to_what_is_safe_in_a_header(db):
    store = Store()
    file = _stored(db, store, mime="application/pdf", filename='re"ceipt\r\nX-Injected: 1.pdf')
    name = media.read(db, file.id, store=store)["filename"]
    assert '"' not in name and "\r" not in name and "\n" not in name and ":" not in name
    assert name


@pytest.mark.parametrize(("state", "words"), [("pending", "not ready yet"), ("gone", "no longer available"), ("failed", "not ready yet")])
def test_a_file_that_is_not_stored_says_why(db, state, words):
    file = _waiting(db, state=state)
    with pytest.raises(media.Unavailable, match=words):
        media.read(db, file.id, store=Store())
    with pytest.raises(media.Unavailable):
        media.read(db, 987654, store=Store())


# ── A file staff send ─────────────────────────────────────────────────────────


def test_a_photo_goes_out_under_her_name_and_our_copy_is_kept(db, may_send):
    asked: list = []
    store = Store()
    conversation = _chat(db)
    mariam = _staff(db)
    message, kept = media.send_file(
        db, conversation.id, content=b"jpeg-bytes", mime_type="image/jpeg", filename="beige set.jpg",
        caption="This one?", voice=False, actor_id=mariam.id, client=_meta(asked=asked), store=store,
    )
    upload, send = asked
    assert upload.url.path.endswith(f"/{NUMBER_ID}/media")
    assert json.loads(send.content)["image"] == {"id": "7700", "caption": "This one?"}
    assert (message.kind, message.origin, message.sent_by, message.status) == ("image", "staff", mariam.id, "sent")
    assert (kept.state, kept.filename, kept.size_bytes) == ("stored", "beige set.jpg", 10)
    assert store.files[kept.storage_key] == (b"jpeg-bytes", "image/jpeg")


def test_only_opus_in_ogg_goes_as_a_voice_note(db, may_send):
    asked: list = []
    conversation = _chat(db)
    mariam = _staff(db)
    message, _ = media.send_file(
        db, conversation.id, content=b"ogg", mime_type="audio/ogg; codecs=opus", filename="voice.ogg",
        caption=None, voice=True, actor_id=mariam.id, client=_meta(asked=asked), store=Store(),
    )
    assert json.loads(asked[1].content)["audio"] == {"id": "7700", "voice": True}
    assert message.extra == {"voice": True}

    asked.clear()
    media.send_file(
        db, conversation.id, content=b"mp3", mime_type="audio/mpeg", filename="song.mp3",
        caption=None, voice=True, actor_id=mariam.id, client=_meta(asked=asked), store=Store(),
    )
    assert json.loads(asked[1].content)["audio"] == {"id": "7700"}


@pytest.mark.parametrize(
    ("mime", "size", "words"),
    [
        ("audio/webm", 1, "does not take this kind of file"),
        ("text/html", 1, "does not take this kind of file"),
        ("image/jpeg", 0, "empty"),
        ("image/jpeg", 5 * 1024 * 1024 + 1, "larger than WhatsApp allows"),
    ],
)
def test_a_file_whatsapp_will_not_take_is_refused_before_asking(db, may_send, mime, size, words):
    asked: list = []
    content = b"x" * size
    conversation = _chat(db)
    with pytest.raises(media.NotSendable, match=words):
        media.send_file(
            db, conversation.id, content=content, mime_type=mime, filename="f", caption=None,
            voice=False, actor_id=_staff(db).id, client=_meta(asked=asked), store=Store(),
        )
    assert asked == []


def test_a_file_is_held_to_the_same_rule_on_who_may_be_messaged(db, connected):
    """Connected, but sending is off: nothing is uploaded, sent or kept."""
    asked: list = []
    store = Store()
    conversation = _chat(db)
    with pytest.raises(NotSent, match=sending.SENDING_OFF[:12]):
        media.send_file(
            db, conversation.id, content=b"x", mime_type="image/jpeg", filename="f.jpg",
            caption=None, voice=False, actor_id=_staff(db).id, client=_meta(asked=asked), store=store,
        )
    assert asked == [] and store.files == {}
    assert db.query(InboxMedia).count() == 0


def test_a_file_is_refused_outside_her_24_hours(db, may_send):
    conversation = _chat(db, wrote_ago=timedelta(hours=30))
    with pytest.raises(NotSent) as refused:
        media.send_file(
            db, conversation.id, content=b"x", mime_type="image/jpeg", filename="f.jpg",
            caption=None, voice=False, actor_id=_staff(db).id, client=_meta(), store=Store(),
        )
    assert refused.value.kind == "window_closed"


def test_if_our_copy_cannot_be_kept_the_message_has_still_gone(db, may_send):
    conversation = _chat(db)
    message, kept = media.send_file(
        db, conversation.id, content=b"x", mime_type="image/jpeg", filename="f.jpg", caption=None,
        voice=False, actor_id=_staff(db).id, client=_meta(),
        store=Store(fail=StorageError("refused (403)")),
    )
    assert (message.status, kept.state, kept.storage_key) == ("sent", "failed", None)


# ── The routes ────────────────────────────────────────────────────────────────

BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}


@pytest.fixture()
def client(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.worker_enabled", False)
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _committed_file(mime: str, state: str = "stored") -> tuple[int, int, str]:
    with SessionLocal() as db:
        file = _waiting(db, mime=mime, filename="note.html", state="pending")
        key = f"inbox/1/{file.message_id}/{file.id}.bin"
        if state == "stored":
            file.state, file.storage_key = "stored", key
        conversation_id = db.get(InboxMessage, file.message_id).conversation_id
        db.commit()
        return file.id, conversation_id, key


def test_a_file_is_served_so_that_the_browser_cannot_be_made_to_run_it(client, monkeypatch):
    store = Store()
    file_id, _, key = _committed_file("text/html")
    store.files[key] = (b"<script>alert(1)</script>", "text/html")
    monkeypatch.setattr(storage, "bucket", lambda: store)

    response = client.get(f"/api/inbox/media/{file_id}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_a_file_that_is_not_ready_is_a_404_in_words(client):
    file_id, _, _ = _committed_file("image/jpeg", state="pending")
    response = client.get(f"/api/inbox/media/{file_id}")
    assert response.status_code == 404
    assert "not ready yet" in response.json()["detail"]


def test_asking_for_a_file_again_answers_in_words(client):
    file_id, _, _ = _committed_file("image/jpeg", state="stored")
    kept = client.post(f"/api/inbox/media/{file_id}/try-again")
    assert kept.status_code == 422
    assert "already kept" in kept.json()["detail"]
    assert client.post("/api/inbox/media/987654/try-again").status_code == 404


def test_a_file_is_only_for_someone_who_holds_the_inbox(client, fresh_database):
    file_id, conversation_id, _ = _committed_file("image/jpeg")
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/inbox/media/{file_id}").status_code == 401
    from app.db import engine

    with engine.begin() as connection_:
        connection_.execute(text("UPDATE role_assignment SET role = 'affiliate_manager'"))
    assert client.get(f"/api/inbox/media/{file_id}").status_code == 403
    upload = {"upload": ("f.jpg", b"x", "image/jpeg")}
    assert client.post(f"/api/inbox/conversations/{conversation_id}/media", files=upload).status_code == 403


def test_uploading_says_why_when_it_cannot_be_sent(client):
    _, conversation_id, _ = _committed_file("image/jpeg")
    url = f"/api/inbox/conversations/{conversation_id}/media"
    wrong_kind = client.post(url, files={"upload": ("v.webm", b"x", "audio/webm")})
    assert wrong_kind.status_code == 422
    not_connected = client.post(url, files={"upload": ("f.jpg", b"x", "image/jpeg")})
    assert not_connected.status_code == 409
    assert not_connected.json()["detail"] == "WhatsApp is not connected."
    assert client.post("/api/inbox/conversations/987654/media", files={"upload": ("f.jpg", b"x", "image/jpeg")}).status_code == 404


def test_the_approved_messages_need_whatsapp_connected(client):
    response = client.get("/api/inbox/templates")
    assert response.status_code == 409
    assert response.json()["detail"] == "WhatsApp is not connected."
