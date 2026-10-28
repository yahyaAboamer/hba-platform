"""Model registry. Every model module must be imported here for Alembic autogenerate."""

from app.modules.affiliates.models import (  # noqa: F401
    affiliates,
    attributed_orders,
    codes,
    compensation,
    payouts,
    payments,
    payroll,
    promotions,
    shipments,
    targets,
)
from app.modules.inbox import models as inbox  # noqa: F401
from app.modules.operations import models as order_ops  # noqa: F401
from app.shared.models import (  # noqa: F401
    audit,
    catalogue,
    identity,
    integration,
    notifications,
    orders,
)
