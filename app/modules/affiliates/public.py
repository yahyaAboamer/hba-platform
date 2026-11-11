"""What other departments may use from Affiliates (ADR 0065).

The only part of this department another one may import: the import check
(pyproject.toml, `[tool.importlinter]`) refuses its api, models and services.
Empty on the day of the move; the crossings that existed then are listed in
that check, and each one that is untangled comes through here.
"""

from app.modules.affiliates.services.payouts import extract_instapay_link, normalise_instapay_address
from app.modules.affiliates.today import look as today_look

# Returns (ADR 0079) checks an InstaPay refund address the way Payments does.
__all__ = ["extract_instapay_link", "normalise_instapay_address", "today_look"]
