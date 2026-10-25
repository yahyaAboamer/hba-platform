"""Error alerts: what reaches Sentry, and what never does.

Every event goes to a capturing transport; nothing here touches the network.
Sentry's state is process-wide, so each test that starts it puts it back the
way it found it (`sentry` fixture) - another test file must never inherit a
live client.
"""

import asyncio
import contextlib
import json
import logging

import httpx
import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.tracing_utils import has_tracing_enabled
from sentry_sdk.transport import Transport
from sqlalchemy import text

from app.config import Settings
from app.core import observability
from app.core.observability import (
    environment_name,
    init_observability,
    release_name,
    scrub_breadcrumb,
    scrub_event,
)
from app.core.signals import Anomaly, report
from app.db import SessionLocal
from app.services.jobs import MAX_ATTEMPTS, PermanentFailure, enqueue
from app.worker import HANDLERS, register_handler, run_one

#: Shaped like an EU-region DSN. Never contacted: the transport below is used.
DSN = "https://0123456789abcdef@o0.ingest.de.sentry.io/1"

#: Values that must never appear anywhere in anything sent. Tests that raise
#: refer to them by name, never by value: a stack frame carries the lines of
#: source around it, which is code and fine to send - but a literal secret in
#: the test's own source would then look like a leak.
PASSWORD = "hunter2-password"
TOKEN = "reset-token-abc123"
FRAGMENT = "fragment-secret"
BEARER = "bearer-xyz789"
COOKIE = "session-cookie-456"
PHONE = "+201001234567"
EMAIL = "customer@example.com"
LOCAL = "local-variable-secret"
SECRETS = (PASSWORD, TOKEN, FRAGMENT, BEARER, COOKIE, PHONE, EMAIL, LOCAL)


class CapturingTransport(Transport):
    """Keeps every event instead of sending it."""

    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []
        self.envelopes = 0

    def capture_envelope(self, envelope):
        self.envelopes += 1
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)

    def flush(self, timeout, callback=None):
        return None

    def kill(self):
        return None


