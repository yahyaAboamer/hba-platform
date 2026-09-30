"""The business audit trail, over HTTP. Read-only.

§16: who did what, when, and why where a reason was required. Nothing here
writes - `record_audit` is called from inside the action that changed
something, in the same transaction as the change itself, and that remains the
only way an event is created.

Every value returned here was already masked at write time
(`app/services/audit.py`, `mask_sensitive`), so nothing extra happens on the
way out. Masking twice would risk masking a value that was already a mask.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.models.affiliates import AffiliateProfile
from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.services.audit import KINDS, kind_of, recent_events
from app.services.audit_words import describe

router = APIRouter(prefix="/api/audit")

MAX_LIMIT = 200


@router.get("")
def recent(
    subject: str | None = None,
    q: str | None = None,
    affiliate_id: int | None = None,
    actor_id: int | None = None,
    kind: str | None = None,
    include_sign_ins: bool = True,
    before: int | None = None,
    limit: int = 50,
    _actor: UserAccount = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The most recent events, narrowed however the person asks.

    `q` searches the way a person does - a model's name, a colleague, a word
    from a reason - and an exact subject (`affiliate:12`) is matched whole.
    `subject` is the older substring filter, kept for anything still using it.
    """
    capped = max(1, min(limit, MAX_LIMIT))
    try:
        # One more than asked for, so the screen knows whether *Show older*
        # has anything behind it without a second request.
        events = recent_events(
            db,
            limit=capped + 1,
            subject_contains=subject,
            q=q,
            affiliate_id=affiliate_id,
            actor_id=actor_id,
            kind=kind,
            include_sign_ins=include_sign_ins,
            before_id=before,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    has_more = len(events) > capped
    events = events[:capped]
    # The export's *Recent activity*: what happened in words, and who.
    words = describe(db, events)
    return {
        "events": [
            {
                **words[index],
                "id": event.id,
                "action": event.action,
                "kind": kind_of(event.action),
                "subject": event.subject,
                "actor_email": event.actor_email,
                "reason": event.reason,
                "created_at": event.created_at.isoformat(),
                "before": event.before_json,
                "after": event.after_json,
            }
            for index, event in enumerate(events)
        ],
        "has_more": has_more,
    }


@router.get("/filters")
def filters(
    _actor: UserAccount = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """What the activity log can be narrowed to: every model by name, and every
    person who has done something recorded - read from the trail itself, so
    the list holds nobody the log has nothing about."""
    actors = select(AuditEvent.actor_id).where(AuditEvent.actor_id.is_not(None)).distinct()
    people = db.execute(
        select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(
            UserAccount.id.in_(actors)
        )
    ).all()
    models = db.execute(
        select(AffiliateProfile.id, AffiliateProfile.name).order_by(AffiliateProfile.name)
    ).all()
    return {
        "models": [{"id": row.id, "name": row.name} for row in models],
        "people": sorted(
            ({"id": row.id, "name": row.display_name or row.email} for row in people),
            key=lambda person: person["name"].lower(),
        ),
        "kinds": list(KINDS),
    }
