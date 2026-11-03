"""The business audit trail, over HTTP. Read-only.

§16: who did what, when, and why where a reason was required. Nothing here
writes - `record_audit` is called from inside the action that changed
something, in the same transaction as the change itself, and that remains the
only way an event is created.

**Read by department** (Batch 2.3, contract §4). The owner (`settings.manage`)
reads everything. Anybody else with `audit.view` reads only the entries of
the departments they hold - held exactly as Today decides it
(`DEPARTMENT_HELD_BY`) - and never an entry no department claims: sign-ins,
staff access, Settings and the connections are the owner's. An entry written
before entries carried a department is read by its action, as it is read and
never rewritten (`in_departments`). The narrowing is in the query itself
(`recent_events`), so paging is never thrown off by it.

Every value returned here was already masked at write time
(`app/services/audit.py`, `mask_sensitive`), so nothing extra happens on the
way out. Masking twice would risk masking a value that was already a mask.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.api.deps import permissions_of, require_permission
from app.core.permissions import Permission, departments_held
from app.db import get_session
from app.modules.affiliates.models.affiliates import AffiliateProfile
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.services.audit import DEPARTMENTS, KINDS, kind_of, readable_by, recent_events
from app.shared.services.audit_words import describe

router = APIRouter(prefix="/api/audit")

MAX_LIMIT = 200

#: What asking for a department that is not yours says.
NOT_YOUR_DEPARTMENT = "That department's activity is not yours to read."


def readable_departments(db: Session, user: UserAccount) -> frozenset[str] | None:
    """The departments whose entries this person may read, or `None` for the
    owner, who reads every entry, those with no department included."""
    permissions = permissions_of(db, user)
    if Permission.SETTINGS_MANAGE in permissions:
        return None
    return frozenset(departments_held(permissions))


def _checked_department(department: str | None, readable: frozenset[str] | None) -> None:
    """An unknown department is a mistake (422); a known one that is not the
    reader's is refused (403)."""
    if department is None:
        return
    if department not in DEPARTMENTS:
        raise HTTPException(422, f"No such department: {department!r}")
    if readable is not None and department not in readable:
        raise HTTPException(403, NOT_YOUR_DEPARTMENT)


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
    department: str | None = None,
    actor: UserAccount = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """The most recent events, narrowed however the person asks.

    `q` searches the way a person does - a model's name, a colleague, a word
    from a reason - and an exact subject (`affiliate:12`) is matched whole.
    `subject` is the older substring filter, kept for anything still using it.
    `department` narrows to one of the reader's departments (Affiliates'
    activity page sends `affiliates`).
    """
    readable = readable_departments(db, actor)
    _checked_department(department, readable)
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
            readable=readable,
            department=department,
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
    actor: UserAccount = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_session),
) -> dict:
    """What the activity log can be narrowed to: every model by name, and every
    person who has done something recorded - read from the trail itself, so
    the list holds nobody the log has nothing about.

    The people are those in the entries this reader may read (Batch 2.3), so
    the list names nobody whose every entry is hidden from them. The models
    stay the roster: whoever reads the log already sees every model."""
    actors = readable_by(
        select(AuditEvent.actor_id).where(AuditEvent.actor_id.is_not(None)),
        readable_departments(db, actor),
    ).distinct()
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
