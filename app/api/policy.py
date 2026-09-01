"""The commission rules, in plain language, over HTTP.

Gated on `settings.manage` - the same permission that gates the staff roster
(app/api/staff.py). Recording a policy version is a decision about what the
platform's own rules mean, not an operational task the way registering a code
or setting a target is; it belongs with the other things only `admin` grants
today.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.permissions import Permission
from app.db import get_session
from app.models.identity import UserAccount
from app.services.policy import create_policy_version, list_policy_versions

router = APIRouter(prefix="/api/policy")


def _payload(version) -> dict:
    return {
        "id": version.id,
        "effective_month": version.effective_month,
        "summary_markdown": version.summary_markdown,
        "created_at": version.created_at.isoformat(),
    }


@router.get("/versions")
def list_versions_route(
    _actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    return {"versions": [_payload(v) for v in list_policy_versions(db)]}


class CreatePolicyVersionBody(BaseModel):
    effective_month: str = Field(min_length=7, max_length=7)
    summary_markdown: str = Field(min_length=1)


@router.post("/versions", status_code=201)
def create_version_route(
    body: CreatePolicyVersionBody,
    actor: UserAccount = Depends(require_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_session),
) -> dict:
    try:
        version = create_policy_version(
            db,
            effective_month=body.effective_month,
            summary_markdown=body.summary_markdown,
            actor_id=actor.id,
            actor_email=actor.email,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    db.commit()
    return _payload(version)
