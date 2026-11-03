"""Settings → Integrations (Phase 2, batch 2.3): whether each outside
connection works, for the owner alone.

Each row working, failed and not connected (and email and storage "never");
the fixed order and words of the frame; one source that cannot be read
leaving its own row "unknown" and the others in place; everybody but the
owner refused. Every key, address and time here is made up.
"""

from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import settings
from app.core.businesstime import at_words, utcnow
from app.core.passwords import hash_password
from app.db import engine
from app.main import app
from app.modules.inbox import public as inbox_public
from app.modules.inbox.models import InboxConnection, InboxConversation, InboxMedia, InboxMessage
from app.modules.inbox.services import media
from app.modules.operations.services import freshness
from app.shared.models.notifications import NotificationOutbox
from app.shared.services.integrations import connections

NOW = utcnow()
PASSWORD = "quiet-harbour-lantern"

ORDER = ["bosta", "shopify", "whatsapp", "estebdal", "email", "storage"]


@pytest.fixture(autouse=True)
def _nothing_configured(monkeypatch):
    """No mail service and no bucket unless a test sets one, whatever the
    machine running the suite has."""
    for name in (
        "mail_from_address", "resend_api_key", "brevo_api_key", "smtp_host",
        "inbox_media_bucket", "inbox_media_endpoint",
        "inbox_media_access_key_id", "inbox_media_secret_access_key",
    ):
        monkeypatch.setattr(settings, name, "", raising=False)


def _mail_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "mail_from_address", "hello@example.com", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "re_made_up_key", raising=False)


def _bucket_on(monkeypatch) -> None:
    monkeypatch.setattr(settings, "inbox_media_bucket", "hba-files", raising=False)
    monkeypatch.setattr(settings, "inbox_media_endpoint", "https://storage.example.com", raising=False)
    monkeypatch.setattr(settings, "inbox_media_access_key_id", "made-up-id", raising=False)
    monkeypatch.setattr(settings, "inbox_media_secret_access_key", "made-up-secret", raising=False)


def _row(body: dict, key: str) -> dict:
    return next(row for row in body["connections"] if row["key"] == key)


def _whatsapp(db, *, readable: bool, monkeypatch) -> None:
    if readable:
        key = Fernet.generate_key()
        monkeypatch.setattr(settings, "settings_encryption_key", key.decode(), raising=False)
        secret = Fernet(key).encrypt(b"made-up-secret-value").decode()
    else:
        monkeypatch.setattr(settings, "settings_encryption_key", "", raising=False)
        secret = "not-readable-here"
    db.add(
        InboxConnection(
            id=1, phone_number_id="100200300400500", business_account_id="777888999000111",
            access_token_encrypted=secret, app_secret_encrypted=secret,
            verify_token_encrypted=secret, access_token_hint="a1b2", app_secret_hint="9f3c",
            verified_at=NOW,
        )
    )
    db.flush()


def _message(db, at, *, direction="in") -> InboxMessage:
    conversation = db.query(InboxConversation).first()
    if conversation is None:
        conversation = InboxConversation(phone="201000000001", name="Nour")
        db.add(conversation)
        db.flush()
    message = InboxMessage(
        conversation_id=conversation.id, direction=direction, kind="image", body=None,
        status="received" if direction == "in" else "sent",
        origin="customer" if direction == "in" else "automatic", occurred_at=at,
    )
    db.add(message)
    db.flush()
    return message


def _file(db, at, state: str, *, refused_at=None) -> None:
    """A file, and - for one the bucket refused - the note `media` writes."""
    message = _message(db, at)
    if refused_at is not None:
        message.extra = {media.BUCKET_REFUSED: refused_at.isoformat()}
    db.add(
        InboxMedia(
            message_id=message.id, state=state, created_at=at,
            storage_key=f"inbox/1/{message.id}/1.jpg" if state == "stored" else None,
        )
    )
    db.flush()


def _email(db, state: str, *, created_at, sent_at=None, error=None) -> None:
    db.add(
        NotificationOutbox(
            event="invitation_sent", recipient_email="sara@example.com", payload={},
            state=state, created_at=created_at, sent_at=sent_at, last_error=error,
        )
    )
    db.flush()


# ── The shape, order and words ────────────────────────────────────────────────


