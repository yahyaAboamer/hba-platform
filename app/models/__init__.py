"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import audit, identity, orders  # noqa: F401
