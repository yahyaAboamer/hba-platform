"""``GET /api/integrations``: whether each outside connection works, for the
owner (Phase 2, batch 2.3; Settings → Integrations).

Only the owner (``settings.manage``) may read it: it names every connection
the business runs on and why each is broken, and fixing one is the owner's.

The answer is built in ``app.shared.services.integrations`` from what the
departments already record - no outside call - and departments are reached
only through their ``public`` (the import check in ``pyproject.toml``).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.permissions import Permission
from app.db import get_session
from app.shared.api.deps import require_permission
from app.shared.models.identity import UserAccount
from app.shared.services.integrations import connections

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("")
def integrations(
    _owner: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    """Every connection, in the frame's order, with its state and why."""
    return connections(db, utcnow())
