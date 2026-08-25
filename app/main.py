"""HBA Platform — FastAPI application entry point.

One service serves both the API and the built frontend. That keeps hosting to
a single deployable, which is what holds the running cost inside budget.
"""

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import affiliates, auth, earnings, health, operations, webhooks
from app.config import settings
from app.worker import worker_loop

# Imported for the side effect of registering its job handlers with the
# worker. Without this the worker leases shopify_sync_order jobs, finds no
# handler, and fails every one of them.
from app.services import reconcile as _reconcile  # noqa: F401  (registers handlers)
from app.services.commission import backfill as _backfill  # noqa: F401  (registers handlers)
from app.services.shopify import bulk as _shopify_bulk  # noqa: F401  (registers handlers)
from app.services.shopify import sync as _shopify_sync  # noqa: F401  (registers handlers)

WEB_DIR = Path(__file__).resolve().parent / "web"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the background worker alongside the API.

    Cancelled on shutdown. A job in flight when that happens is not lost: its
    lease expires and the next worker to start picks it up, which is exactly
    the case leases exist for.
    """
    task = None
    if settings.worker_enabled:
        task = asyncio.create_task(worker_loop())
    else:
        logger.info("background worker disabled by configuration")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    # Authenticated responses must never sit in a shared or browser cache.
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# API routes are registered before the catch-all below, so they always win.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(operations.router)
app.include_router(affiliates.router)
app.include_router(earnings.router)


if (WEB_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str) -> FileResponse:
        """Serve the single-page app for any route the API did not claim.

        Unmatched /api/ paths are re-raised as 404 rather than answered with
        the HTML shell. Otherwise a typo in a frontend fetch would receive a
        200 and a page of HTML, and the mistake would surface much later as a
        confusing parse error instead of an obvious missing endpoint.
        """
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found")
        return FileResponse(WEB_DIR / "index.html")