def test_every_connection_in_the_frames_order_and_words(db):
    body = connections(db, NOW)

    assert body["checked_at"] == NOW.isoformat()
    assert [row["key"] for row in body["connections"]] == ORDER
    assert [
        (row["name"], row["what"], row["used_by"], row["when_label"], row["key_form"])
        for row in body["connections"]
    ] == [
        ("Bosta", "Deliveries", "Used by Operations and order pages", "Last read", "bosta"),
        ("Shopify", "Orders, products and tags", "Used by Operations, Affiliates and Inbox",
         "Read at", "shopify"),
        ("WhatsApp", "Customer chats and confirmations", "Used by Inbox", "Last message",
         "whatsapp"),
        ("E-stebdal", "Returns and exchanges", "Used by Operations", "Read at", "estebdal"),
        ("Email", "Invitations, password resets, model emails", "Used by everyone",
         "Last sent", None),
        # Only the Inbox's files go to the bucket (a stated divergence from
        # frame 6, which also names receipts and Affiliates).
        ("File storage", "Chat photos and voice notes", "Used by Inbox", "Last file stored", None),
    ]
    for row in body["connections"]:
        assert set(row) == {
            "key", "name", "what", "used_by", "state", "why", "when_label", "when", "key_form",
        }


def test_a_failed_row_stays_in_its_place(db):
    freshness.record_failure(db, "estebdal", "E-stebdal refused the key.", at=NOW)
    freshness.record_success(db, "bosta", 3, at=NOW)

    body = connections(db, NOW)

    assert [row["key"] for row in body["connections"]] == ORDER
    assert _row(body, "estebdal")["state"] == "failed"


# ── Bosta, Shopify and E-stebdal: Operations' freshness ───────────────────────


@pytest.mark.parametrize("source", ["bosta", "shopify", "estebdal"])
def test_a_clean_read_is_working_as_of_it(db, source):
    read = NOW - timedelta(minutes=3)
    freshness.record_success(db, source, 12, at=read)

    row = _row(connections(db, NOW), source)

    assert row["state"] == "working"
    assert row["why"] is None
    assert row["when"] == read.isoformat()


def test_a_failed_read_says_the_recorded_reason_as_of_the_last_clean_one(db):
    clean = NOW - timedelta(hours=2)
    freshness.record_success(db, "bosta", 12, at=clean)
    freshness.record_failure(db, "bosta", "Bosta refused the key.", at=NOW - timedelta(minutes=1))

    row = _row(connections(db, NOW), "bosta")

    assert row["state"] == "failed"
    assert row["why"] == "Bosta refused the key."
    assert row["when"] == clean.isoformat()


def test_an_old_clean_read_is_late(db):
    old = NOW - timedelta(minutes=45)
    freshness.record_success(db, "shopify", 12, at=old)

    row = _row(connections(db, NOW), "shopify")

    assert row["state"] == "late"
    assert row["why"] == "Not read cleanly for over 10 minutes. The reads may have stopped."
    assert row["when"] == old.isoformat()


@pytest.mark.parametrize("source", ["bosta", "shopify", "estebdal"])
def test_no_key_is_not_connected(db, source):
    freshness.record_not_connected(db, source, at=NOW)

    row = _row(connections(db, NOW), source)

    assert row["state"] == "not_connected"
    assert row["why"] == "No key is saved."
    assert row["when"] is None


def test_a_source_never_read_says_so(db):
    row = _row(connections(db, NOW), "estebdal")

    assert (row["state"], row["why"], row["when"]) == ("never", None, None)


# ── WhatsApp: the Inbox's connection ──────────────────────────────────────────


def test_whatsapp_with_no_connection_is_not_connected(db):
    row = _row(connections(db, NOW), "whatsapp")

    assert (row["state"], row["why"], row["when"]) == ("not_connected", "No key is saved.", None)


def test_whatsapp_working_as_of_the_latest_message_in_or_out(db, monkeypatch):
    _whatsapp(db, readable=True, monkeypatch=monkeypatch)
    _message(db, NOW - timedelta(hours=3), direction="in")
    latest = NOW - timedelta(minutes=20)
    _message(db, latest, direction="out")

    row = _row(connections(db, NOW), "whatsapp")

    assert (row["state"], row["why"], row["when"]) == ("working", None, latest.isoformat())


def test_whatsapp_keys_this_server_cannot_read_have_failed_in_the_inboxs_words(db, monkeypatch):
    _whatsapp(db, readable=False, monkeypatch=monkeypatch)

    row = _row(connections(db, NOW), "whatsapp")

    assert row["state"] == "failed"
    assert row["why"].startswith("It is saved, but this server cannot read it")
    assert "Traceback" not in row["why"]


# ── Email: the outbox ─────────────────────────────────────────────────────────


def test_email_with_no_mail_service_is_not_connected(db):
    _email(db, "skipped", created_at=NOW)

    row = _row(connections(db, NOW), "email")

    assert row["state"] == "not_connected"
    assert row["why"] == "No mail service is set on the server, so no email is sent."
    assert row["when"] is None


