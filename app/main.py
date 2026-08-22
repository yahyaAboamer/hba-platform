"""HBA Platform — FastAPI application entry point."""

from fastapi import FastAPI

from app.api import health
from app.config import settings

app = FastAPI(
    title="HBA Platform",
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.include_router(health.router)
