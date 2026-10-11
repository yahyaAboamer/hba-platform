"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.models import (  # noqa: F401
    affiliates,
    attributed_orders,
    audit,
    catalogue,
    codes,
    compensation,
    identity,
    inbox,
    integration,
    notifications,
    order_ops,
    orders,
    payouts,
    payments,
    payroll,
    promotions,
    shipments,
    targets,
)
