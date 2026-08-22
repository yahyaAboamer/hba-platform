"""Permissions and roles.

Spec sections 5.1 and 6.3. Roles are defined in code so that every change to
who can do what is version-controlled, reviewed, and covered by tests. These
tests are that coverage.

The target_recorder assertions matter most: an external review flagged that
granting Sara full affiliate_manager access would let a content-tracking role
alter compensation, payroll, and payments. The negative assertions below are
what stop that regressing.
"""

import pytest

from app.core.permissions import (
    ALL_PERMISSIONS,
    ROLES,
    VALID_ROLES,
    Permission,
    has_permission,
    permissions_for,
)


# ── admin ──────────────────────────────────────────────────────────────────────


def test_admin_has_every_permission():
    for permission in ALL_PERMISSIONS:
        assert has_permission("admin", permission) is True


def test_admin_grants_stay_in_sync_with_the_permission_list():
    # If a permission is added and admin is not updated, this fails.
    assert ROLES["admin"] == ALL_PERMISSIONS


# ── affiliate_manager (Boda) ───────────────────────────────────────────────────


def test_affiliate_manager_runs_the_affiliate_programme():
    for granted in (
        Permission.AFFILIATES_VIEW,
        Permission.AFFILIATES_MANAGE,
        Permission.COMPENSATION_MANAGE,
        Permission.TARGETS_MANAGE,
        Permission.TARGETS_VERIFY,
        Permission.PAYROLL_APPROVE,
        Permission.INVITATIONS_SEND,
        Permission.AUDIT_VIEW,
    ):
        assert has_permission("affiliate_manager", granted) is True


def test_affiliate_manager_cannot_record_payments():
    # Payment recording stays with admin at launch (spec 5.1).
    assert has_permission("affiliate_manager", Permission.PAYMENTS_RECORD) is False


def test_affiliate_manager_cannot_reopen_approved_payroll():
    # Reopening rewrites an approved financial record; admin only.
    assert has_permission("affiliate_manager", Permission.PAYROLL_REOPEN) is False


def test_affiliate_manager_cannot_change_platform_settings():
    assert has_permission("affiliate_manager", Permission.SETTINGS_MANAGE) is False


# ── target_recorder (Sara) ─────────────────────────────────────────────────────


def test_target_recorder_can_do_its_job():
    assert has_permission("target_recorder", Permission.TARGETS_RECORD) is True
    assert has_permission("target_recorder", Permission.AFFILIATES_VIEW) is True


def test_target_recorder_has_no_financial_authority():
    """The whole reason this role exists.

    Sara records video and story counts. She needs nothing else, and the audit
    trail is only meaningful when access is minimal.
    """
    for forbidden in (
        Permission.COMPENSATION_MANAGE,
        Permission.PAYROLL_APPROVE,
        Permission.PAYROLL_REOPEN,
        Permission.PAYMENTS_RECORD,
        Permission.INVITATIONS_SEND,
        Permission.AFFILIATES_MANAGE,
        Permission.TARGETS_MANAGE,
        Permission.TARGETS_VERIFY,
        Permission.SETTINGS_MANAGE,
        Permission.AUDIT_VIEW,
    ):
        assert has_permission("target_recorder", forbidden) is False


def test_target_recorder_cannot_verify_its_own_recordings():
    """Separation of duties: recording and verifying are different people.

    Verification is what unlocks a base guarantee, so the person entering the
    numbers must not also be the person approving them.
    """
    assert has_permission("target_recorder", Permission.TARGETS_RECORD) is True
    assert has_permission("target_recorder", Permission.TARGETS_VERIFY) is False


def test_target_recorder_is_strictly_smaller_than_affiliate_manager():
    assert permissions_for("target_recorder") < permissions_for("affiliate_manager")


# ── affiliate ──────────────────────────────────────────────────────────────────


def test_affiliate_role_has_no_staff_permissions():
    """Affiliates reach their own portal by owning the record, not by permission."""
    assert permissions_for("affiliate") == frozenset()


# ── Guard rails ────────────────────────────────────────────────────────────────


def test_unknown_role_grants_nothing():
    assert has_permission("wizard", Permission.AFFILIATES_VIEW) is False
    assert permissions_for("wizard") == frozenset()


def test_unknown_permission_is_rejected_even_for_admin():
    """A typo must fail loudly rather than silently denying access."""
    with pytest.raises(ValueError):
        has_permission("admin", "not.a.real.permission")
    with pytest.raises(ValueError):
        has_permission("admin", "payroll.aprove")  # deliberate misspelling


def test_valid_roles_matches_the_role_map():
    assert VALID_ROLES == frozenset(ROLES)


def test_every_granted_permission_is_a_real_permission():
    for role, granted in ROLES.items():
        assert granted <= ALL_PERMISSIONS, f"{role} grants an unknown permission"


def test_permission_values_are_unique():
    # Two constants sharing a value would silently merge two capabilities.
    values = [
        value for name, value in vars(Permission).items() if not name.startswith("_")
    ]
    assert len(values) == len(set(values))


def test_returned_permission_sets_cannot_be_mutated():
    """A caller must not be able to grant itself a permission at runtime."""
    granted = permissions_for("target_recorder")
    with pytest.raises(AttributeError):
        granted.add(Permission.PAYMENTS_RECORD)  # type: ignore[attr-defined]
    assert has_permission("target_recorder", Permission.PAYMENTS_RECORD) is False


def test_the_four_expected_roles_exist_and_no_others():
    assert VALID_ROLES == {"admin", "affiliate_manager", "target_recorder", "affiliate"}
