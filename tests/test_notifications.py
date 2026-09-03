"""What the platform tells people, and when it refuses to.

§16. The tests that matter here are not about wording — they are about the two
guarantees underneath it:

**An email is queued in the same transaction as the change it announces.** A
month agreed with no email queued is a model who was paid and never told; an
email queued for a month that rolled back is a model told about money they are
not owed. Both are proven by rolling the transaction back and looking.

**Nothing sensitive leaves the building.** Mail is the one channel that keeps a
copy on a server nobody here controls, so account numbers, InstaPay addresses
and passwords are asserted absent rather than assumed absent.
"""

import smtplib

import pytest
from sqlalchemy import select

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind, AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.models.notifications import NotificationOutbox, NotificationState
from app.services import mail
from app.services.notifications import (
    Event,
    application_approved,
    month_in_words,
    queue,
    render,
    send_notification,
)

ADDRESS = "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp"


@pytest.fixture()
def affiliate(db):
    account = UserAccount(
        email="nour@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        display_name="Nour",
        status="active",
    )
    db.add(account)
    db.flush()
    profile = AffiliateProfile(
        user_account_id=account.id,
        name="Nour Mahmoud",
        status=AffiliateStatus.PENDING,
        account_kind=AccountKind.MODEL,
    )
    db.add(profile)
    db.flush()
    return profile


def _outbox(db) -> list[NotificationOutbox]:
    return list(db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.id)))


# -- The guarantee ------------------------------------------------------------


def test_queueing_does_not_commit(db, affiliate):
    """§16's whole design. `queue` writes into the caller's transaction and
    leaves committing to them, so the email and the thing it announces cannot
    part company.
    """
    queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.rollback()

    assert _outbox(db) == []


def test_the_sending_job_is_queued_in_the_same_transaction(db, affiliate):
    """A row saying an email is owed, and no work to deliver it, is a queue
    that never drains.
    """
    from app.models.integration import BackgroundJob

    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )

    # The session is autoflush=False, so the pending insert has to be pushed
    # before a query can see it. That is the production behaviour too: both
    # rows land at commit, together.
    db.flush()
    jobs = list(
        db.scalars(
            select(BackgroundJob).where(BackgroundJob.kind == "notification.send")
        )
    )
    assert [job.payload["outbox_id"] for job in jobs] == [row.id]


def test_an_affiliate_with_no_address_is_not_an_error(db, affiliate):
    """They were entered by hand from a WhatsApp conversation. That must not stop
    a month being approved.
    """
    assert queue(db, event=Event.MONTH_APPROVED, recipient_email=None) is None
    assert queue(db, event=Event.MONTH_APPROVED, recipient_email="  ") is None
    assert _outbox(db) == []


def test_approving_an_application_queues_the_sign_in_link(db, affiliate):
    """The email the whole go-live depends on arriving."""
    application_approved(db, affiliate)

    queued = _outbox(db)
    assert [row.event for row in queued] == [Event.APPLICATION_APPROVED]
    assert queued[0].recipient_email == "nour@example.com"
    assert queued[0].state == NotificationState.PENDING


# -- Nothing sensitive travels ------------------------------------------------


def test_no_payout_detail_reaches_an_email(db, affiliate, monkeypatch):
    """§6.4.5's email says *that* a destination moved, never what to.

    The point is that somebody notices a change happened, not that an account
    number ends up sitting in an inbox that gets forwarded.
    """
    from app.config import settings
    from app.services.notifications import destination_changed

    monkeypatch.setattr(settings, "maintainer_email", "owner@example.com")
    destination_changed(
        db,
        affiliate,
        {"method": "instapay", "instapay_address_url": "…8Xk2Qp", "instapay_phone": "…4567"},
    )

    row = _outbox(db)[0]
    message = render(row.event, dict(row.payload))

    assert ADDRESS not in message.body
    assert "01001234567" not in message.body
    assert "Nour Mahmoud" in message.body


