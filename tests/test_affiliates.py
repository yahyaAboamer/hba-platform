"""The affiliate registry.

Spec section 8. Business data for an affiliate, hanging off a user_account
rather than replacing it (ADR 0006).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind, AffiliateProfile, AffiliateStatus
from app.models.identity import UserAccount
from app.services.affiliates import (
    archive_affiliate,
    create_affiliate,
    get_affiliate,
    list_affiliates,
    set_status,
)
from app.services.codes import owner_of, register_code


def _account(db, email="nour@example.com") -> UserAccount:
    account = UserAccount(
        email=email,
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name="Nour",
    )
    db.add(account)
    db.flush()
    return account


def _audit_actions(db) -> list[str]:
    return [
        row[0]
        for row in db.execute(text("SELECT action FROM audit_event ORDER BY id"))
    ]


# ── Creating ───────────────────────────────────────────────────────────────────


def test_an_affiliate_is_created_pending(db):
    """Applied, not yet approved. Approval is a deliberate later act."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()

    assert affiliate.status == AffiliateStatus.PENDING
    assert affiliate.account_kind == AccountKind.MODEL
    assert affiliate.id is not None


def test_an_affiliate_is_rooted_in_a_user_account(db):
    """Identity lives in user_account (ADR 0006). An affiliate is business data
    hanging off an account, never an account in itself.
    """
    account = _account(db)
    affiliate = create_affiliate(db, user_account_id=account.id, name="Nour")
    db.flush()

    assert affiliate.user_account_id == account.id
    assert affiliate.account.email == "nour@example.com"


