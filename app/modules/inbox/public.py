"""What other departments may use from Inbox (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from app.modules.inbox.services.confirmations import latest_for_orders as confirmations_for_orders
from app.modules.inbox.today import look as today_look

__all__ = ["confirmations_for_orders", "today_look"]