def test_a_month_email_states_a_figure_and_links_to_the_screen(monkeypatch):
    """Phase 9 built the screens. Restating a breakdown in an email is a second
    place for the figures to disagree, and they will be reading both.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://pay.example.com")
    message = render(
        Event.MONTH_APPROVED,
        {
            "email": "nour@example.com",
            "name": "Nour Mahmoud",
            "month": "2026-09",
            "month_name": "September 2026",
            "obligation_piastres": 240_000,
            "version": 1,
        },
    )

    assert "E£2,400.00" in message.body
    assert "https://pay.example.com/" in message.body
    # One figure, not a breakdown. Restating the lines in an email is a second
    # place for them to disagree with the screen, and they read both.
    assert message.body.count("E£") == 1


def test_no_link_is_better_than_a_broken_one(monkeypatch):
    """A sign-in link pointing at localhost teaches twenty people that mail
    from HBA does not work, and that lesson is expensive to unteach.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "")
    message = render(
        Event.APPLICATION_APPROVED,
        {"email": "nour@example.com", "name": "Nour"},
    )

    assert "http" not in message.body


def test_a_name_cannot_inject_a_header(monkeypatch):
    """A model's name is data somebody else typed. Built through the header
    registry rather than by string formatting, so a newline cannot become a
    second recipient.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "mail_from_address", "no-reply@example.com")
    monkeypatch.setattr(settings, "mail_from_name", "HBA")

    built = mail.build(
        mail.Message(
            to_address="nour@example.com",
            to_name="Nour\nBcc: attacker@example.com",
            subject="Test",
            body="Body",
        )
    )

    # The injected text survives as part of the quoted display name, which is
    # harmless. What must not survive is a header break or a second recipient,
    # and neither does: there is exactly one address, and it is theirs.
    header = str(built["To"])
    assert chr(10) not in header and chr(13) not in header
    assert [address.addr_spec for address in built["To"].addresses] == [
        "nour@example.com"
    ]


# -- Sending, and what happens when it cannot ---------------------------------


def test_with_no_credentials_it_is_skipped_not_failed(db, affiliate):
    """A development machine and the test suite are in this state permanently.

    `skipped` and `failed` look identical to a recipient and mean completely
    different things to whoever is looking into it.
    """
    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.SKIPPED
    assert row.sent_at is None


def test_a_sent_notification_is_never_sent_twice(db, affiliate, monkeypatch):
    """A lease can expire and hand the same job to a second worker. A duplicate
    payroll email is a model asking whether they are being paid twice.
    """
    sends = []
    monkeypatch.setattr(
        "app.services.notifications.send", lambda message: sends.append(message) or True
    )

    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()

    send_notification(db, {"outbox_id": row.id})
    send_notification(db, {"outbox_id": row.id})

    assert len(sends) == 1
    assert row.state == NotificationState.SENT
    assert row.sent_at is not None


def test_a_refused_address_is_not_retried(db, affiliate, monkeypatch):
    """A mailbox that does not exist will not exist next minute. Retrying four
    more times only delays somebody noticing the address is wrong.
    """
    def refuse(message):
        raise mail.MailRefused("550 no such user")

    monkeypatch.setattr("app.services.notifications.send", refuse)

    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.FAILED
    assert "550" in row.last_error


def test_a_timeout_is_recorded_on_the_row_and_retried(db, affiliate, monkeypatch):
    """The failure is written to the outbox rather than raised.

    The worker rolls a handler's transaction back when it raises, which would
    take the attempt count with it - the row would sit at `pending` forever
    while the retry budget lived on the job, and an email nobody will receive
    would be invisible from the one table that tracks them.
    """
    from app.models.integration import BackgroundJob

    def timeout(message):
        raise TimeoutError("the mail server did not answer")

    monkeypatch.setattr("app.services.notifications.send", timeout)

    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()

    send_notification(db, {"outbox_id": row.id})
    db.flush()

    assert row.state == NotificationState.PENDING
    assert row.attempts == 1
    assert "did not answer" in row.last_error
    # A fresh job, scheduled later. The first one is about to be marked done.
    retries = list(
        db.scalars(
            select(BackgroundJob).where(BackgroundJob.kind == "notification.send")
        )
    )
    assert len(retries) == 2


def test_it_gives_up_after_the_last_attempt(db, affiliate, monkeypatch):
    def timeout(message):
        raise TimeoutError("still nothing")

    monkeypatch.setattr("app.services.notifications.send", timeout)

    row = queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com", "name": "Nour"},
    )
    db.flush()

    for _ in range(5):
        row.state = NotificationState.PENDING
        send_notification(db, {"outbox_id": row.id})

    assert row.attempts == 5
    assert row.state == NotificationState.FAILED


def test_a_missing_template_fails_the_job_rather_than_the_row(db, affiliate):
    """A code failure, not a delivery one. It belongs in the failed-jobs view
    where somebody looks for a broken deploy.
    """
    from app.services.jobs import PermanentFailure

    row = queue(
        db,
        event="something.nobody.wrote",
        recipient_email="nour@example.com",
        payload={"email": "nour@example.com"},
    )
    db.flush()

    with pytest.raises(PermanentFailure):
        send_notification(db, {"outbox_id": row.id})


def test_an_authentication_failure_is_permanent(monkeypatch):
    """Wrong credentials will be wrong next minute too. The alternative is
    every email in the queue quietly retrying against a rotated password.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "mail_from_address", "no-reply@example.com")

    class Refusing:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            pass

        def login(self, *_):
            raise smtplib.SMTPAuthenticationError(535, b"bad password")

    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: Refusing())
    monkeypatch.setattr(settings, "smtp_username", "someone")

    with pytest.raises(mail.MailRefused):
        mail.send(
            mail.Message(
                to_address="nour@example.com",
                to_name=None,
                subject="Test",
                body="Body",
            )
        )