def test_a_profile_cannot_exist_without_an_account(db):
    db.add(AffiliateProfile(user_account_id=999999, name="Ghost"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_one_profile_per_user_account(db):
    account = _account(db)
    create_affiliate(db, user_account_id=account.id, name="Nour")
    db.flush()
    with pytest.raises(IntegrityError):
        create_affiliate(db, user_account_id=account.id, name="Nour Again")


def test_the_phone_number_is_optional(db):
    """Collected as an InstaPay fallback (§13.1), not required to exist."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    assert affiliate.phone is None


# ── House accounts ─────────────────────────────────────────────────────────────


def test_a_house_account_is_marked_as_such(db):
    """HBA10 is a real code used by real customers. It needs a working
    dashboard for verification and must never appear in payable totals or
    rankings - so it is a kind of account, not a kind of code.
    """
    house = create_affiliate(
        db,
        user_account_id=_account(db, "house@example.com").id,
        name="HBA House",
        account_kind=AccountKind.HOUSE,
    )
    db.flush()
    assert house.account_kind == AccountKind.HOUSE
    assert house.is_payable is False


def test_a_model_account_is_payable(db):
    """Guards the test above, which would pass if nothing were ever payable."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    assert affiliate.is_payable is True


# ── The vocabulary is fixed ────────────────────────────────────────────────────


def test_an_unknown_status_is_refused_by_the_database(db):
    create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE affiliate_profile SET status = 'nearly'"))


def test_an_unknown_account_kind_is_refused_by_the_database(db):
    create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE affiliate_profile SET account_kind = 'sort-of'"))


def test_an_unknown_status_is_refused_by_the_service(db):
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    with pytest.raises(ValueError, match="Unknown affiliate status"):
        set_status(db, affiliate, "nearly")


def test_an_unknown_account_kind_is_refused_by_the_service(db):
    with pytest.raises(ValueError, match="Unknown account kind"):
        create_affiliate(
            db, user_account_id=_account(db).id, name="Nour", account_kind="sort-of"
        )


# ── Status changes ─────────────────────────────────────────────────────────────


def test_a_status_change_is_recorded(db):
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    set_status(db, affiliate, AffiliateStatus.ACTIVE)
    db.flush()

    assert affiliate.status == AffiliateStatus.ACTIVE
    assert "affiliate.status_changed" in _audit_actions(db)


def test_the_audit_record_names_what_it_changed_from(db):
    """"Who deactivated Nour, and when" gets asked. The new value alone does
    not answer it.
    """
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    set_status(db, affiliate, AffiliateStatus.ACTIVE)
    db.flush()

    before, after = db.execute(
        text(
            "SELECT before_json, after_json FROM audit_event "
            "WHERE action = 'affiliate.status_changed'"
        )
    ).one()
    assert before["status"] == AffiliateStatus.PENDING
    assert after["status"] == AffiliateStatus.ACTIVE


def test_setting_the_status_it_already_has_records_nothing(db):
    """An audit trail of non-events is an audit trail nobody reads."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    set_status(db, affiliate, AffiliateStatus.PENDING)
    db.flush()

    assert "affiliate.status_changed" not in _audit_actions(db)


def test_creating_an_affiliate_is_recorded(db):
    create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    assert "affiliate.created" in _audit_actions(db)


# ── Archiving ──────────────────────────────────────────────────────────────────


def test_archiving_does_not_delete(db):
    """An archived affiliate's past payroll still has to resolve."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    archive_affiliate(db, affiliate)
    db.flush()

    assert affiliate.status == AffiliateStatus.ARCHIVED
    assert get_affiliate(db, affiliate.id) is not None


def test_archiving_stamps_when(db):
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    archive_affiliate(db, affiliate)
    db.flush()
    assert affiliate.archived_at is not None


def test_archiving_twice_keeps_the_first_timestamp(db):
    """When somebody left is a fact, not a function of who clicked last."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    archive_affiliate(db, affiliate)
    db.flush()
    first = affiliate.archived_at

    archive_affiliate(db, affiliate)
    db.flush()
    assert affiliate.archived_at == first


# ── Listing ────────────────────────────────────────────────────────────────────


def test_listing_excludes_archived_by_default(db):
    keep = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    gone = create_affiliate(
        db, user_account_id=_account(db, "old@example.com").id, name="Old"
    )
    db.flush()
    archive_affiliate(db, gone)
    db.flush()

    assert [a.id for a in list_affiliates(db)] == [keep.id]


def test_listing_can_include_archived(db):
    create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    gone = create_affiliate(
        db, user_account_id=_account(db, "old@example.com").id, name="Old"
    )
    db.flush()
    archive_affiliate(db, gone)
    db.flush()

    assert len(list_affiliates(db, include_archived=True)) == 2


def test_listing_is_ordered_by_name(db):
    for index, name in enumerate(["Zeina", "Amira", "Nour"]):
        create_affiliate(
            db, user_account_id=_account(db, f"{index}@example.com").id, name=name
        )
    db.flush()

    assert [a.name for a in list_affiliates(db)] == ["Amira", "Nour", "Zeina"]


# ── Deletion cascades from the account ─────────────────────────────────────────


def test_a_deleted_user_account_takes_its_profile_with_it(db):
    """ON DELETE CASCADE, honoured by passive_deletes. Without it SQLAlchemy
    tries to NULL the foreign key first, which violates NOT NULL and fails the
    delete outright - the exact bug Phase 1 hit on role_assignment.
    """
    account = _account(db)
    create_affiliate(db, user_account_id=account.id, name="Nour")
    db.flush()

    db.delete(account)
    db.flush()

    assert db.query(AffiliateProfile).count() == 0


# ── Archiving closes code ownership (does not just change status) ──────────────


def test_archiving_closes_open_ended_code_ownership(db):
    """Archiving says "from now on, not theirs" - and must actually make that
    true, or an archived affiliate keeps silently owning their code and a
    later order still attributes to them.
    """
    from app.core.businesstime import business_month, utcnow

    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    register_code(db, affiliate, "NOUR10", "2026-01")
    db.flush()

    archive_affiliate(db, affiliate)
    db.flush()

    current_month = business_month(utcnow())
    assert owner_of(db, "NOUR10", current_month) is not None
    # A month safely after "now" in any test run must be unowned.
    assert owner_of(db, "NOUR10", "2099-12") is None


def test_archiving_does_not_touch_already_closed_code_periods(db):
    """A period that ended earlier must not be extended by archiving."""
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    register_code(db, affiliate, "OLD10", "2026-01", "2026-03")
    db.flush()

    archive_affiliate(db, affiliate)
    db.flush()

    assert owner_of(db, "OLD10", "2026-02") is not None
    assert owner_of(db, "OLD10", "2026-04") is None


def test_archiving_with_no_codes_does_not_error(db):
    affiliate = create_affiliate(db, user_account_id=_account(db).id, name="Nour")
    db.flush()
    archive_affiliate(db, affiliate)
    db.flush()
    assert affiliate.status == AffiliateStatus.ARCHIVED
