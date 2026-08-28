"""Operational visibility.

A failed background job that exists only in a log file is invisible. These
endpoints put sync state, failures, and unattributed codes where the maintainer
will actually see them - the point being to learn about a sync failure from the
platform rather than from a confused affiliate.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.config import settings
from app.core.businesstime import parse_month, utcnow
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import UserAccount
from app.services.jobs import JobKind, JobStatus, enqueue
from app.services.schedule import SCHEDULE
from app.services.shopify.client import (
    ShopifyError,
    ShopifyMissingScope,
    ShopifyNotConfigured,
)
from app.services.shopify.client import REQUIRED_SCOPES
from app.services.shopify.discounts import REQUIRED_SCOPE, verify_discount_code
from app.services.shopify.facts import DEFAULT_SAMPLE

router = APIRouter(prefix="/api/operations")

#: The earliest the business wants history from. Anything before this is not a
#: mistake so much as a much larger export than anyone intended.
EARLIEST_IMPORT = "2026-01-01"


class VerifyCodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=120)


class StartImportBody(BaseModel):
    since: str = Field(default=EARLIEST_IMPORT)

    @field_validator("since")
    @classmethod
    def _must_be_a_date(cls, value: str) -> str:
        text_value = str(value or "").strip()
        try:
            year, month, day = (int(part) for part in text_value.split("-"))
            parse_month(f"{year:04d}-{month:02d}")
            if not 1 <= day <= 31:
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise ValueError("since must be a date like 2026-01-01") from exc
        return text_value


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


@router.get("/sync")
def sync_status(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Is order data flowing, and is the safety net running?

    The second half matters as much as the first. Recurring work is queued by
    the worker itself, so if the worker stops, the reconciliation sweep stops
    too - with no error, because nothing failed (docs/limits.md). Reporting
    when it last ran is what makes that visible instead of silent.
    """
    jobs = dict(
        db.execute(
            text("SELECT status, count(*) FROM background_job GROUP BY status")
        ).all()
    )

    recurring = {}
    for kind in SCHEDULE:
        row = db.execute(
            text(
                "SELECT max(finished_at) FILTER (WHERE status = 'succeeded') AS last_run, "
                "       min(run_after) FILTER (WHERE status = 'pending') AS next_due "
                "FROM background_job WHERE kind = :kind"
            ),
            {"kind": kind},
        ).mappings().one()
        recurring[kind] = {
            "last_succeeded_at": _isoformat(row["last_run"]),
            "next_due_at": _isoformat(row["next_due"]),
            "scheduled": row["next_due"] is not None,
        }

    return {
        "shopify_configured": settings.shopify_configured,
        "webhooks_configured": bool(settings.shopify_webhook_secret),
        # §11.2. Blank blocks every approval, deliberately - a default would
        # silently make eight months of already-settled orders approvable.
        # Reported here so "did the variable land?" is a fact rather than a
        # guess about a deploy.
        "go_live_month": settings.go_live_month or None,
        # ADR 0026 puts the trigger for revisiting proof storage at 200 MB,
        # which is only a trigger if somebody can see the number.
        "proof_stored_bytes": db.execute(
            text("SELECT coalesce(sum(size_bytes), 0) FROM proof_file")
        ).scalar()
        or 0,
        "payroll_can_be_approved": bool(settings.go_live_month),
        "orders_indexed": db.execute(text("SELECT count(*) FROM order_index")).scalar()
        or 0,
        "last_order_synced_at": _isoformat(
            db.execute(text("SELECT max(last_synced_at) FROM order_index")).scalar()
        ),
        "last_event_received_at": _isoformat(
            db.execute(text("SELECT max(received_at) FROM integration_event")).scalar()
        ),
        "jobs": {
            "pending": jobs.get(JobStatus.PENDING, 0),
            "running": jobs.get(JobStatus.RUNNING, 0),
            "succeeded": jobs.get(JobStatus.SUCCEEDED, 0),
            "failed": jobs.get(JobStatus.FAILED, 0),
        },
        "recurring": recurring,
    }


