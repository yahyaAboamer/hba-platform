"""Error alerts: what reaches Sentry, and what never does (Phase 1, batch 1).

**Off until a DSN is set.** `init_observability` returns without touching the
SDK when `SENTRY_DSN` is blank, so a development machine, the test suite and a
server nobody has configured send nothing anywhere.

**What is sent** is an error and the code it happened in: the exception's type,
its message, the stack, the route's *pattern* (``/api/affiliates/{id}``), the
environment and the deployed commit. That is enough to answer "what broke,
where, since which deploy".

**What is never sent**, each rule tested in ``tests/test_observability.py``:

- request bodies, cookies, headers, the query string and the server
  environment - a sign-in body holds a password, a cookie is a session, a reset
  or invitation link carries its token after the ``?``;
- the signed-in person (``user``) and anything Sentry would add on its own as
  personal data (``send_default_pii=False``);
- local variables in stack frames, which can hold a customer's phone or a
  decrypted key;
- the values interpolated into log lines. A log line here is written for the
  platform's own logs, and many carry an order id, an error text from a
  provider or a job's payload. Sentry keeps the line's *template*
  (``"job %s (%s) failed%s: %s"``) with only its numbers filled in;
- query strings and fragments on any URL the platform called (Shopify, Bosta,
  E-stebdal, Meta), and any user:password in one;
- the bound parameters and the ``DETAIL`` line inside a database error, which
  repeat the row that was refused - an email, a phone;
- performance traces and profiles: nothing is timed, and no tracing header is
  added to a call to Shopify or Meta.

A background job that fails for good is reported by `report_job_failed_for_good`
with its kind, id and attempts - never its payload.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

logger = logging.getLogger(__name__)

#: What stands in for a value that was removed.
FILTERED = "[filtered]"

#: The parts of a request Sentry may keep. Everything else - body (`data`),
#: cookies, headers, query string, environment - is removed.
_REQUEST_KEEP = ("method", "url")

#: The anomaly logger (app/core/signals.py). Its line is
#: ``ANOMALY <name> <context>``; the name is a constant from `Anomaly`, the
#: context is not, and can be a whole job payload.
_ANOMALY_LOGGER = "hba.anomaly"

_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'\"<>]+")
#: A path quoted without its scheme ("GET /reset-password?token=..."): kept up
#: to its ``?`` or ``#``.
_PATH_QUERY = re.compile(r"(^|[\s'\"(=])(/[^\s?#'\"<>()]*)[?#][^\s'\"<>()]*")
#: A ``token=`` value anywhere in an error's text, quoted or not.
_TOKEN_VALUE = re.compile(r"(?i)(token=)[^\s&'\"<>]+")
_SQL_PARAMETERS = re.compile(r"\[parameters: [^\n]*")
_PG_DETAIL = re.compile(r"DETAIL:[^\n]*")

#: Breadcrumb data keys that are a URL's query or fragment on their own.
_URL_PART_KEYS = frozenset({"http.query", "http.fragment", "url.query", "url.fragment"})


def environment_name(settings) -> str | None:
    """Which deployment this is, for telling staging and production apart.

    Not `APP_ENV`, first: staging runs with APP_ENV=production for its secure
    cookies (RULES.md), so on its own it would label staging's errors as
    production's. An explicit SENTRY_ENVIRONMENT wins, then the name Railway
    gives the environment, then APP_ENV for a machine that is not on Railway.
    """
    for value in (
        settings.sentry_environment,
        settings.railway_environment_name,
        settings.app_env,
    ):
        if value and value.strip():
            return value.strip()
    return None


def release_name(settings) -> str | None:
    """The deployed commit, so "since which deploy" has an answer."""
    sha = (settings.railway_git_commit_sha or "").strip()
    return sha or None


def init_observability(settings, *, transport: Any = None) -> bool:
    """Start error reporting if a DSN is configured. Returns whether it did.

    Called once, at startup, before the FastAPI app is built: the FastAPI
    integration wraps route handlers as they are registered. ``transport`` is
    for tests only - a capturing transport, so nothing ever leaves the machine.
    """
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=environment_name(settings),
        release=release_name(settings),
        transport=transport,
        # ── Privacy: each of these is asserted by a test. ──
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
        before_breadcrumb=scrub_breadcrumb,
        # ── Errors only: no performance tracing, no profiling. ──
        traces_sample_rate=None,
        profiles_sample_rate=None,
        profile_session_sample_rate=None,
        # Never add sentry-trace / baggage headers to a call to Shopify, Bosta,
        # E-stebdal or Meta.
        trace_propagation_targets=[],
        enable_logs=False,
        # Only what is listed here, not whatever happens to be importable.
        auto_enabling_integrations=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            HttpxIntegration(),
            # Warnings become breadcrumbs (scrubbed to their template);
            # logger.error / logger.exception become events - which is how a
            # failing worker loop ("worker iteration failed") is reported.
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
    )
    return True


# ── Scrubbing ─────────────────────────────────────────────────────────────────


def strip_url(value: str) -> str:
    """A URL without its query string, its fragment or any user:password."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value.split("?", 1)[0].split("#", 1)[0]
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _strip_urls_in(text: str) -> str:
    return _URL.sub(lambda match: strip_url(match.group(0)), text)