def test_email_never_sent_is_never(db, monkeypatch):
    _mail_on(monkeypatch)
    # Skipped is not an attempt.
    _email(db, "skipped", created_at=NOW)

    row = _row(connections(db, NOW), "email")

    assert (row["state"], row["why"], row["when"]) == ("never", None, None)


def test_email_working_as_of_the_last_sent(db, monkeypatch):
    _mail_on(monkeypatch)
    earlier = NOW - timedelta(days=1)
    # The service's own failure, before the last email went out fine.
    _email(db, "failed", created_at=earlier, error="RuntimeError: Could not reach resend: timed out")
    sent = NOW - timedelta(minutes=5)
    _email(db, "sent", created_at=sent - timedelta(seconds=30), sent_at=sent)

    row = _row(connections(db, NOW), "email")

    assert (row["state"], row["why"], row["when"]) == ("working", None, sent.isoformat())


#: How the outbox records an email refused for its own reasons
#: (`notifications.send_notification`, `mail.send`).
ITS_OWN = [
    "There is no email address to send to",
    "Not sent: the sign-in code had already expired.",
    'resend refused the message (422): {"message":"Invalid `to` field."}',
    "{'nour@example': (550, b'5.1.1 No such user')}",
    "SMTPDataError: (554, b'Message rejected')",
]


@pytest.mark.parametrize("error", ITS_OWN)
def test_an_email_refused_for_its_own_reasons_leaves_email_working(db, monkeypatch, error):
    _mail_on(monkeypatch)
    sent = NOW - timedelta(hours=2)
    _email(db, "sent", created_at=sent, sent_at=sent)
    _email(db, "failed", created_at=NOW - timedelta(minutes=1), error=error)

    row = _row(connections(db, NOW), "email")

    assert (row["state"], row["why"], row["when"]) == ("working", None, sent.isoformat())


def test_only_emails_refused_for_their_own_reasons_is_never_not_failed(db, monkeypatch):
    _mail_on(monkeypatch)
    _email(db, "failed", created_at=NOW, error="There is no email address to send to")

    row = _row(connections(db, NOW), "email")

    assert (row["state"], row["why"], row["when"]) == ("never", None, None)


# ── Email, through the real mail code ─────────────────────────────────────────
#
# Each failure is produced by `notifications.send_notification` and `mail`
# themselves, with only the provider (httpx) or the server (smtplib) faked,
# so the words the rule reads are the words that code writes. A change of
# wording there fails here.


class _Smtp:
    """smtplib.SMTP, failing at the step it is told to."""

    fail_at: str | None = None
    error: Exception | None = None

    def __init__(self, *args, **kwargs):
        if self.fail_at == "connect":
            raise self.error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _step(self, name):
        if self.fail_at == name:
            raise self.error

    def starttls(self):
        self._step("starttls")

    def login(self, *args):
        self._step("login")

    def send_message(self, *args):
        self._step("send")


def _smtp(monkeypatch, fail_at: str, error: Exception) -> None:
    import smtplib

    monkeypatch.setattr(settings, "mail_from_address", "hello@example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_username", "hello@example.com", raising=False)
    monkeypatch.setattr(settings, "smtp_use_tls", True, raising=False)
    monkeypatch.setattr(smtplib, "SMTP", type("Smtp", (_Smtp,), {"fail_at": fail_at, "error": error}))


def _resend(monkeypatch, answer) -> None:
    """Resend answering with `answer` (a status and body), or raising it."""
    import httpx

    _mail_on(monkeypatch)

    def post(*args, **kwargs):
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, text=body)

    monkeypatch.setattr(httpx, "post", post)


