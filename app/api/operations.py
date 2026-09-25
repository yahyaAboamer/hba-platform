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
from app.core.businesstime import business_month, parse_month, utcnow
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
from app.services.recipients import unmatched
from app.services.shopify.catalogue import catalogue_state
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
        # The connection in use - saved from Settings, or the environment's.
        "shopify_configured": _shopify_effective(db).source is not None,
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
        # Settings → Shopify's *Refresh now* card. Only a finished sweep moves
        # `last_success_at`; a failure keeps it.
        "refresh": _refresh_state(db),
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
    June, their code kept being used in August, and those August sales are
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

    Phase 4 pays a model when their order is **delivered** (ADR 0012) and reads
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


@router.post("/sync-catalogue")
def sync_catalogue_route(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Queue a walk of the shop's products, variants and images.

    **Safe to run against the shared shop**, unlike the historical order
    import. That one is a bulk operation and Shopify permits one per shop at a
    time, which is why the old docs say never to start it from staging. This is
    ordinary paginated reads: it costs rate limit and nothing else, and running
    it twice is an upsert.

    Queued rather than run. A catalogue is not a page, and an HTTP request is
    not the place to wait for the walk. Watch it under `jobs` in
    /api/operations/sync.

    Deduped, so a second click while one is running joins the first rather than
    starting a second walk over the same shop.
    """
    job = enqueue(
        db,
        JobKind.SYNC_CATALOGUE,
        {},
        dedupe_key=JobKind.SYNC_CATALOGUE,
    )
    if job is None:
        raise HTTPException(
            409, "A catalogue sync is already running. Wait for it to finish."
        )

    db.commit()
    return {
        "status": "queued",
        "job_id": job.id,
        "queued_at": _isoformat(utcnow()),
    }


@router.post("/refresh")
def refresh_route(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """*Refresh now*: bring the reconciliation sweep forward.

    Reads orders Shopify changed in the last 48 hours, exactly as the
    half-hourly sweep does - it is that sweep, not a second mechanism. Nothing
    is written to Shopify.

    **Accepted is not refreshed.** The answer is 202 and the sweep's state;
    *last successful refresh* moves only when the sweep finishes. A click while
    one is queued or running starts nothing new.
    """
    from app.services.shopify.refresh import NotConnected, request_refresh

    try:
        requested = request_refresh(db)
    except NotConnected:
        raise HTTPException(
            409, "There is no Shopify connection to refresh from."
        ) from None
    db.commit()
    return {
        "accepted": True,
        "job_id": requested.job_id,
        "joined_running": requested.state == "running",
        "refresh": _refresh_state(db),
    }


def _refresh_state(db) -> dict:
    from app.services.shopify.refresh import refresh_state

    return refresh_state(db)


@router.get("/catalogue")
def catalogue_route(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """What the catalogue holds, and when HBA last heard about it.

    The freshness half matters more than the counts. A catalogue nobody has
    synced for a fortnight looks identical to a fresh one until something says
    otherwise, and *"as of"* is the difference between a stale screen and a
    lying one.
    """
    return catalogue_state(db)


@router.post("/scan-recipients")
def scan_recipients_route(
    body: StartImportBody,
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Queue the walk that works out which parcels went to which model.

    **Safe against the shared shop.** Ordinary paginated reads, like the
    catalogue and unlike the bulk import - it costs rate limit and nothing
    else, and every write it makes is an upsert keyed by order.

    Resumable: each run does a few pages, commits them, and queues the next
    slice with its cursor. A backfill of thousands of orders that must finish
    in one go is a backfill that never finishes.

    Reuses the import's date body, because it answers the same question -
    *from when* - and W05's answer is January 2026.
    """
    job = enqueue(
        db,
        JobKind.SCAN_RECIPIENTS,
        {"since": body.since},
        dedupe_key=JobKind.SCAN_RECIPIENTS,
    )
    if job is None:
        raise HTTPException(
            409, "A recipient scan is already running. Wait for it to finish."
        )

    db.commit()
    return {
        "status": "queued",
        "job_id": job.id,
        "since": body.since,
        "queued_at": _isoformat(utcnow()),
    }


@router.get("/unmatched-parcels")
def unmatched_parcels_route(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Parcels the platform looked at and could not attach to a model.

    W12's bounded staff path, and deliberately **not** a work queue. Most
    unmatched orders are ordinary customers and always will be; presenting
    every one as a backlog would invite somebody to clear a thousand rows that
    were never HBA's parcels. Only genuine ambiguities and near-misses are
    listed - an order with no phone at all is recorded and not shown.
    """
    return unmatched(db)


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
    from app.models.notifications import (
        NoticeMute,
        NotificationOutbox,
        NotificationState,
    )
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

#: Notices that may never be muted. A10 allows somebody to stop seeing a
#: notice; it does not allow them to stop seeing a stop sign, and every one of
#: these means the month cannot close.
UNMUTABLE = frozenset({"go_live_month_unset"})

#: §16. The payroll reminder, on the 5th unless somebody changes it.
PAYROLL_REMINDER_DAY = 5

#: How long a sync can be silent before it is worth saying so. Webhooks arrive
#: within seconds of an order, and the reconciliation sweep runs every half
#: hour, so a day of silence is either a very quiet shop or a broken pipe -
#: and the two look identical from here, which is exactly why it is reported
#: rather than judged.
STALE_SYNC_HOURS = 24


@router.get("/counts")
def counts(
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The numbers beside the sidebar's section names.

    The approved export puts a count on *Models* and on *Payments*, so the
    owner can see where work is waiting without opening each section to find
    out.

    **Payments counts rows, not money.** An earlier note here refused to serve
    it at all, on the grounds that a second implementation of *how much is
    still to send* would be a second answer waiting to disagree with the
    Payments screen in front of the one person guaranteed to notice. That
    reasoning is right and it does not apply: the export's badge is the size
    of the *Awaiting approval* filter - how many models still need a look -
    and the count below is produced by calling the same `balance_for` the
    screen itself calls, on the same month, so there is one implementation and
    it is the screen's.
    """
    from app.models.affiliates import AffiliateProfile
    from app.services.payments import balance_for, on_the_desk

    month = business_month(utcnow())
    # **The same people the desk lists**, through the same function. Counting
    # every payable affiliate here instead put 22 on the badge above a screen
    # showing 19, which is the disagreement the paragraph above predicted.
    awaiting = sum(
        1
        for affiliate in on_the_desk(db, month)
        if balance_for(db, affiliate, month)["state"] == "not_approved"
    )

    return {
        "models_awaiting_approval": db.scalar(
            select(func.count())
            .select_from(AffiliateProfile)
            .where(AffiliateProfile.status == "pending")
        )
        or 0,
        "payments_awaiting_approval": awaiting,
    }


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
    from app.models.notifications import (
        NoticeMute,
        NotificationOutbox,
        NotificationState,
    )
    from app.services.payroll import months_left_reopened, working_month

    items: list[dict] = []

    # **A blocking notice cannot be muted**, and that is not an oversight.
    # A10 lets somebody stop seeing a notice; it does not let them stop seeing
    # a stop sign. "Nothing can be approved" is not noise to be turned off -
    # it is the reason the month will not close, and silencing it would make
    # the platform quietly useless rather than loudly stuck.
    muted = {
        row.key
        for row in db.scalars(select(NoticeMute))
        if row.key not in UNMUTABLE
    }

    def add(
        key: str,
        severity: str,
        text: str,
        where: str,
        action: str,
        detail: str | None = None,
    ) -> None:
        """One notice, and **the words on its own button**.

        The approved export gives every notice a named action — *Open
        applications*, *Open correction*, *Open sync* — so the column can be
        read down the buttons. The browser used to derive the verb from the
        route, which produced *Open settings* four times over for four
        unrelated problems.

        `detail` is the export's second line, and it is **one line**: the
        business's verdict on the first draft was *"this is too much and as an
        admin I don't need all of this. Just one liners."* A short second line
        naming the thing - which model, which order - is what makes the notice
        actionable without opening it. A paragraph is not.
        """
        items.append(
            {
                "key": key,
                "severity": severity,
                "text": text,
                "detail": detail,
                "where": where,
                "action": action,
            }
        )

    # -- The one that stops everything ---------------------------------------
    if not settings.go_live_month:
        add(
            "go_live_month_unset",
            BLOCKING,
            "No go-live month is set, so nothing can be approved",
            "/settings",
            "Open settings",
            "Until it is set, no month can be agreed and no model can be paid.",
        )

    # -- People waiting to be let in -----------------------------------------
    #
    # **The export's first notice, and the app had no such notice at all.**
    # `2 applications awaiting review / Submitted through the invitation link.
    # / Open applications`. Somebody who applied through an invitation link is
    # waiting on a person, and nothing else on Home said so: the roster's
    # *Applications 2* chip is only seen by somebody who already went looking.
    #
    # ATTENTION rather than BLOCKING. Nobody is owed money and no month is
    # held up; a person is waiting, which is a different kind of urgent.
    waiting = db.execute(
        text(
            "SELECT count(*) FROM affiliate_profile "
            "WHERE status = 'pending' AND account_kind <> 'house'"
        )
    ).scalar()
    if waiting:
        add(
            "applications_waiting",
            ATTENTION,
            f"{waiting} application{_s(waiting)} awaiting review",
            "/affiliates?segment=applications",
            "Open applications",
            "Submitted through the invitation link.",
        )

    # -- Agreed months that have changed -----------------------------------
    #
    # **The export's second notice**: *Late failed order needs a decision /
    # Yahya Aboamer · order #29741 failed after September was approved. /
    # Open correction*. One per open correction (05C), from the same
    # `open_corrections` the payments desk used to list, across every payable
    # model including departed ones - so a correction is on the screen
    # everybody lands on until somebody carries or absorbs it.
    #
    # Worded from what actually happened: *failed* only where every order the
    # agreement counted and has lost was a courier's failure (`order_status`);
    # a cancellation or a refund is never called a failed delivery.
    #
    # BLOCKING, for the export's red: money may already have been advanced.
    from app.services.affiliates import list_affiliates
    from app.services.corrections import open_corrections
    from app.services.portal import changed_after_approval

    this_year = working_month()[:4]
    for affiliate in list_affiliates(db, include_archived=True):
        if not affiliate.is_payable:
            continue
        for correction in open_corrections(db, affiliate):
            month = correction.month
            when = (
                _month_words(month).split(" ")[0]
                if month[:4] == this_year
                else _month_words(month)
            )
            lost = changed_after_approval(db, affiliate, month)
            if lost and all(status == "failed" for _, status in lost):
                numbers = ", ".join(number for number, _ in lost)
                one = len(lost) == 1
                title = f"Late failed order{'' if one else 's'} need{'s' if one else ''} a decision"
                detail = (
                    f"{affiliate.name} · order{'' if one else 's'} {numbers} "
                    f"failed after {when} was approved."
                )
            else:
                title = "Agreed month changed and needs a decision"
                detail = f"{affiliate.name} · {when} changed after it was approved."
            add(
                f"correction:{affiliate.id}:{month}",
                BLOCKING,
                title,
                # The month's own correction, where it is carried or absorbed.
                f"/payments/{month}/{affiliate.id}/correction",
                "Open correction",
                detail,
            )

    # -- Mail ----------------------------------------------------------------
    #
    # The most likely thing to be silently wrong, and the least likely to be
    # noticed: nothing errors, people simply never hear.
    if not settings.mail_configured:
        add(
            "mail_not_configured",
            ATTENTION,
            "No email is being sent",
            "/settings",
            "Open settings",
            "Invitations and receipts are written and never delivered.",
        )

    failed_mail = db.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .where(NotificationOutbox.state == NotificationState.FAILED)
    )
    if failed_mail:
        add(
            "notifications_failed",
            ATTENTION,
            f"{failed_mail} email{_s(failed_mail)} did not arrive",
            "/settings",
            "Open settings",
            "They can be sent again without writing them a second time.",
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
            f"{failed_jobs} piece{_s(failed_jobs)} of order syncing failed",
            "/settings",
            "Open sync",
            "Sales in those orders are not attributed to anybody yet.",
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
            f"{unowned} discount code{_s(unowned)} on orders belong{'s' if unowned == 1 else ''} to no model",
            "/settings",
            "Open codes",
            "Whoever earned on them is not being credited.",
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
            f"{held} order{_s(held)} carry two models' codes and need a decision",
            "/orders",
            "Open orders",
            "Nobody is credited until somebody says which model it belongs to.",
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
            f"{_month_words(months[0])} was reopened and never agreed again"
            if len(months) == 1
            else f"{len(months)} months were reopened and never agreed again",
            "/payroll",
            "Open payroll",
            "A month left open is a month nobody is being paid for.",
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
                f"{_month_words(previous)}",
                "/payroll",
                "Open payroll",
                "The month cannot close while any model is still unapproved.",
            )

    return {
        # **Muted notices are removed here, not earlier.** Every one was still
        # computed, so muting cannot hide a problem from anything that counts
        # them - only from the panel.
        "items": [row for row in items if row["key"] not in muted],
        "blocking": sum(
            1
            for row in items
            if row["severity"] == BLOCKING and row["key"] not in muted
        ),
        # Listed, so a mute is reversible by somebody who did not set it and
        # cannot become a thing nobody remembers turning off. A10: muting does
        # not resolve anything, and a muted problem that is still true should
        # still be findable.
        "muted": [
            {**row, "muted": True} for row in items if row["key"] in muted
        ],
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


@router.post("/notifications/retry")
def retry_notifications(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Send everything that failed, again.

    **The case this exists for is a provider that was not working yet.** Brevo
    holds a new account for manual activation and answers every send with
    *"your account is not yet activated"* - a 403, which is correctly treated
    as permanent, because retrying a refusal four more times helps nobody.

    The consequence is that every notification queued before activation is
    dead. Approvals, invitations, payment notices: all owed, all marked failed,
    none of them ever going out - and no way to change that but a button.

    Which is also why this is deliberately **not** automatic. The reason a
    batch failed is usually a setting somebody has to fix first, and a queue
    that retried on its own would hide that by eventually succeeding. Somebody
    fixes the cause, then presses this.

    Idempotent, and safe on a healthy platform: with nothing failed it queues
    nothing.
    """
    from app.models.notifications import NotificationOutbox, NotificationState
    from app.services.jobs import enqueue
    from app.services.notifications import JOB_KIND

    failed = list(
        db.scalars(
            select(NotificationOutbox).where(
                NotificationOutbox.state == NotificationState.FAILED
            )
        )
    )

    for row in failed:
        row.state = NotificationState.PENDING
        # The count starts again: this is a fresh attempt at something that has
        # been fixed, not a continuation of the run that gave up.
        row.attempts = 0
        row.last_error = None
        enqueue(db, JOB_KIND, {"outbox_id": row.id})

    db.commit()
    return {"queued": len(failed)}


class MuteBody(BaseModel):
    key: str = Field(min_length=1, max_length=64)


@router.post("/notices/mute", status_code=201)
def mute_notice(
    body: MuteBody,
    actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Stop showing a notice on the panel. A10.

    **This resolves nothing.** The problem is still there and the notice is
    still true; muting only stops it appearing. That distinction is the rule,
    and it is why a mute is listed back rather than swallowed — a muted problem
    that is still real should stay findable by somebody who did not mute it.

    A **blocking** notice cannot be muted. A10 lets somebody stop seeing a
    notice; it does not let them stop seeing a stop sign, and every blocking
    one means the month will not close.
    """
    from app.models.notifications import NoticeMute

    if body.key in UNMUTABLE:
        raise HTTPException(
            400,
            "That one stops the month closing, so it cannot be turned off. "
            "Fixing it is what makes it go away.",
        )

    existing = db.get(NoticeMute, body.key)
    if existing is None:
        # Idempotent: muting twice is what a double-click looks like, and the
        # second should be the same answer rather than a constraint violation.
        db.add(NoticeMute(key=body.key, muted_by=actor.id))
        db.commit()
    return {"key": body.key, "muted": True}


@router.delete("/notices/mute/{key}")
def unmute_notice(
    key: str,
    _actor: UserAccount = Depends(require_permission(Permission.AFFILIATES_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """Show a notice again.

    Idempotent for the same reason muting is: asking for something that is
    already true is not an error.
    """
    from app.models.notifications import NoticeMute

    existing = db.get(NoticeMute, key)
    if existing is not None:
        db.delete(existing)
        db.commit()
    return {"key": key, "muted": False}


class ShopifyConnectionBody(BaseModel):
    """The export's form, in HBA's credentials (decision b; ADR 0015)."""

    shop_domain: str = Field(max_length=255)
    #: Blank keeps the saved one, as for the secret.
    client_id: str | None = Field(default=None, max_length=255)
    #: Blank keeps the saved secret: it is never sent to the browser, so an
    #: unchanged form arrives without it.
    client_secret: str | None = Field(default=None, max_length=512)


@router.get("/shopify-connection")
def shopify_connection(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """The connection in use, for Settings. **No secret, in any form.**"""
    from app.services.shopify.connection import describe

    return describe(db)


@router.put("/shopify-connection")
def update_shopify_connection(
    body: ShopifyConnectionBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Change the connection - only if the new one answers Shopify.

    Owner, decision b (25 September). A refusal leaves the connection in use
    exactly as it was, and says why in words safe to show; the secret is never
    echoed back, logged or audited.
    """
    from app.services.shopify.connection import ConnectionRefused, save

    try:
        found = save(
            db,
            shop_domain=body.shop_domain,
            client_id=body.client_id,
            client_secret=body.client_secret,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ConnectionRefused as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from None
    db.commit()
    return found


def _shopify_effective(db):
    """The connection in use (saved from Settings, or the environment's)."""
    from app.services.shopify.connection import effective

    return effective(db)
