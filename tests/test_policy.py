"""Policy versions - the commission rules, in plain language, dated.

Spec section 16, Phase 10 Batch C. Not the ADRs, which already are the
engineering record; this is the same rules translated once into what a model
reads, and pointed to by every payroll snapshot calculated under it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.payroll import PolicyVersion
from app.services.policy import (
    active_policy_for,
    create_policy_version,
    get_policy_version,
    list_policy_versions,
)


def _version(db, month="2026-09", text_="Commission is worked out on the base."):
    return create_policy_version(db, effective_month=month, summary_markdown=text_)


# ── Creating ─────────────────────────────────────────────────────────────────


def test_the_first_version_can_be_created(db):
    version = _version(db)
    db.flush()

    assert version.effective_month == "2026-09"
    assert "Commission" in version.summary_markdown


def test_empty_text_is_refused(db):
    with pytest.raises(ValueError):
        create_policy_version(db, effective_month="2026-09", summary_markdown="   ")


def test_a_second_version_must_be_later_than_the_first(db):
    _version(db, "2026-09")
    db.flush()

    with pytest.raises(ValueError) as refused:
        create_policy_version(db, effective_month="2026-06", summary_markdown="x")
    assert "2026-09" in str(refused.value)


def test_the_same_month_twice_is_refused(db):
    _version(db, "2026-09")
    db.flush()

    with pytest.raises(ValueError):
        create_policy_version(db, effective_month="2026-09", summary_markdown="x")


def test_the_database_backs_the_refusal_too(db):
    """The service's check is the readable half; this is the real one."""
    db.add(PolicyVersion(effective_month="2026-09", summary_markdown="x"))
    db.flush()

    db.add(PolicyVersion(effective_month="2026-09", summary_markdown="y"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_a_version_cannot_be_rewritten(db):
    """The text is what a model was told the rules were. Changing it in place
    would change what an already-approved month claims it was calculated
    under, and leave nothing behind saying so.

    `payroll_snapshot.policy_version_id` is `ondelete RESTRICT`, which stops a
    version some month depends on being deleted - but RESTRICT says nothing
    about the words. The guard does (b7c4e1a92f30).
    """
    version = _version(db, text_="the original wording")
    db.flush()

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text("update policy_version set summary_markdown = :t where id = :i"),
            {"t": "quietly different", "i": version.id},
        )
    assert "append-only" in str(refused.value)


def test_a_version_cannot_be_deleted(db):
    """A rule change is a new row with a later effective_month. Nothing is ever
    withdrawn, including a version no month happens to point at yet.
    """
    version = _version(db)
    db.flush()

    with pytest.raises(IntegrityError) as refused:
        db.execute(
            text("delete from policy_version where id = :i"), {"i": version.id}
        )
    assert "append-only" in str(refused.value)


def test_creating_a_version_is_recorded(db):
    version = _version(db, text_="x", month="2026-09")
    db.flush()

    row = db.execute(
        text("select action from audit_event where subject = :s"),
        {"s": f"policy_version:{version.id}"},
    ).fetchone()
    assert row is not None
    assert row.action == "policy_version.created"


# ── Reading ──────────────────────────────────────────────────────────────────


def test_versions_list_oldest_first(db):
    _version(db, "2026-09")
    db.flush()
    _version(db, "2026-11")
    db.flush()

    months = [v.effective_month for v in list_policy_versions(db)]
    assert months == ["2026-09", "2026-11"]


def test_get_by_id(db):
    version = _version(db)
    db.flush()

    assert get_policy_version(db, version.id).id == version.id
    assert get_policy_version(db, 999999) is None


# ── Which version governs a month ───────────────────────────────────────────


def test_no_version_governs_a_month_before_any_exist(db):
    assert active_policy_for(db, "2026-09") is None


def test_the_only_version_governs_every_month_from_its_start(db):
    v1 = _version(db, "2026-09")
    db.flush()

    assert active_policy_for(db, "2026-09").id == v1.id
    assert active_policy_for(db, "2027-01").id == v1.id


def test_a_month_before_the_first_version_has_none(db):
    _version(db, "2026-09")
    db.flush()

    assert active_policy_for(db, "2026-08") is None


def test_the_newest_version_that_has_taken_effect_wins(db):
    v1 = _version(db, "2026-09")
    db.flush()
    v2 = _version(db, "2026-11")
    db.flush()

    assert active_policy_for(db, "2026-09").id == v1.id
    assert active_policy_for(db, "2026-10").id == v1.id, "v2 has not taken effect yet"
    assert active_policy_for(db, "2026-11").id == v2.id
    assert active_policy_for(db, "2027-06").id == v2.id
