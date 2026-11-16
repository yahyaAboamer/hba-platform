"""The permission guards the production routes share, kept by name so a test
can find them. ``api`` re-exports them; ``suppliers_api`` imports them from
here (it cannot import ``api``, which includes it)."""

from fastapi import Request

from app.core.permissions import Permission
from app.modules.production.orders.services.files import MAX_BYTES
from app.shared.api.deps import require_permission

#: The router's guard: reading Production.
GUARD = require_permission(Permission.PRODUCTION_VIEW)
#: The QC manager's writes: stages, counts, deliveries, dates, files, a purchase's arrival.
EDIT = require_permission(Permission.PRODUCTION_EDIT)
#: The owner's: create, edit, sample, write-off, settle, cancel, reopen, settings,
#: and all the money of suppliers.
OWNER = require_permission(Permission.PRODUCTION_OWNER)
#: Managers and the owner: adding and editing suppliers and their sections.
SUPPLIERS = require_permission(Permission.PRODUCTION_SUPPLIERS)


def too_large(request: Request) -> bool:
    """Refused before reading: too large, or of no stated size. A body sent
    without `Content-Length` would otherwise be read whole before its size
    could be checked."""
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        return True
    return int(length) > MAX_BYTES + 1024 * 1024