def test_months_are_written_out_in_words():
    """Email has no frontend to format for it."""
    assert month_in_words("2026-09") == "September 2026"
    assert month_in_words("nonsense") == "nonsense"


# -- An invitation token is a credential --------------------------------------


def test_the_token_is_erased_from_the_outbox_once_sent(db, monkeypatch):
    """`invitations.py` stores only the hash, because the link is a way in
    until it is used. The outbox has to hold the raw value long enough to put
    it in an email and not one moment longer - otherwise the queue quietly
    becomes a table of working sign-in links, which is the exact thing the
    hashing was protecting against.
    """
    from app.config import settings
    from app.services.notifications import invitation_sent

    # Without a base URL there is no link, and therefore no token in the body -
    # which is the correct behaviour and not what this test is about.
    monkeypatch.setattr(settings, "public_base_url", "https://pay.example.com")
    sent = []
    monkeypatch.setattr(
        "app.services.notifications.send", lambda message: sent.append(message) or True
    )

    invitation_sent(db, "someone@example.com", "a-real-looking-token", "affiliate")
    db.flush()
    row = _outbox(db)[0]
    assert row.payload["_secret"]["token"] == "a-real-looking-token"

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.SENT
    assert "_secret" not in row.payload
    # It did reach the email on its way out.
    assert "a-real-looking-token" in sent[0].body


def test_the_token_is_erased_even_when_the_email_never_goes(db):
    """An email that was never delivered still leaves a live token behind.

    This is the state a development machine and the test suite are in
    permanently, so it is the path most likely to accumulate them.
    """
    from app.services.notifications import invitation_sent

    invitation_sent(db, "someone@example.com", "a-real-looking-token", "affiliate")
    db.flush()
    row = _outbox(db)[0]

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.SKIPPED
    assert "_secret" not in row.payload


def test_the_token_is_erased_when_the_address_is_refused(db, monkeypatch):
    def refuse(message):
        raise mail.MailRefused("550 no such user")

    monkeypatch.setattr("app.services.notifications.send", refuse)

    from app.services.notifications import invitation_sent

    invitation_sent(db, "wrong@example.com", "a-real-looking-token", "affiliate")
    db.flush()
    row = _outbox(db)[0]

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.FAILED
    assert "_secret" not in row.payload


