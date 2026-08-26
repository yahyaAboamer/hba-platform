"""Operational visibility.

A failed background job that exists only in a log file is invisible. These
endpoints put sync state, failures, and unattributed codes where the maintainer
will actually see them - the point being to learn about a sync failure from the
platform rather than from a confused affiliate.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
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
