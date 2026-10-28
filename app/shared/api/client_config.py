"""What the browser needs to know before anybody signs in.

No sign-in, on purpose: the sign-in page itself must be able to report its own
errors. So this returns only what is public anyway - the browser's Sentry DSN
(which can submit errors, not read them), the environment's name and the
deployed commit, which the browser's reports carry regardless.

**A fixed contract** with `frontend/`: exactly these three keys, each a string
or null. With no frontend DSN all three are null, and the browser reports
nothing.
"""

from fastapi import APIRouter

from app.config import settings
from app.core.observability import environment_name, release_name

router = APIRouter()


@router.get("/api/client-config")
def client_config() -> dict:
    dsn = settings.sentry_frontend_dsn.strip() or None
    return {
        "sentry_dsn": dsn,
        "environment": environment_name(settings) if dsn else None,
        "release": release_name(settings) if dsn else None,
    }