def test_a_retry_keeps_the_token_because_it_still_needs_it(db, monkeypatch):
    """The one path that must *not* forget: the email has not gone yet."""
    def timeout(message):
        raise TimeoutError("no answer")

    monkeypatch.setattr("app.services.notifications.send", timeout)

    from app.services.notifications import invitation_sent

    invitation_sent(db, "someone@example.com", "a-real-looking-token", "affiliate")
    db.flush()
    row = _outbox(db)[0]

    send_notification(db, {"outbox_id": row.id})

    assert row.state == NotificationState.PENDING
    assert row.payload["_secret"]["token"] == "a-real-looking-token"


def test_the_invitation_email_carries_a_link_that_works(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "public_base_url", "https://pay.example.com")
    message = render(
        Event.INVITATION_SENT,
        {"email": "someone@example.com", "role": "affiliate", "_secret": {"token": "abc123"}},
    )

    assert "https://pay.example.com/accept-invitation?token=abc123" in message.body
    assert "expires in three days" in message.body


# -- Through the worker, the way production runs it --------------------------


def test_the_registered_handler_is_the_one_that_sends(fresh_database):
    """The bug this file did not catch, and the reason it did not.

    A decorator ended up above the wrong function, so `notification.send` was
    registered to `_forget_secrets` - which the worker then called with two
    arguments. Every email failed with a `TypeError`, five times each, and
    nothing here noticed, because **every test called the handler directly.**

    Calling a function is not the same as it being wired up. This asserts the
    wiring.
    """
    import app.main  # noqa: F401  - importing is what registers the handlers
    from app.services.notifications import JOB_KIND, send_notification
    from app.worker import HANDLERS

    assert HANDLERS[JOB_KIND] is send_notification


def test_a_queued_email_is_sent_by_the_worker(fresh_database, monkeypatch):
    """End to end through the queue: `queue` writes the row and the job, the
    worker leases it, and the row comes out sent.

    The direct-call tests above cover the branches; this covers that the two
    halves are joined at all - which is exactly what broke in production while
    every one of them passed.
    """
    import app.main  # noqa: F401
    from app.db import SessionLocal
    from app.models.notifications import NotificationOutbox, NotificationState
    from app.services.notifications import Event, queue
    from app.worker import run_one

    sent = []
    monkeypatch.setattr(
        "app.services.notifications.send", lambda message: sent.append(message) or True
    )

    with SessionLocal() as session:
        queue(
            session,
            event=Event.APPLICATION_APPROVED,
            recipient_email="nour@example.com",
            payload={"email": "nour@example.com", "name": "Nour"},
        )
        session.commit()

    with SessionLocal() as session:
        assert run_one(session, "test-worker") is True

    with SessionLocal() as session:
        row = session.scalars(select(NotificationOutbox)).one()
        assert row.state == NotificationState.SENT, row.last_error
        assert len(sent) == 1
        assert "on the programme" in sent[0].body


def test_the_worker_does_not_leave_a_token_behind(fresh_database, monkeypatch):
    """The same path as above, for the one payload that carries a credential."""
    import app.main  # noqa: F401
    from app.config import settings
    from app.db import SessionLocal
    from app.models.notifications import NotificationOutbox
    from app.services.notifications import invitation_sent
    from app.worker import run_one

    monkeypatch.setattr(settings, "public_base_url", "https://pay.example.com")
    sent = []
    monkeypatch.setattr(
        "app.services.notifications.send", lambda message: sent.append(message) or True
    )

    with SessionLocal() as session:
        invitation_sent(session, "someone@example.com", "TOKEN-abc", "affiliate")
        session.commit()

    with SessionLocal() as session:
        run_one(session, "test-worker")

    with SessionLocal() as session:
        row = session.scalars(select(NotificationOutbox)).one()
        assert "_secret" not in row.payload
    assert "TOKEN-abc" in sent[0].body


# -- Sending over HTTPS, because the host blocks SMTP ------------------------


