"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import (  # noqa: F401
    affiliates,
    audit,
    codes,
    identity,
    integration,
    orders,
)