def _settings(**overrides) -> Settings:
    values = {
        "sentry_dsn": DSN,
        "sentry_environment": "",
        "railway_environment_name": "",
        "railway_git_commit_sha": "",
        "app_env": "development",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _reset_sentry() -> None:
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close(timeout=0)
    sentry_sdk.get_global_scope().set_client(None)
    for scope in (
        sentry_sdk.get_global_scope(),
        sentry_sdk.get_isolation_scope(),
        sentry_sdk.get_current_scope(),
    ):
        scope.clear()


@pytest.fixture()
def sentry():
    """Start error reporting into a capturing transport; tear it down after."""
    _reset_sentry()
    transport = CapturingTransport()
    assert init_observability(_settings(), transport=transport) is True
    yield transport
    _reset_sentry()


def _dump(event: dict) -> str:
    return json.dumps(event, default=str)


def _assert_no_secrets(event: dict) -> None:
    dumped = _dump(event)
    for secret in SECRETS:
        assert secret not in dumped, f"{secret!r} reached Sentry"


# ── Off without a DSN ─────────────────────────────────────────────────────────


def test_without_a_dsn_nothing_is_started(monkeypatch):
    _reset_sentry()

    def must_not_run(*args, **kwargs):  # pragma: no cover - the assertion
        raise AssertionError("sentry_sdk.init was called without a DSN")

    monkeypatch.setattr(observability.sentry_sdk, "init", must_not_run)
    assert init_observability(_settings(sentry_dsn="")) is False
    assert init_observability(_settings(sentry_dsn="   ")) is False
    assert sentry_sdk.get_client().is_active() is False
    # And reporting a failed job is a quiet no-op.
    observability.report_job_failed_for_good(job_id=1, kind="k", attempts=5)


# ── The privacy settings themselves ──────────────────────────────────────────


def test_the_privacy_settings(sentry):
    options = sentry_sdk.get_client().options
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["before_send"] is scrub_event
    assert options["before_breadcrumb"] is scrub_breadcrumb
    assert options["enable_logs"] is False
    assert options["trace_propagation_targets"] == []
    # No performance tracing, no profiling.
    assert options["traces_sample_rate"] is None
    assert options["traces_sampler"] is None
    assert options["profiles_sample_rate"] is None
    assert options["profile_session_sample_rate"] is None
    assert has_tracing_enabled(options) is False
    assert sentry_sdk.get_client().transport is sentry


def test_staging_is_not_called_production():
    # Staging runs with APP_ENV=production; the environment must not follow it.
    assert environment_name(_settings(app_env="production", sentry_environment="staging")) == "staging"
    assert (
        environment_name(_settings(app_env="production", railway_environment_name="staging"))
        == "staging"
    )
    assert (
        environment_name(
            _settings(
                app_env="production",
                railway_environment_name="staging",
                sentry_environment="staging-eu",
            )
        )
        == "staging-eu"
    )
    assert environment_name(_settings(app_env="development")) == "development"


def test_the_release_is_the_deployed_commit():
    assert release_name(_settings(railway_git_commit_sha="abc123def")) == "abc123def"
    assert release_name(_settings(railway_git_commit_sha="")) is None


def test_events_carry_environment_and_release():
    _reset_sentry()
    transport = CapturingTransport()
    try:
        init_observability(
            _settings(
                app_env="production",
                railway_environment_name="staging",
                railway_git_commit_sha="deadbeef",
            ),
            transport=transport,
        )
        sentry_sdk.capture_message("hello")
    finally:
        _reset_sentry()
    (event,) = transport.events
    assert event["environment"] == "staging"
    assert event["release"] == "deadbeef"


# ── before_send ───────────────────────────────────────────────────────────────


def test_before_send_removes_everything_personal_from_an_event():
    event = {
        "user": {"id": 7, "email": "customer@example.com"},
        "extra": {"sys.argv": ["uvicorn"], "phone": "+201001234567"},
        "request": {
            "method": "POST",
            "url": "https://hba.example/api/auth/reset?token=reset-token-abc123#fragment-secret",
            "query_string": "token=reset-token-abc123",
            "cookies": {"hba_session": "session-cookie-456"},
            "headers": {"Authorization": "Bearer bearer-xyz789"},
            "data": {"password": "hunter2-password"},
            "env": {"REMOTE_ADDR": "10.0.0.1"},
        },
        "exception": {
            "values": [
                {
                    "type": "IntegrityError",
                    "value": (
                        "(psycopg.errors.UniqueViolation) duplicate key value\n"
                        "DETAIL:  Key (email)=(customer@example.com) already exists.\n"
                        "[SQL: INSERT INTO user_account (email) VALUES (%(email)s)]\n"
                        "[parameters: {'email': 'customer@example.com'}]\n"
                        "(Background on this error at: https://sqlalche.me/e/20/gkpj)"
                    ),
                    "stacktrace": {
                        "frames": [{"function": "f", "vars": {"secret": "local-variable-secret"}}]
                    },
                }
            ]
        },
    }
    scrubbed = scrub_event(event, {})

    assert "user" not in scrubbed
    assert "extra" not in scrubbed
    assert scrubbed["request"] == {
        "method": "POST",
        "url": "https://hba.example/api/auth/reset",
    }
    value = scrubbed["exception"]["values"][0]["value"]
    assert "duplicate key value" in value  # still says what went wrong
    assert "INSERT INTO user_account" in value  # the statement is code, kept
    assert "vars" not in scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    _assert_no_secrets(scrubbed)


def test_an_error_that_quotes_a_link_or_a_token_loses_them():
    """A message can quote a path without its scheme, or a bare token=."""
    event = {
        "exception": {
            "values": [
                {"type": "ValueError", "value": "GET /reset-password?token=reset-token-abc123 failed"},
                {"type": "ValueError", "value": "refused token=bearer-xyz789&next=1"},
            ]
        },
        "logentry": {"message": "could not open (/accept-invitation?token=reset-token-abc123#f)"},
    }
    scrubbed = scrub_event(event, {})

    values = [v["value"] for v in scrubbed["exception"]["values"]]
    assert values == ["GET /reset-password failed", "refused token=[filtered]&next=1"]
    assert scrubbed["logentry"]["message"] == "could not open (/accept-invitation)"
    _assert_no_secrets(scrubbed)


def test_a_url_loses_its_query_fragment_and_credentials():
    assert (
        observability.strip_url("https://user:pass@shop.example/a/b?x=1&y=2#frag")
        == "https://shop.example/a/b"
    )
    assert observability.strip_url("/invite?token=t#f") == "/invite"


# ── before_breadcrumb ─────────────────────────────────────────────────────────


def test_outgoing_calls_are_recorded_without_query_or_fragment(sentry):
    def answer(request):
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        client.get("https://bosta.example/api/v2/deliveries?apiKey=reset-token-abc123#fragment-secret")
    sentry_sdk.capture_message("look at the breadcrumbs")

    (event,) = sentry.events
    crumbs = [c for c in event["breadcrumbs"]["values"] if c.get("category") == "httplib"]
    assert crumbs, "the httpx integration recorded no breadcrumb"
    data = crumbs[-1]["data"]
    assert data["url"] == "https://bosta.example/api/v2/deliveries"
    assert "http.query" not in data and "http.fragment" not in data
    _assert_no_secrets(event)


def test_no_tracing_header_is_added_to_an_outgoing_call(sentry):
    seen = {}

    def answer(request):
        seen.update(request.headers)
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(answer)) as client:
        client.get("https://shop.example/admin/api/graphql.json")
    assert "sentry-trace" not in seen
    assert "baggage" not in seen


