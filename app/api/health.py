"""Liveness and readiness probes."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db import engine

router = APIRouter()


@router.get("/api/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/api/health/ready")
def ready() -> dict:
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
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
