"""Permissions and roles.

Spec sections 5.1 and 6.3. Roles are defined in code so that every change to
who can do what is version-controlled, reviewed, and covered by tests. These
tests are that coverage.

The negative assertions matter most. Roles here are wide by design - the
business chose that knowingly - so what these tests pin is the boundary that
did NOT move: no role except admin can both decide an obligation and settle
it.
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


# ── content_manager (Sara) ─────────────────────────────────────────────────────


def test_content_manager_owns_content_and_the_affiliate_roster():
    """Sara's job combines several concerns, so the role does too."""
    for granted in (
        Permission.AFFILIATES_VIEW,
        Permission.AFFILIATES_MANAGE,
        Permission.COMPENSATION_MANAGE,
        Permission.TARGETS_RECORD,
        Permission.TARGETS_MANAGE,
        Permission.TARGETS_VERIFY,
        Permission.AUDIT_VIEW,
    ):
        assert has_permission("content_manager", granted) is True


def test_content_manager_cannot_approve_payroll_or_move_money():
    """The boundary that still holds.

    This role sets compensation and verifies targets, so it decides what is
    owed. It cannot approve a month, reopen an approved one, or record a
    payment - so deciding an obligation and settling it stay separate acts,
    performed by different people.
    """
    for forbidden in (
        Permission.PAYROLL_APPROVE,
        Permission.PAYROLL_REOPEN,
        Permission.PAYMENTS_RECORD,
    ):
        assert has_permission("content_manager", forbidden) is False


def test_content_manager_cannot_grant_access_to_others():
    assert has_permission("content_manager", Permission.INVITATIONS_SEND) is False


def test_content_manager_cannot_change_platform_settings():
    # Settings change everyone's numbers at once: go-live month, return window.
    assert has_permission("content_manager", Permission.SETTINGS_MANAGE) is False


def test_content_manager_is_strictly_smaller_than_admin():
    assert permissions_for("content_manager") < permissions_for("admin")


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
    """A caller must not be able to grant itself a permission at runtime.

    Uses a real role deliberately. An unknown role returns an empty frozenset,
    which is also immutable, so this test would still pass while asserting
    nothing if the role name were stale.
    """
    granted = permissions_for("content_manager")
    assert granted, "must exercise a real, non-empty role"
    with pytest.raises(AttributeError):
        granted.add(Permission.PAYMENTS_RECORD)  # type: ignore[attr-defined]
    assert has_permission("content_manager", Permission.PAYMENTS_RECORD) is False


def test_no_test_references_a_role_that_does_not_exist():
    """Guards against the stale-role-name trap this file just fell into.

    permissions_for() returns an empty set for any unknown role, so a renamed
    role leaves tests passing while silently checking nothing.
    """
    import pathlib
    import re

    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    referenced = set(re.findall(r'(?:permissions_for|has_permission)\(\s*"([a-z_]+)"', source))
    unknown = referenced - VALID_ROLES
    assert unknown == {"wizard"}, f"tests reference unknown roles: {unknown - {'wizard'}}"


def test_the_four_expected_roles_exist_and_no_others():
    assert VALID_ROLES == {"admin", "affiliate_manager", "content_manager", "affiliate"}
