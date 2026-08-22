"""Permissions and roles, defined in code.

Roles are deliberately not composable through the interface. A UI for building
arbitrary permission sets is complex to test, easy to misconfigure into a
security hole, and hard to reason about six months later. Defining them here
means every change to who can do what is version-controlled, reviewed, and
covered by tests.

Assigning a person to a role happens in the application. That is the
flexibility actually needed day to day: invite someone, change their role,
revoke access — none of which requires code.

Every check is enforced server-side. Hiding a control in the interface is
presentation, never protection.
"""


class Permission:
    """Capability constants. The value is what is stored and compared."""

    AFFILIATES_VIEW = "affiliates.view"
    AFFILIATES_MANAGE = "affiliates.manage"
    COMPENSATION_MANAGE = "compensation.manage"
    TARGETS_RECORD = "targets.record"
    TARGETS_MANAGE = "targets.manage"
    TARGETS_VERIFY = "targets.verify"
    PAYROLL_APPROVE = "payroll.approve"
    PAYROLL_REOPEN = "payroll.reopen"
    PAYMENTS_RECORD = "payments.record"
    INVITATIONS_SEND = "invitations.send"
    AUDIT_VIEW = "audit.view"
    SETTINGS_MANAGE = "settings.manage"


ALL_PERMISSIONS = frozenset(
    value for name, value in vars(Permission).items() if not name.startswith("_")
)

ROLES: dict[str, frozenset[str]] = {
    # The maintainer. Also the only role that may reopen approved payroll or
    # record payments, both of which touch settled financial records.
    "admin": ALL_PERMISSIONS,
    # Boda: runs the affiliate programme end to end, up to approving payroll.
    # Payment recording and reopening are withheld at launch.
    "affiliate_manager": frozenset(
        {
            Permission.AFFILIATES_VIEW,
            Permission.AFFILIATES_MANAGE,
            Permission.COMPENSATION_MANAGE,
            Permission.TARGETS_MANAGE,
            Permission.TARGETS_VERIFY,
            Permission.TARGETS_RECORD,
            Permission.PAYROLL_APPROVE,
            Permission.INVITATIONS_SEND,
            Permission.AUDIT_VIEW,
        }
    ),
    # Sara: records video and story counts. She needs nothing else, so she gets
    # nothing else. Note that recording is separated from verifying — verified
    # targets unlock a base guarantee, so the person entering the numbers must
    # not also be the person approving them.
    "target_recorder": frozenset(
        {
            Permission.AFFILIATES_VIEW,
            Permission.TARGETS_RECORD,
        }
    ),
    # Affiliates reach their own portal by owning the record, not by holding a
    # staff permission, so this set is intentionally empty.
    "affiliate": frozenset(),
}

VALID_ROLES = frozenset(ROLES)


def permissions_for(role: str) -> frozenset[str]:
    """Every permission a role grants. Unknown roles grant nothing."""
    return ROLES.get(role, frozenset())


def has_permission(role: str, permission: str) -> bool:
    """Whether a role grants a permission.

    An unrecognised permission raises rather than returning False: a typo in a
    check should fail loudly during development, not silently deny access in
    production and look like a permissions bug.
    """
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    return permission in permissions_for(role)