def test_smtp_is_only_used_when_nothing_better_is_configured(monkeypatch):
    """Railway blocks outbound SMTP, and so do most hosts.

    Every notification the platform queued failed with
    `OSError: [Errno 101] Network is unreachable` connecting to port 587. Not
    a credential problem and not fixable by changing a password - so an HTTP
    key has to win, because on such a host SMTP is not a fallback, it is a
    guaranteed and silent failure.
    """
    from app.config import settings
    from app.services.mail import MailProvider, transport

    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "brevo_api_key", "", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com", raising=False)
    assert transport() == MailProvider.SMTP

    monkeypatch.setattr(settings, "brevo_api_key", "a-key", raising=False)
    assert transport() == MailProvider.BREVO

    monkeypatch.setattr(settings, "resend_api_key", "another", raising=False)
    assert transport() == MailProvider.RESEND


def test_mail_counts_as_configured_with_only_an_http_key(monkeypatch):
    """`mail_configured` decides whether the screen says an invitation was
    emailed. It asked for an SMTP host, so a platform sending perfectly well
    over HTTPS would have reported that email was switched off.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "brevo_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "mail_from_address", "hba@example.com", raising=False)

    assert settings.mail_configured is True


def test_a_provider_that_refuses_is_not_retried(monkeypatch):
    """A 4xx will not become acceptable by being repeated: a rejected sender, a
    malformed address, a revoked key.
    """
    import httpx

    from app.config import settings
    from app.services import mail

    monkeypatch.setattr(settings, "brevo_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "mail_from_address", "hba@example.com", raising=False)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: httpx.Response(403, text="sender not verified"),
    )

    with pytest.raises(mail.MailRefused) as refused:
        mail.send(
            mail.Message(
                to_address="nour@example.com", to_name=None, subject="x", body="y"
            )
        )

    assert "sender not verified" in str(refused.value)


def test_a_provider_that_is_unreachable_is_retried(monkeypatch):
    """Unlike a refusal. This is the failure that was happening on every send,
    and it has to stay retryable rather than becoming permanent.
    """
    import httpx

    from app.config import settings
    from app.services import mail

    monkeypatch.setattr(settings, "brevo_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "mail_from_address", "hba@example.com", raising=False)

    def unreachable(*a, **k):
        raise httpx.ConnectError("Network is unreachable")

    monkeypatch.setattr(httpx, "post", unreachable)

    with pytest.raises(RuntimeError) as failed:
        mail.send(
            mail.Message(
                to_address="nour@example.com", to_name=None, subject="x", body="y"
            )
        )

    assert not isinstance(failed.value, mail.MailRefused)


def test_the_message_reaches_the_provider_intact(monkeypatch):
    """Including the link, which is the only part of an invitation that
    matters.
    """
    import httpx

    from app.config import settings
    from app.services import mail

    monkeypatch.setattr(settings, "brevo_api_key", "a-key", raising=False)
    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "mail_from_address", "hba@example.com", raising=False)
    monkeypatch.setattr(settings, "mail_from_name", "HBA Aesthetics", raising=False)

    captured = {}

    def capture(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(201, json={"messageId": "1"})

    monkeypatch.setattr(httpx, "post", capture)

    sent = mail.send(
        mail.Message(
            to_address="nour@example.com",
            to_name="Nour",
            subject="Your HBA affiliate account",
            body="Open this link:\nhttps://pay.example.com/accept-invitation?token=abc",
        )
    )

    assert sent is True
    assert "brevo" in captured["url"]
    assert captured["json"]["sender"] == {
        "name": "HBA Aesthetics",
        "email": "hba@example.com",
    }
    assert captured["json"]["to"] == [{"email": "nour@example.com"}]
    assert "accept-invitation?token=abc" in captured["json"]["textContent"]
    assert captured["headers"]["api-key"] == "a-key"


# ── The brand around the words ──────────────────────────────────────────────
#
# The plain text is the source and the HTML is derived from it, so the two can
# never say different things - and a template added later is branded without
# anybody remembering to brand it.


def test_the_html_carries_the_same_words_as_the_text(monkeypatch):
    from app.services.mail_branding import wrap

    body = "Hi Nour,\n\nSeptember is closed and agreed at E£280.00."
    rendered = wrap(body)

    assert "September is closed and agreed at E£280.00." in rendered
    assert "Hi Nour," in rendered


def test_a_link_becomes_a_button_and_stays_copyable(monkeypatch):
    """A button cannot be forwarded to a laptop or read out over the phone,
    and a client that refuses to render it still needs the address."""
    from app.config import settings
    from app.services.mail_branding import wrap

    monkeypatch.setattr(settings, "public_base_url", "https://example.test")
    rendered = wrap("Open this:\nhttps://example.test/accept-invitation?token=x")

    assert "Open it" in rendered
    assert "Or copy this" in rendered
    assert rendered.count("https://example.test/accept-invitation?token=x") >= 2


def test_the_words_are_escaped(monkeypatch):
    """A model's name is data. `Nour <script>` must arrive as text."""
    from app.services.mail_branding import wrap

    rendered = wrap("Hi Nour <script>alert(1)</script>,\n\nSomething happened.")

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_an_email_survives_the_platform_not_knowing_its_address(monkeypatch):
    """Same condition that leaves invitation links empty. An email with no
    logo is fine; one with a broken image is not."""
    from app.config import settings
    from app.services.mail_branding import wrap

    monkeypatch.setattr(settings, "public_base_url", "")
    rendered = wrap("Hi Nour,\n\nSomething happened.")

    assert "<img" not in rendered
    assert "HBA" in rendered
    assert "Something happened." in rendered