def _scrub_error_text(text: str) -> str:
    """An exception's message, without the row a database error repeats."""
    text = _SQL_PARAMETERS.sub(f"[parameters: {FILTERED}]", text)
    text = _PG_DETAIL.sub(f"DETAIL: {FILTERED}", text)
    text = _strip_urls_in(text)
    text = _PATH_QUERY.sub(r"\1\2", text)
    return _TOKEN_VALUE.sub(rf"\1{FILTERED}", text)


def _render_template(template: Any, args: Any) -> str:
    """A log line with only its numbers filled in.

    Strings are not filled in: an id is a number here, and a string argument
    is as likely to be a provider's error text or a payload as a job kind.
    """
    if not isinstance(template, str):
        return FILTERED
    if not args:
        return template
    if isinstance(args, dict):
        return template
    values = tuple(
        arg if isinstance(arg, (int, float)) and not isinstance(arg, bool) else FILTERED
        for arg in (args if isinstance(args, tuple) else (args,))
    )
    try:
        return template % values
    except (TypeError, ValueError):
        return template


def _safe_log_message(record: logging.LogRecord) -> str:
    if record.name == _ANOMALY_LOGGER and record.args:
        # ``ANOMALY %s %s``: the first argument is the anomaly's name.
        first = record.args[0] if isinstance(record.args, tuple) else None
        if isinstance(first, str) and re.fullmatch(r"[a-z_]+", first):
            return f"ANOMALY {first}"
        return "ANOMALY"
    return _render_template(record.msg, record.args)


def scrub_breadcrumb(crumb: dict, hint: dict | None) -> dict | None:
    """Applied to every breadcrumb before it is kept."""
    record = (hint or {}).get("log_record")
    if record is not None:
        crumb["message"] = _safe_log_message(record)
        crumb["data"] = {}
        return crumb

    if crumb.get("category") == "subprocess":
        # A command line can carry anything; the platform runs none on purpose.
        return None

    data = crumb.get("data")
    if isinstance(data, dict):
        cleaned = {}
        for key, value in data.items():
            if key in _URL_PART_KEYS:
                continue
            if isinstance(value, str):
                value = _strip_urls_in(value)
            cleaned[key] = value
        crumb["data"] = cleaned
    if isinstance(crumb.get("message"), str):
        crumb["message"] = _strip_urls_in(crumb["message"])
    return crumb


def scrub_event(event: dict, hint: dict | None) -> dict | None:
    """Applied to every event before it is sent."""
    event.pop("user", None)
    # `extra` carries a log record's extra fields and the process's argv;
    # neither is needed to find a bug, and either could hold anything.
    event.pop("extra", None)

    request = event.get("request")
    if isinstance(request, dict):
        kept = {key: request[key] for key in _REQUEST_KEEP if key in request}
        if isinstance(kept.get("url"), str):
            kept["url"] = strip_url(kept["url"])
        event["request"] = kept

    record = (hint or {}).get("log_record")
    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        if record is not None:
            # The template groups the issue; the safe rendering is what shows.
            safe = _safe_log_message(record)
            template = record.msg if isinstance(record.msg, str) else safe
            if record.name == _ANOMALY_LOGGER:
                template = safe
            event["logentry"] = {"message": template, "formatted": safe}
        else:
            message = logentry.get("message")
            event["logentry"] = {
                "message": _scrub_error_text(message) if isinstance(message, str) else FILTERED
            }

    for exception in (event.get("exception") or {}).get("values") or []:
        if isinstance(exception.get("value"), str):
            exception["value"] = _scrub_error_text(exception["value"])
        for frame in (exception.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)

    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        # Already scrubbed as they were recorded; the URL rule again, in case
        # one was added by a path that skipped before_breadcrumb.
        data = crumb.get("data")
        if isinstance(data, dict):
            for key in list(data):
                if key in _URL_PART_KEYS:
                    data.pop(key)
                elif isinstance(data[key], str):
                    data[key] = _strip_urls_in(data[key])
    return event


# ── The worker ────────────────────────────────────────────────────────────────


def report_job_failed_for_good(*, job_id: int, kind: str, attempts: int) -> None:
    """One event for a background job that will not be tried again.

    Its kind, id and attempts - never its payload or its error text, both of
    which can name a customer. The error is on the job's row for whoever looks.
    Grouped by kind, so a hundred failed syncs are one issue. A no-op when
    error reporting is off.
    """
    if not sentry_sdk.get_client().is_active():
        return
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_level("error")
            scope.set_tag("job_kind", kind)
            scope.set_context("job", {"id": job_id, "kind": kind, "attempts": attempts})
            scope.fingerprint = ["background-job-failed", kind]
            sentry_sdk.capture_message(f"Background job failed for good: {kind}")
    except Exception:  # noqa: BLE001 - reporting must never fail the worker
        logger.warning("could not report a failed job")
