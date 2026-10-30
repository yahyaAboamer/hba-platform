"""What other departments may use from Affiliates (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from app.modules.affiliates.today import look as today_look
from app.modules.affiliates.today import waiting

__all__ = ["today_look", "waiting"]
