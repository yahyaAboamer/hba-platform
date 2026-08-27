"""The business audit trail, over HTTP. Read-only.

§16: who did what, when, and why where a reason was required. Nothing here
writes - `record_audit` is called from inside the action that changed
something, in the same transaction as the change itself, and that remains the
only way an event is created.

Every value returned here was already masked at write time
(`app/services/audit.py`, `mask_sensitive`), so nothing extra happens on the
way out. Masking twice would risk masking a value that was already a mask.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import UserAccount
from app.services.audit import recent_events

router = APIRouter(prefix="/api/audit")

MAX_LIMIT = 200


@router.get("")
def recent(
    subject: str | None = None,
    limit: int = 50,
    _actor: UserAccount = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The most recent events, optionally narrowed to one subject.

    `subject` matches a substring - `affiliate:12`, or just `12` - because
    that is what a person has in hand, not a structured query they compose.
    """
    capped = max(1, min(limit, MAX_LIMIT))
    events = recent_events(db, limit=capped, subject_contains=subject)
    return {
        "events": [
            {
                "id": event.id,
                "action": event.action,
                "subject": event.subject,
                "actor_email": event.actor_email,
                "reason": event.reason,
                "created_at": event.created_at.isoformat(),
                "before": event.before_json,
                "after": event.after_json,
            }
            for event in events
        ]
    }
