"""HBA Platform — FastAPI application entry point.

One service serves both the API and the built frontend. That keeps hosting to
a single deployable, which is what holds the running cost inside budget.
"""

import asyncio
import contextlib
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.modules.affiliates.api import (
    affiliate_self,
    affiliates,
    applications,
    earnings,
    operations,
    orders,
    payments,
    payroll,
    policy,
    portal_preview,
    products,
    targets,
)
from app.modules.inbox import api as inbox
from app.modules.operations import api as order_ops
from app.shared.api import (
    audit,
    auth,
    client_config,
    health,
    staff,
    webhooks,
)
from app.core.observability import init_observability
from app.worker import worker_loop

# Imported for the side effect of registering its job handlers with the
# worker. Without this the worker leases shopify_sync_order jobs, finds no
# handler, and fails every one of them.
from app.shared.services import notifications as _notifications  # noqa: F401  (registers handlers)
from app.shared.services import reconcile as _reconcile  # noqa: F401  (registers handlers)
from app.shared.services import staff_prefs as _staff_prefs  # noqa: F401  (registers handlers)
from app.modules.affiliates.services.commission import backfill as _backfill  # noqa: F401  (registers handlers)
from app.modules.inbox.services import confirmations as _inbox_confirmations  # noqa: F401  (registers handlers)
from app.modules.inbox.services import events as _inbox_events  # noqa: F401  (registers handlers)
from app.modules.inbox.services import media as _inbox_media  # noqa: F401  (registers handlers)
from app.modules.inbox.services import outbound as _inbox_outbound  # noqa: F401  (registers handlers)
from app.modules.inbox.services import payments as _inbox_payments  # noqa: F401  (registers handlers)
from app.modules.inbox.services import tags as _inbox_tags  # noqa: F401  (registers handlers)
from app.modules.operations.services import bosta as _order_ops_bosta  # noqa: F401  (registers handlers)
from app.modules.operations.services import estebdal as _order_ops_estebdal  # noqa: F401  (registers handlers)
from app.modules.operations.services import shopify as _order_ops_shopify  # noqa: F401  (registers handlers)
from app.shared.services.shopify import bulk as _shopify_bulk  # noqa: F401  (registers handlers)
from app.shared.services.shopify import sync as _shopify_sync  # noqa: F401  (registers handlers)

WEB_DIR = Path(__file__).resolve().parent / "web"

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the background worker alongside the API.

    Cancelled on shutdown. A job in flight when that happens is not lost: its
    lease expires and the next worker to start picks it up, which is exactly
    the case leases exist for.
    """
    tasks: list[asyncio.Task] = []
    if settings.worker_enabled:
        # Two lanes (app.worker.LANES): Operations' reads apart from the rest.
        tasks = [
            asyncio.create_task(worker_loop(lane)) for lane in ("main", "operations", "inbox")
        ]
    else:
        logger.info("background worker disabled by configuration")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


# Before the app is built: the FastAPI integration wraps route handlers as they
# are registered. Does nothing at all without SENTRY_DSN.
init_observability(settings)

app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)


#: The frame inside *View her portal* (ADR 0064, `frontend/src/departments/affiliates/PortalPreview.tsx`).
#: At `/affiliates/models/<id>/portal/frame` since ADR 0068; the old
#: `/affiliates/<id>/portal/frame` still matches, for bookmarks.
_PREVIEW_FRAME = re.compile(r"^/affiliates/(?:models/)?\d+/portal/frame/?$")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if _PREVIEW_FRAME.match(request.url.path):
        # ADR 0064: the one page the platform frames itself - a model's portal
        # inside *View her portal*. Our own pages may frame it; no other site
        # may, so the reason for DENY (clickjacking) still holds.
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    else:
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
app.include_router(client_config.router)
app.include_router(auth.router)
app.include_router(webhooks.router)
app.include_router(operations.router)
app.include_router(order_ops.router)
app.include_router(order_ops.frame_router)
app.include_router(inbox.router)
app.include_router(affiliates.router)
app.include_router(applications.router)
app.include_router(affiliate_self.router)
app.include_router(portal_preview.router)
app.include_router(earnings.router)
app.include_router(targets.router)
app.include_router(orders.router)
app.include_router(staff.router)
app.include_router(audit.router)
app.include_router(payroll.router)
app.include_router(payments.router)
app.include_router(products.router)
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