def test_a_url_anywhere_in_breadcrumb_data_is_stripped():
    crumb = scrub_breadcrumb(
        {
            "category": "custom",
            "message": "fetched https://graph.example/v1/media?access_token=bearer-xyz789",
            "data": {
                "url": "https://lookaside.example/file?token=reset-token-abc123#fragment-secret",
                "url.query": "token=reset-token-abc123",
                "note": "see https://x.example/p?q=customer@example.com",
                "status": 200,
            },
        },
        {},
    )
    assert crumb["data"] == {
        "url": "https://lookaside.example/file",
        "note": "see https://x.example/p",
        "status": 200,
    }
    assert crumb["message"] == "fetched https://graph.example/v1/media"


def test_a_subprocess_breadcrumb_is_dropped():
    assert scrub_breadcrumb({"category": "subprocess", "message": "x --key secret"}, {}) is None


def test_a_log_line_keeps_its_template_and_numbers_only(sentry):
    log = logging.getLogger("app.services.inbox.payments")
    log.warning("order %s: invoice email not sent: %s", 4512, "550 customer@example.com rejected")
    sentry_sdk.capture_message("look at the breadcrumbs")

    (event,) = sentry.events
    messages = [c.get("message") for c in event["breadcrumbs"]["values"]]
    assert "order 4512: invoice email not sent: [filtered]" in messages
    _assert_no_secrets(event)


def test_an_anomaly_keeps_its_name_and_loses_its_context(sentry):
    report(
        Anomaly.JOB_GAVE_UP,
        job_id=9,
        kind="inbox_send",
        payload={"phone": "+201001234567"},
        last_error="customer@example.com",
    )
    sentry_sdk.capture_message("look at the breadcrumbs")

    (event,) = sentry.events
    messages = [c.get("message") for c in event["breadcrumbs"]["values"]]
    assert "ANOMALY job_gave_up" in messages
    _assert_no_secrets(event)


def test_logger_exception_becomes_a_scrubbed_event(sentry):
    log = logging.getLogger("app.worker")
    try:
        raise RuntimeError("database unreachable")
    except RuntimeError:
        log.exception("could not process %s", EMAIL)

    (event,) = sentry.events
    assert event["level"] == "error"
    assert event["logentry"]["message"] == "could not process %s"
    assert event["logentry"]["formatted"] == "could not process [filtered]"
    assert "params" not in event["logentry"]
    assert event["exception"]["values"][-1]["value"] == "database unreachable"
    _assert_no_secrets(event)


# ── A request that fails ──────────────────────────────────────────────────────


def test_an_unhandled_exception_in_a_request_is_captured_and_scrubbed(sentry):
    # Built after init, as app.main builds its app after init_observability.
    app = FastAPI()

    @app.post("/api/things/{thing_id}")
    def explode(thing_id: int):
        secret = LOCAL  # noqa: F841 - must not be sent
        raise ValueError("something broke")

    client = TestClient(app, raise_server_exceptions=False, cookies={"hba_session": COOKIE})
    response = client.post(
        f"/api/things/12?token={TOKEN}",
        json={"password": PASSWORD, "phone": PHONE},
        headers={"Authorization": f"Bearer {BEARER}"},
    )
    assert response.status_code == 500

    assert len(sentry.events) == 1
    (event,) = sentry.events
    assert event["exception"]["values"][-1]["type"] == "ValueError"
    assert event["exception"]["values"][-1]["value"] == "something broke"
    assert event["request"]["method"] == "POST"
    assert event["request"]["url"].endswith("/api/things/12")
    assert set(event["request"]) <= {"method", "url"}
    assert "user" not in event
    for exception in event["exception"]["values"]:
        for frame in exception.get("stacktrace", {}).get("frames", []):
            assert "vars" not in frame
    _assert_no_secrets(event)


def test_a_client_error_is_not_an_alert(sentry):
    app = FastAPI()

    @app.get("/api/missing")
    def missing():
        from fastapi import HTTPException

        raise HTTPException(404, "Not found")

    assert TestClient(app).get("/api/missing").status_code == 404
    assert sentry.events == []


# ── The worker ────────────────────────────────────────────────────────────────