def _deliver(db, *, event=None, payload=None, written_ago=None) -> NotificationOutbox:
    """Queue one email and let the real sender try it - as its last try, so a
    failure it would retry gives up and is recorded as failed."""
    from app.shared.services.notifications import MAX_ATTEMPTS, Event, queue, send_notification

    row = queue(
        db,
        event=event or Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload=payload or {"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()
    row.attempts = MAX_ATTEMPTS - 1
    if written_ago is not None:
        row.created_at = utcnow() - written_ago
    db.flush()
    send_notification(db, {"outbox_id": row.id})
    db.flush()
    assert row.state == "failed", (row.state, row.last_error)
    return row


def _smtp_case(fail_at, error):
    return lambda monkeypatch: _smtp(monkeypatch, fail_at, error)


def _resend_case(answer):
    return lambda monkeypatch: _resend(monkeypatch, answer)


def _service_cases():
    import smtplib

    import httpx

    return [
        ("sign-in refused", _smtp_case("login", smtplib.SMTPAuthenticationError(535, b"5.7.8 Bad credentials")),
         "The mail service refused the account's sign-in {at}."),
        ("no STARTTLS", _smtp_case("starttls", smtplib.SMTPNotSupportedError(
            "STARTTLS extension not supported by server.")),
         "The mail server would not open a secure connection {at}."),
        ("server unreachable", _smtp_case("connect", ConnectionRefusedError(111, "Connection refused")),
         "The mail service could not be reached {at}, even after every retry."),
        ("server hung up", _smtp_case("send", smtplib.SMTPServerDisconnected("Connection unexpectedly closed")),
         "The mail service could not be reached {at}, even after every retry."),
        ("key refused", _resend_case((401, '{"message":"API key is invalid"}')),
         "The mail service refused the key {at}."),
        ("key not allowed", _resend_case((403, '{"message":"You do not have access"}')),
         "The mail service refused the key {at}."),
        ("domain not verified (403)", _resend_case(
            (403, '{"message":"The example.com domain is not verified. Please, add and verify your domain"}')),
         "The mail service refused the sender address {at}: its domain is not verified."),
        ("sender domain not verified (422)", _resend_case(
            (422, '{"message":"The sender domain is not verified"}')),
         "The mail service refused the sender address {at}: its domain is not verified."),
        ("rate limited", _resend_case((429, '{"message":"Too many requests"}')),
         "The mail service turned emails away as too many {at}."),
        ("provider down", _resend_case((503, "unavailable")),
         "The mail service could not be reached {at}, even after every retry."),
        ("provider unreachable", _resend_case(httpx.ConnectError("Network is unreachable")),
         "The mail service could not be reached {at}, even after every retry."),
    ]


@pytest.mark.parametrize("case", range(11))
def test_the_mail_service_failing_turns_email_failed(db, monkeypatch, case):
    name, make, why = _service_cases()[case]
    make(monkeypatch)

    failed = _deliver(db)
    now = utcnow()
    row = _row(connections(db, now), "email")

    assert row["state"] == "failed", (name, failed.last_error)
    assert row["why"] == why.format(at=at_words(failed.created_at, now)), name
    # Nothing was ever sent: no time it last worked.
    assert row["when"] is None


def test_a_failed_emails_when_is_still_the_last_sent(db, monkeypatch):
    sent = utcnow() - timedelta(days=2)
    _email(db, "sent", created_at=sent, sent_at=sent)
    _resend(monkeypatch, (401, '{"message":"API key is invalid"}'))
    _deliver(db)
    # An email of its own refused after it does not hide it.
    _email(db, "failed", created_at=utcnow(), error="There is no email address to send to")

    row = _row(connections(db, utcnow()), "email")

    assert row["state"] == "failed"
    assert row["when"] == sent.isoformat()


def _own_cases():
    import smtplib

    from app.shared.services.notifications import Event

    return [
        ("no address", lambda mp: _resend(mp, (200, "{}")), {"payload": {"email": "", "name": "Nour"}}),
        ("code expired", lambda mp: _resend(mp, (200, "{}")),
         {"event": Event.SIGN_IN_CODE, "payload": {"email": "nour@example.com", "code": "123456"},
          "written_ago": timedelta(hours=1)}),
        ("address refused by the provider",
         lambda mp: _resend(mp, (422, '{"message":"Invalid `to` field."}')), {}),
        ("recipient refused by the server", lambda mp: _smtp(
            mp, "send", smtplib.SMTPRecipientsRefused({"nour@example.com": (550, b"5.1.1 No such user")})), {}),
    ]


@pytest.mark.parametrize("case", range(4))
def test_an_email_refused_for_its_own_reasons_does_not_turn_email_failed(db, monkeypatch, case):
    name, make, how = _own_cases()[case]
    make(monkeypatch)

    failed = _deliver(db, **how)

    row = _row(connections(db, utcnow()), "email")
    assert row["state"] == "never", (name, failed.last_error)


# ── File storage: the Inbox's copies ──────────────────────────────────────────


def test_storage_with_no_bucket_is_not_connected(db):
    _file(db, NOW, "stored")

    row = _row(connections(db, NOW), "storage")

    assert row["state"] == "not_connected"
    assert row["why"] == "No file storage is set on the server, so customers' files are not kept."
    assert row["when"] is None


def test_storage_with_nothing_kept_yet_is_never(db, monkeypatch):
    _bucket_on(monkeypatch)
    # Still waiting is not a finished copy.
    _file(db, NOW, "pending")

    row = _row(connections(db, NOW), "storage")

    assert (row["state"], row["why"], row["when"]) == ("never", None, None)


def test_storage_working_as_of_the_last_file_kept(db, monkeypatch):
    _bucket_on(monkeypatch)
    _file(db, NOW - timedelta(days=2), "failed", refused_at=NOW - timedelta(days=2))
    kept = NOW - timedelta(hours=1)
    _file(db, kept, "stored")

    row = _row(connections(db, NOW), "storage")

    assert (row["state"], row["why"], row["when"]) == ("working", None, kept.isoformat())


def test_storage_whose_latest_copy_the_bucket_refused_has_failed(db, monkeypatch):
    """`when` stays the last file kept, as Bosta's stays its last good read;
    the refusal's time is in the words."""
    _bucket_on(monkeypatch)
    kept = NOW - timedelta(hours=3)
    _file(db, kept, "stored")
    refused = NOW - timedelta(minutes=8)
    _file(db, refused, "failed", refused_at=refused)

    row = _row(connections(db, NOW), "storage")

    assert row["state"] == "failed"
    assert row["why"] == f"File storage refused the latest file {at_words(refused, NOW)}."
    assert row["when"] == kept.isoformat()


def test_storage_refused_with_nothing_ever_kept_has_no_when(db, monkeypatch):
    _bucket_on(monkeypatch)
    _file(db, NOW, "failed", refused_at=NOW)

    row = _row(connections(db, NOW), "storage")

    assert (row["state"], row["when"]) == ("failed", None)


def test_a_file_failed_for_its_own_reasons_is_not_storage_failing(db, monkeypatch):
    """Too large to keep, or WhatsApp would not hand it over: `failed`, with
    no note from the bucket - storage was never asked."""
    _bucket_on(monkeypatch)
    kept = NOW - timedelta(hours=3)
    _file(db, kept, "stored")
    _file(db, NOW - timedelta(minutes=8), "failed")

    row = _row(connections(db, NOW), "storage")

    assert (row["state"], row["why"], row["when"]) == ("working", None, kept.isoformat())


def test_no_size_is_offered(db, monkeypatch):
    """Choice 9: not readable without a call to the bucket."""
    _bucket_on(monkeypatch)
    _file(db, NOW, "stored")

    row = _row(connections(db, NOW), "storage")

    assert not any("size" in key or "bytes" in key or "gb" in key.lower() for key in row)


# ── One source failing leaves the others ──────────────────────────────────────


def test_one_source_that_cannot_be_read_is_unknown_and_the_others_stay(db, monkeypatch):
    freshness.record_success(db, "bosta", 3, at=NOW)
    freshness.record_success(db, "estebdal", 3, at=NOW)

    def broken(session):
        session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(inbox_public, "whatsapp_connection", broken)

    body = connections(db, NOW)

    whatsapp = _row(body, "whatsapp")
    assert (whatsapp["state"], whatsapp["why"], whatsapp["when"]) == ("unknown", None, None)
    assert whatsapp["name"] == "WhatsApp"
    # The rows on either side were read, the ones after it from a session
    # the failed query did not spoil.
    assert _row(body, "bosta")["state"] == "working"
    assert _row(body, "estebdal")["state"] == "working"
    assert _row(body, "email")["state"] == "not_connected"
    assert [row["key"] for row in body["connections"]] == ORDER


# ── Who may ask ───────────────────────────────────────────────────────────────


@pytest.fixture()
def owner(fresh_database):
    with TestClient(app) as client:
        response = client.post(
            "/api/auth/bootstrap",
            json={"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD},
        )
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _signed_in_as(role: str) -> TestClient:
    email = f"{role}@example.com"
    with engine.begin() as connection:
        account = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', :e) RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD)},
        ).scalar_one()
        connection.execute(
            text("INSERT INTO role_assignment (user_account_id, role) VALUES (:u, :r)"),
            {"u": account, "r": role},
        )
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def test_the_owner_reads_every_connection(owner):
    response = owner.get("/api/integrations")

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["key"] for row in body["connections"]] == ORDER
    assert body["checked_at"]


@pytest.mark.parametrize(
    "role",
    ["affiliate_manager", "content_manager", "operations_manager", "customer_service", "affiliate"],
)
def test_everybody_but_the_owner_is_refused(owner, role):
    other = _signed_in_as(role)

    response = other.get("/api/integrations")

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission required: settings.manage"


def test_signed_out_is_refused(fresh_database):
    with TestClient(app) as client:
        assert client.get("/api/integrations").status_code == 401
