"""Liveness and readiness probes."""

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.config import settings
from app.db import engine

router = APIRouter()


@router.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready(response: Response) -> dict:
    checks: dict = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # surfaced, never swallowed
        checks["database"] = {"ok": False, "error": type(exc).__name__}

    checks["configuration"] = {"ok": True, "environment": settings.app_env}

    # Reported, never enforced: the platform is healthy without Shopify, it
    # simply cannot sync. Surfacing it here means an operator sees a missing
    # credential immediately rather than inferring it from an empty order list.
    # webhooks_configured is separate from configured: the API credentials can
    # be perfectly good while the webhook secret is missing, in which case every
    # delivery is rejected with a 401 and orders quietly stop arriving.
    checks["shopify"] = {
        "ok": True,
        "configured": settings.shopify_configured,
        "webhooks_configured": bool(settings.shopify_webhook_secret),
    }
    ready_now = all(check.get("ok") for check in checks.values())

    # **The status code is the whole point of this endpoint.**
    #
    # Railway queries this path until it gets a 200 and only then routes
    # traffic to a new deployment - and it never asks again afterwards. So this
    # number is the single gate a broken deployment ever meets.
    #
    # It used to return 200 unconditionally, saying `"database": {"ok": false}`
    # in a body nothing reads. A deployment that could not reach its database
    # was therefore declared healthy and put in front of the models. It also
    # meant an outside probe could not tell a working platform from a broken
    # one, which is how a region migration went by unmeasured.
    response.status_code = 200 if ready_now else 503
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
