"""The commission rules, in the words a model reads.

Nothing here calculates anything, and nothing here is the engineering record -
the ADRs already are that. This is the translation layer: what the rules mean,
written once in plain language, dated, and pointed to by every payroll
snapshot that was calculated under it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month
from app.models.payroll import PolicyVersion
from app.services.audit import record_audit


def list_policy_versions(db: Session) -> list[PolicyVersion]:
    """Every version, oldest first - the order a reader expects a history in."""
    return list(
        db.scalars(select(PolicyVersion).order_by(PolicyVersion.effective_month))
    )


def get_policy_version(db: Session, policy_version_id: int) -> PolicyVersion | None:
    return db.get(PolicyVersion, policy_version_id)


def active_policy_for(db: Session, month: str) -> PolicyVersion | None:
    """Whichever version governs this month: the latest one that had already
    taken effect by then.

    `None` only for a month before any policy version exists - which, once
    v1 is backfilled to `GO_LIVE_MONTH`, should never actually happen for a
    month the platform calculates payroll for.
    """
    parse_month(month)
    return db.scalar(
        select(PolicyVersion)
        .where(PolicyVersion.effective_month <= month)
        .order_by(PolicyVersion.effective_month.desc())
        .limit(1)
    )


def create_policy_version(
    db: Session,
    *,
    effective_month: str,
    summary_markdown: str,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PolicyVersion:
    """Record a rule change - or the first policy, if none exists yet.

    Refused if it would not be the newest: a version dated earlier than one
    that already exists cannot be "the latest one in force" for any month
    without producing a history that reads out of order. The database's own
    unique constraint on `effective_month` is the backstop; this is the
    readable half of it.
    """
    parse_month(effective_month)
    text = str(summary_markdown or "").strip()
    if not text:
        raise ValueError("The policy text cannot be empty.")

    latest = db.scalar(
        select(PolicyVersion).order_by(PolicyVersion.effective_month.desc()).limit(1)
    )
    if latest is not None and effective_month <= latest.effective_month:
        raise ValueError(
            f"A policy version already exists effective {latest.effective_month}. "
            "A new one must take effect later than every version before it."
        )

    version = PolicyVersion(
        effective_month=effective_month,
        summary_markdown=text,
        created_by=actor_id,
    )
    db.add(version)
    db.flush()

    record_audit(
        db,
        action="policy_version.created",
        subject=f"policy_version:{version.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"effective_month": effective_month},
    )
    return version
