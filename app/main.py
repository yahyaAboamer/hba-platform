"""HBA Platform — FastAPI application entry point.

One service serves both the API and the built frontend. That keeps hosting to
a single deployable, which is what holds the running cost inside budget.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, health
from app.config import settings

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
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