@pytest.fixture()
def _isolated_handlers():
    original = dict(HANDLERS)
    yield
    HANDLERS.clear()
    HANDLERS.update(original)


@pytest.fixture()
def session(fresh_database, _isolated_handlers):
    with SessionLocal() as db:
        yield db


def _job_events(transport) -> list[dict]:
    return [e for e in transport.events if (e.get("contexts") or {}).get("job")]


def test_a_permanent_failure_sends_one_event_without_its_payload(sentry, session):
    @register_handler("obs_permanent")
    def handle(db, payload):
        raise PermanentFailure(f"no such customer {payload['phone']}")

    job = enqueue(session, "obs_permanent", {"phone": PHONE, "email": EMAIL})
    session.commit()
    job_id = job.id

    assert run_one(session, worker_id="w") is True

    (event,) = sentry.events
    assert event["level"] == "error"
    assert event["contexts"]["job"] == {
        "id": job_id,
        "kind": "obs_permanent",
        "attempts": MAX_ATTEMPTS,
    }
    assert event["tags"]["job_kind"] == "obs_permanent"
    assert event["fingerprint"] == ["background-job-failed", "obs_permanent"]
    _assert_no_secrets(event)


def test_a_failure_that_will_be_retried_sends_nothing(sentry, session):
    @register_handler("obs_flaky")
    def handle(db, payload):
        raise RuntimeError("try again later")

    enqueue(session, "obs_flaky", {"phone": "+201001234567"})
    session.commit()

    assert run_one(session, worker_id="w") is True
    assert sentry.events == []


def test_the_last_retry_sends_one_event(sentry, session):
    @register_handler("obs_exhausted")
    def handle(db, payload):
        raise RuntimeError(f"still failing for {EMAIL}")

    job = enqueue(session, "obs_exhausted", {"phone": "+201001234567"})
    session.commit()
    session.execute(
        text("UPDATE background_job SET attempts = :a WHERE id = :i"),
        {"a": MAX_ATTEMPTS - 1, "i": job.id},
    )
    session.commit()

    assert run_one(session, worker_id="w") is True
    (event,) = _job_events(sentry)
    assert len(sentry.events) == 1
    assert event["contexts"]["job"]["attempts"] == MAX_ATTEMPTS
    _assert_no_secrets(event)


def test_a_job_with_no_handler_sends_one_event(sentry, session):
    enqueue(session, "obs_nobody_handles_this", {"email": "customer@example.com"})
    session.commit()

    assert run_one(session, worker_id="w") is True
    (event,) = sentry.events
    assert event["contexts"]["job"]["kind"] == "obs_nobody_handles_this"
    _assert_no_secrets(event)


def test_a_failing_worker_loop_is_reported(sentry, monkeypatch):
    from app import worker

    def broken(*args, **kwargs):
        raise RuntimeError("queue unreachable")

    monkeypatch.setattr(worker, "_iteration", broken)
    monkeypatch.setattr(worker.settings, "worker_poll_seconds", 0.01)

    async def run_until_reported():
        task = asyncio.create_task(worker.worker_loop("main"))
        for _ in range(300):
            await asyncio.sleep(0.01)
            if sentry.events:
                break
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    asyncio.run(run_until_reported())

    event = sentry.events[0]
    assert event["logentry"]["message"] == "worker iteration failed"
    assert event["exception"]["values"][-1]["value"] == "queue unreachable"


# ── /api/client-config ────────────────────────────────────────────────────────


def _client_config(monkeypatch, **values):
    from app.config import settings
    from app.main import app

    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    # No sign-in: a bare client with no cookies.
    return TestClient(app).get("/api/client-config")


def test_client_config_without_a_dsn(monkeypatch):
    response = _client_config(
        monkeypatch,
        sentry_frontend_dsn="",
        sentry_environment="staging",
        railway_git_commit_sha="abc",
    )
    assert response.status_code == 200
    assert response.json() == {"sentry_dsn": None, "environment": None, "release": None}


def test_client_config_with_a_dsn(monkeypatch):
    response = _client_config(
        monkeypatch,
        sentry_frontend_dsn="https://browserkey@o0.ingest.de.sentry.io/2",
        sentry_dsn="https://serverkey@o0.ingest.de.sentry.io/1",
        sentry_environment="",
        railway_environment_name="staging",
        app_env="production",
        railway_git_commit_sha="abc123",
    )
    assert response.status_code == 200
    assert response.json() == {
        "sentry_dsn": "https://browserkey@o0.ingest.de.sentry.io/2",
        "environment": "staging",
        "release": "abc123",
    }
    # The server's own DSN is never handed out.
    assert "serverkey" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