@router.get("/failed-jobs")
def failed_jobs(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Work that did not happen, and will not without someone acting."""
    rows = (
        db.execute(
            text(
                "SELECT id, kind, payload, attempts, last_error, created_at, finished_at "
                "FROM background_job WHERE status = 'failed' "
                "ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 100"
            )
        )
        .mappings()
        .all()
    )
    return {
        "jobs": [
            {
                "id": row["id"],
                "kind": row["kind"],
                "payload": row["payload"],
                "attempts": row["attempts"],
                "last_error": row["last_error"],
                "created_at": _isoformat(row["created_at"]),
                "finished_at": _isoformat(row["finished_at"]),
            }
            for row in rows
        ]
    }


@router.get("/unregistered-codes")
def unregistered_codes(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Live discount codes whose sales are attributed to nobody.

    **Ownership is per month, so a code can be partly unregistered.** If
    NOUR10 was registered from September, April's NOUR10 orders still belong
    to no one - and those are the sales somebody needs to see. An order counts
    here when no affiliate owned its code *in the month that order was
    placed*.

    That also covers the case nobody thinks to look for: an affiliate left in
    June, her code kept being used in August, and those August sales are
    quietly going nowhere.

    ``unowned_months`` is included so whoever registers the code knows which
    month to start it from, rather than guessing and leaving a gap.
    """
    rows = (
        db.execute(
            text(
                """
                SELECT
                    used.code,
                    count(*) AS order_count,
                    min(used.placed_at) AS first_seen,
                    max(used.placed_at) AS last_seen,
                    array_agg(DISTINCT used.business_month
                              ORDER BY used.business_month) AS unowned_months
                FROM (
                    SELECT o.placed_at, o.business_month, upper(c.code) AS code
                    FROM order_index o,
                         unnest(o.discount_codes) AS c(code)
                ) AS used
                WHERE NOT EXISTS (
                    SELECT 1 FROM discount_code_period p
                    WHERE p.code = used.code
                      AND p.start_month <= used.business_month
                      AND (p.end_month IS NULL
                           OR p.end_month >= used.business_month)
                )
                GROUP BY used.code
                ORDER BY order_count DESC, used.code
                LIMIT 200
                """
            )
        )
        .mappings()
        .all()
    )
    return {
        "codes": [
            {
                "code": row["code"],
                "order_count": row["order_count"],
                "first_seen": _isoformat(row["first_seen"]),
                "last_seen": _isoformat(row["last_seen"]),
                "unowned_months": list(row["unowned_months"]),
            }
            for row in rows
        ]
    }


@router.post("/verify-code")
def verify_code(
    body: VerifyCodeBody,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_MANAGE)),
) -> dict:
    """Confirm a discount code exists in Shopify. The Phase 3 onboarding gate."""
    from app.services.shopify.sync import build_client

    try:
        return verify_discount_code(build_client(), body.code)
    except ShopifyMissingScope as exc:
        # Distinct from a general Shopify failure on purpose. Shopify was
        # reached and answered; the app simply has not been granted the scope.
        # Reporting that as "could not reach Shopify" would send someone
        # debugging the network instead of the app configuration.
        raise HTTPException(
            403,
            f"Shopify has not granted {REQUIRED_SCOPE}. Add it to the app's "
            f"configuration in the Shopify Dev Dashboard, then try again.",
        ) from exc
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc


@router.get("/shopify-scopes")
def shopify_scopes(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
) -> dict:
    """What Shopify actually grants this app.

    Exists because "is the scope granted?" is otherwise unanswerable without
    guessing. Editing the scope field in the Dev Dashboard only saves a draft:
    the change takes effect when a new app version is released and approved on
    the store, and an already-issued token never gains a scope retroactively.

    Forces a token exchange, so it is administrator-only and not something to
    poll. That is also the point - the answer reflects a *fresh* token rather
    than whatever was cached before the scope changed.
    """
    from app.services.shopify.sync import build_client

    try:
        client = build_client()
        # Forces the token exchange that populates the scope list. A missing
        # scope is the answer here, not an error - so it is swallowed, and the
        # same client is then asked what it holds.
        try:
            client.require_scope(REQUIRED_SCOPE)
        except ShopifyMissingScope:
            pass
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc

    return {
        "granted": sorted(client.granted_scopes()),
        "missing": sorted(client.missing_scopes()),
        "required": sorted(REQUIRED_SCOPES),
        # A static token carries no scope list, so an empty granted set means
        # "Shopify did not say", not "nothing is granted".
        "reported_by_shopify": bool(client.granted_scopes()),
    }