def test_the_signature_is_not_printed_twice(monkeypatch):
    """The templates end with a plain-text sign-off written for text. The HTML
    has a signature block of its own."""
    from app.services.mail_branding import wrap

    rendered = wrap("Hi Nour,\n\nSomething happened.\n\nHBA Aesthetics")

    assert "HBA Aesthetics" not in rendered
    assert rendered.count("The HBA Team") == 1


# -- What a model asked not to hear -------------------------------------------
#
# Two switches, and the rule that matters is that each stops exactly what it
# names. A switch that muted more than it said would be worse than no switch:
# the model would stop hearing about being paid and have no way to know why.


class _Transaction:
    """The two fields `payment_recorded` reads. Enough, and no fixture."""

    amount_piastres = 250_000
    proof_file_id = None


def test_turning_off_one_message_leaves_the_other_alone(db, affiliate):
    from app.models.notifications import NotificationKind
    from app.services.notification_prefs import set_preference
    from app.services.notifications import payment_recorded

    set_preference(
        db, affiliate, kind=NotificationKind.PAYMENT_SENT, enabled=False
    )
    db.flush()

    payment_recorded(db, affiliate, _Transaction())
    db.flush()

    assert _outbox(db) == [], "they asked not to hear about payments"

    # And the switch they did not touch still sends.
    set_preference(db, affiliate, kind=NotificationKind.PAYMENT_SENT, enabled=True)
    db.flush()
    payment_recorded(db, affiliate, _Transaction())
    db.flush()

    assert [row.event for row in _outbox(db)] == ["payment.recorded"]


def test_a_model_who_never_opened_the_screen_still_hears(db, affiliate):
    """Absence means on.

    The alternative - a row seeded per model at sign-up - silently mutes
    anybody the seeding misses, and nobody finds out until a month closes in
    silence.
    """
    from app.services.notifications import payment_recorded

    payment_recorded(db, affiliate, _Transaction())
    db.flush()

    assert [row.event for row in _outbox(db)] == ["payment.recorded"]


def test_security_mail_is_not_something_a_model_can_mute(db, affiliate):
    """Only the two routine messages are gateable.

    An invitation, a password reset and the notice that somebody moved where
    your money goes are not news, they are security. There is no switch for
    them, and `GATED_BY` is the list that says so.
    """
    from app.services.notification_prefs import GATED_BY

    assert set(GATED_BY) == {Event.MONTH_APPROVED, Event.PAYMENT_RECORDED}
