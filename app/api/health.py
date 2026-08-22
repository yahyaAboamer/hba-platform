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
    ready_now = all(check.get("ok") for check in checks.values())
    return {"status": "ready" if ready_now else "not_ready", "checks": checks}