@router.get("/order-facts")
def order_facts(
    sample_size: int = DEFAULT_SAMPLE,
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """What Shopify will actually tell us about delivery, returns and refunds.

    Phase 4 pays a model when her order is **delivered** (ADR 0012) and reads
    that from Shopify rather than from Bosta (ADR 0023). This is the instrument
    that turns "Shopify updates the status" into a number, the same way
    /shopify-scopes turned "is the scope granted?" into an answer.

    Read `delivery.signal` first. `absent` means no shipped order has ever
    reached a delivered status - which would mean nobody is ever paid, and
    every month calculating to zero would look exactly like a month with no
    sales. That is the failure this endpoint exists to catch **before** the
    code that depends on it is written.

    It also stays useful afterwards. Whatever writes delivery into Shopify sits
    outside this codebase and can stop without a symptom, so a month that comes
    out unexpectedly low is a reason to read this again.

    Administrator only, and not something to poll: it runs several sampled
    queries against Shopify.
    """
    from app.services.shopify.facts import probe_order_facts
    from app.services.shopify.sync import build_client

    # Free, and independent of Shopify being reachable: what the orders already
    # indexed actually carry. If the live probe fails, this still says whether
    # the platform has ever seen a delivery-shaped status.
    indexed = {
        "orders_indexed": db.scalar(text("SELECT count(*) FROM order_index")) or 0,
        "fulfillment_status": {
            row.value or "(null)": row.count
            for row in db.execute(
                text(
                    "SELECT fulfillment_status AS value, count(*) AS count "
                    "FROM order_index GROUP BY fulfillment_status "
                    "ORDER BY count DESC"
                )
            )
        },
        "financial_status": {
            row.value or "(null)": row.count
            for row in db.execute(
                text(
                    "SELECT financial_status AS value, count(*) AS count "
                    "FROM order_index GROUP BY financial_status "
                    "ORDER BY count DESC"
                )
            )
        },
        # The one that says whether a re-import actually landed. An order with
        # delivery_state NULL was indexed before the platform ever asked
        # Shopify about delivery, and it can never earn - so a shop full of
        # NULLs calculates every month to zero while looking like no sales.
        "delivery_state": {
            row.value or "(never asked)": row.count
            for row in db.execute(
                text(
                    "SELECT delivery_state AS value, count(*) AS count "
                    "FROM order_index GROUP BY delivery_state "
                    "ORDER BY count DESC"
                )
            )
        },
    }

    try:
        report = probe_order_facts(build_client(), sample_size=sample_size)
    except ShopifyNotConfigured as exc:
        raise HTTPException(503, str(exc)) from exc
    except ShopifyError as exc:
        raise HTTPException(502, f"Could not reach Shopify: {exc}") from exc

    return {**report, "already_indexed": indexed}


@router.post("/start-import")
def start_import(
    body: StartImportBody,
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Queue the historical order import.

    Admin only. It runs a server-side export over the whole shop's history and
    Shopify permits one bulk operation at a time, so this is not something to
    start casually or twice.

    Queues rather than runs: the export takes minutes, and an HTTP request is
    not the place to wait for it. Watch it under `jobs` in
    /api/operations/sync - not under `recurring`, which covers only work that
    repeats on a schedule.
    """
    job = enqueue(
        db,
        JobKind.BULK_IMPORT,
        {"since": body.since},
        dedupe_key=JobKind.BULK_IMPORT,
    )
    if job is None:
        raise HTTPException(
            409,
            "An import is already in progress. Wait for it to finish - Shopify "
            "runs one bulk operation per shop at a time.",
        )

    db.commit()
    return {
        "status": "queued",
        "job_id": job.id,
        "since": body.since,
        "queued_at": _isoformat(utcnow()),
    }


@router.get("/notifications")
def notification_health(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Emails owed, and emails that will never arrive.

    §16. Worth its own view because a failed notification is invisible from
    every other screen in the platform: the month is approved, the payment is
    recorded, the figures are all correct, and one model simply never heard.
    Nothing else here would ever show that.

    `configured` says whether mail could be sent at all. Without it a screen
    reporting "0 failed" would be truthfully describing a platform that has
    quietly sent nothing since it was deployed - which is the most likely way
    this goes wrong, and the least likely to be noticed.
    """
    from app.models.notifications import NotificationOutbox, NotificationState
    from app.services.notifications import failed as failed_notifications

    counts = dict(
        db.execute(
            select(NotificationOutbox.state, func.count())
            .group_by(NotificationOutbox.state)
        ).all()
    )

    return {
        "configured": settings.mail_configured,
        "from_address": settings.mail_from_address or None,
        "counts": {
            state: int(counts.get(state, 0))
            for state in sorted(
                {
                    NotificationState.PENDING,
                    NotificationState.SENT,
                    NotificationState.FAILED,
                    NotificationState.SKIPPED,
                }
            )
        },
        "failed": [
            {
                "id": row.id,
                "event": row.event,
                # The address is shown: knowing *which* model never heard is
                # the entire point, and it is an address the maintainer already
                # has. The payload is not - an invitation token would be in it
                # if the send failed before it was erased.
                "recipient_email": row.recipient_email,
                "subject_ref": row.subject_ref,
                "attempts": row.attempts,
                "last_error": row.last_error,
                "created_at": _isoformat(row.created_at),
            }
            for row in failed_notifications(db)
        ],
    }


#: §16's bottom two rows, and the rule that decides whether each one appears.
#:
#: **A warning that is always on is one nobody reads.** Every item here is
#: conditional on something being genuinely true and genuinely actionable, and
#: the whole list is empty on a healthy platform - which is what makes a
#: non-empty one worth looking at.
#:
#: Two severities, and they mean different things. `blocking` stops money
#: moving and somebody has to act before month end. `attention` is a thing
#: going wrong quietly that nobody would otherwise meet until it mattered.
BLOCKING = "blocking"
ATTENTION = "attention"

#: §16. The payroll reminder, on the 5th unless somebody changes it.
PAYROLL_REMINDER_DAY = 5

#: How long a sync can be silent before it is worth saying so. Webhooks arrive
#: within seconds of an order, and the reconciliation sweep runs every half
#: hour, so a day of silence is either a very quiet shop or a broken pipe -
#: and the two look identical from here, which is exactly why it is reported
#: rather than judged.
STALE_SYNC_HOURS = 24


@router.get("/attention")
def attention(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Everything a maintainer should not have to go looking for.

    §16's in-platform notifications, on the screen somebody lands on.

    **One line each.** The first version explained itself at length - three
    sentences per item, on a panel meant to be scanned in two seconds - and the
    business's verdict on reading it was *"this is too much and as an admin I
    don't need all of this. Just one liners."*

    That is the right instinct and it costs nothing, because the explanation
    was never the useful part. What a maintainer needs from this panel is
    **what is wrong, how many, and where to go.** `where` carries the last one,
    so the panel points rather than lectures.

    Months are written out. `2026-07` on a screen is a string somebody has to
    decode; *July 2026* is a month.
    """
    from app.models.notifications import NotificationOutbox, NotificationState
    from app.services.payroll import months_left_reopened, working_month

    items: list[dict] = []

    def add(key: str, severity: str, text: str, where: str) -> None:
        items.append(
            {"key": key, "severity": severity, "text": text, "where": where}
        )

    # -- The one that stops everything ---------------------------------------
    if not settings.go_live_month:
        add(
            "go_live_month_unset",
            BLOCKING,
            "No go-live month is set, so nothing can be approved.",
            "/settings",
        )

    # -- Mail ----------------------------------------------------------------
    #
    # The most likely thing to be silently wrong, and the least likely to be
    # noticed: nothing errors, people simply never hear.
    if not settings.mail_configured:
        add("mail_not_configured", ATTENTION, "No email is being sent.", "/settings")

    failed_mail = db.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.state == NotificationState.FAILED)
    )
    if failed_mail:
        add(
            "notifications_failed",
            ATTENTION,
            f"{failed_mail} email{_s(failed_mail)} did not arrive.",
            "/settings",
        )

    # -- Work that did not happen --------------------------------------------
    failed_jobs = db.execute(
        text("SELECT count(*) FROM background_job WHERE status = 'failed'")
    ).scalar()
    if failed_jobs:
        # "Background job" meant nothing to the person reading it. Named by
        # what it is *for* instead: the work that keeps order data current.
        add(
            "failed_jobs",
            ATTENTION,
            f"{failed_jobs} piece{_s(failed_jobs)} of order syncing failed.",
            "/settings",
        )

    # -- Orders nobody owns --------------------------------------------------
    unowned = db.execute(
        text(
            """
            SELECT count(DISTINCT upper(c.code))
            FROM order_index o, unnest(o.discount_codes) AS c(code)
            WHERE NOT EXISTS (
                SELECT 1 FROM discount_code_period p
                WHERE upper(p.code) = upper(c.code)
                  AND p.start_month <= o.business_month
                  AND (p.end_month IS NULL OR p.end_month >= o.business_month)
            )
            """
        )
    ).scalar()
    if unowned:
        add(
            "unregistered_codes",
            ATTENTION,
            f"{unowned} discount code{_s(unowned)} on orders belong{'s' if unowned == 1 else ''} to no model.",
            "/settings",
        )

    # -- Orders two models both claim ----------------------------------------
    held = db.execute(
        text(
            """
            SELECT count(*) FROM order_index o
            WHERE (
                SELECT count(DISTINCT p.affiliate_id)
                FROM unnest(o.discount_codes) AS c(code)
                JOIN discount_code_period p
                  ON upper(p.code) = upper(c.code)
                 AND p.start_month <= o.business_month
                 AND (p.end_month IS NULL OR p.end_month >= o.business_month)
            ) > 1
            """
        )
    ).scalar()
    if held:
        add(
            "orders_held",
            BLOCKING,
            f"{held} order{_s(held)} carry two models' codes and need a decision.",
            "/orders",
        )

    # -- Reopened and forgotten ----------------------------------------------
    #
    # §11.5, and the dangerous state is not reopening - it is forgetting.
    stuck = months_left_reopened(db)
    if stuck:
        months = sorted({row.month for row in stuck})
        add(
            "months_left_reopened",
            BLOCKING,
            f"{_month_words(months[0])} was reopened and never agreed again."
            if len(months) == 1
            else f"{len(months)} months were reopened and never agreed again.",
            "/payroll",
        )

    # -- The reminder --------------------------------------------------------
    today = utcnow()
    if today.day >= PAYROLL_REMINDER_DAY:
        previous = _previous_month(working_month())
        unapproved = db.execute(
            text(
                "SELECT count(*) FROM affiliate_profile a "
                "WHERE a.status = 'active' AND a.account_kind <> 'house' "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM payroll_month m WHERE m.affiliate_id = a.id "
                "  AND m.month = :month AND m.calculation_state = 'approved')"
            ),
            {"month": previous},
        ).scalar()
        if unapproved:
            add(
                "payroll_due",
                ATTENTION,
                f"{unapproved} model{_s(unapproved)} still unapproved for "
                f"{_month_words(previous)}.",
                "/payroll",
            )

    return {
        "items": items,
        "blocking": sum(1 for item in items if item["severity"] == BLOCKING),
    }


def _s(count: int) -> str:
    return "" if count == 1 else "s"


def _month_words(month: str) -> str:
    """`2026-07` -> `July 2026`. A month, not a string to decode."""
    names = (
        "January February March April May June July August September October "
        "November December"
    ).split()
    year, _, index = month.partition("-")
    try:
        return f"{names[int(index) - 1]} {year}"
    except (ValueError, IndexError):
        return month


def _previous_month(month: str) -> str:
    year, _, index = month.partition("-")
    year, index = int(year), int(index)
    return f"{year - 1}-12" if index == 1 else f"{year}-{index - 1:02d}"
