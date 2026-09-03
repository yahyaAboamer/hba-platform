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

from app.api import (
    affiliate_self,
    affiliates,
    applications,
    audit,
    auth,
    earnings,
    health,
    operations,
    orders,
    payments,
    payroll,
    policy,
    staff,
    targets,
    webhooks,
)
from app.config import settings
from app.worker import worker_loop

# Imported for the side effect of registering its job handlers with the
# worker. Without this the worker leases shopify_sync_order jobs, finds no
# handler, and fails every one of them.
from app.services import notifications as _notifications  # noqa: F401  (registers handlers)
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
    elif request.url.path.startswith("/assets/"):
        # **Content-hashed, so immutable.** Vite puts a hash of the contents in
        # every asset filename, which means a given URL can never mean
        # something different - a change produces a new name.
        #
        # Without this the browser had an ETag and no freshness, so it
        # revalidated every file on every page load: five or six extra round
        # trips before anything could render, and each round trip to this host
        # from Cairo costs about 210ms. The files were in the cache the whole
        # time; the browser just kept asking whether they were still good.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path == "/" or not request.url.path.startswith("/api/"):
        # The shell, on the other hand, must be checked every time - it is what
        # names the current asset hashes, so caching it is how somebody keeps
        # running last week's deploy.
        response.headers["Cache-Control"] = "no-cache"
    return response


# API routes are registered before the catch-all below, so they always win.
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(operations.router)
app.include_router(affiliates.router)
app.include_router(applications.router)
app.include_router(affiliate_self.router)
app.include_router(earnings.router)
app.include_router(targets.router)
app.include_router(orders.router)
app.include_router(staff.router)
app.include_router(audit.router)
app.include_router(payroll.router)
app.include_router(payments.router)
app.include_router(policy.router)


if (WEB_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    @app.get("/hba-logo.png", include_in_schema=False)
    def brand_logo() -> FileResponse:
        """The mark at the top of every email.

        **A route of its own, on purpose.** Emails cannot embed an image
        reliably - most clients refuse a data URI - so they reference a URL,
        and an email sent today is opened next year. That rules out
        `/assets/`, where Vite renames every file with a content hash on each
        build: the logo in a September email would 404 by October.

        This path never changes, so neither does the picture in anybody's
        inbox. It sits above the SPA fallback because that fallback answers
        every unclaimed path with the HTML shell, which would otherwise send
        a page of markup where a PNG was asked for.
        """
        return FileResponse(WEB_DIR / "hba-logo.png", media_type="image/png")

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
