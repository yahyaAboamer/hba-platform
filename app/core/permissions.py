"""Permissions and roles, defined in code.

Roles are deliberately not composable through the interface. A UI for building
arbitrary permission sets is complex to test, easy to misconfigure into a
security hole, and hard to reason about six months later. Defining them here
means every change to who can do what is version-controlled, reviewed, and
covered by tests.

Assigning a person to a role happens in the application. That is the
flexibility actually needed day to day: invite someone, give them a role,
take one away — none of which requires code.

**A person may hold several roles at once** (ADR 0067). What they may do is
everything their live roles grant together, so a mix of jobs is two
assignments rather than a new role invented for the mix.

Every check is enforced server-side. Hiding a control in the interface is
presentation, never protection.
"""

from collections.abc import Iterable


class Permission:
    """Capability constants. The value is what is stored and compared."""

    AFFILIATES_VIEW = "affiliates.view"
    AFFILIATES_MANAGE = "affiliates.manage"
    #: Erasing a model outright (ADR 0052). Held by no role but admin.
    AFFILIATES_ERASE = "affiliates.erase"
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
    #: The operations dashboard - Shopify, Bosta and E-stebdal (ADR 0057).
    #: Reading only: nothing behind it writes to any of the three.
    ORDER_OPS_VIEW = "order_ops.view"
    #: The customer inbox - WhatsApp chats and order confirmations (ADR 0059).
    #: Reading and replying: the one permission customer service holds.
    INBOX_USE = "inbox.use"


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
    # Sara: owns content and the affiliate roster day to day. Their job combines
    # setting monthly requirements, recording what was published, verifying it,
    # maintaining affiliate records, and setting compensation terms.
    #
    # Note deliberately, so it is not mistaken for an oversight: this role both
    # verifies targets and manages compensation. Verification is what releases a
    # base guarantee, so there is no second pair of eyes between setting a
    # target, judging it met, and the money that follows. The business accepted
    # this knowingly. Approving payroll and recording payments remain elsewhere,
    # so the obligation and its settlement are still separate acts.
    "content_manager": frozenset(
        {
            Permission.AFFILIATES_VIEW,
            Permission.AFFILIATES_MANAGE,
            Permission.COMPENSATION_MANAGE,
            Permission.TARGETS_RECORD,
            Permission.TARGETS_MANAGE,
            Permission.TARGETS_VERIFY,
            Permission.AUDIT_VIEW,
        }
    ),
    # The operations manager (ADR 0057): the operations dashboard and nothing
    # else - no model, code, target, payroll or payment, and no invitations,
    # because he is the only one and the staff do not use it. There is one at
    # a time; the database refuses a second live holder.
    #
    # He also holds the customer inbox (ADR 0059, owner, 11 October 2026), but
    # since ADR 0067 as a second assignment, `customer_service`, rather than
    # as part of this role: migration c3e7a1f90019 gave it to whoever held
    # this role then, so nobody's access changed.
    "operations_manager": frozenset({Permission.ORDER_OPS_VIEW}),
    # Customer service (ADR 0059): the inbox and nothing else - no model, code,
    # target, payroll, payment or Operations, and no invitations. Any number
    # of people may hold it; only an admin gives it.
    "customer_service": frozenset({Permission.INBOX_USE}),
    # Affiliates reach their own portal by owning the record, not by holding a
    # staff permission, so this set is intentionally empty.
    "affiliate": frozenset(),
}

VALID_ROLES = frozenset(ROLES)

#: Roles an invitation brings with it, beside the one it names. The operations
#: manager has held the customer inbox since ADR 0059; ADR 0067 made that a
#: second assignment rather than part of his role, so accepting his invitation
#: gives both, exactly as the role alone used to. Only invitations read this:
#: giving or taking a role in Settings is always one role at a time.
INVITATION_BRINGS: dict[str, tuple[str, ...]] = {
    "operations_manager": ("customer_service",),
}


def can_invite(actor_roles: str | Iterable[str], target_role: str) -> bool:
    """`can_grant` for an invitation: the role it names and every role it
    brings with it (`INVITATION_BRINGS`) must each be the actor's to give."""
    return all(
        can_grant(actor_roles, role)
        for role in (target_role, *INVITATION_BRINGS.get(target_role, ()))
    )


#: The order roles are listed in wherever a person's roles are shown: the
#: widest first, so the role somebody is known by leads (the operations
#: manager reads "operations manager", not "customer service").
ROLE_ORDER: tuple[str, ...] = tuple(ROLES)

#: The role that grants no staff permission. A model holds it; nobody is
#: *staff* by holding it (ADR 0067, decision 2).
MODEL_ROLE = "affiliate"


def permissions_for(role: str) -> frozenset[str]:
    """Every permission a role grants. Unknown roles grant nothing."""
    return ROLES.get(role, frozenset())


def _as_roles(roles: str | Iterable[str]) -> frozenset[str]:
    """One role or several, as a set.

    A bare string is one role, never its letters: iterating "admin" would
    otherwise check the roles "a", "d", "m"... which grant nothing and would
    fail closed, but silently.
    """
    if isinstance(roles, str):
        return frozenset({roles})
    return frozenset(roles)


def permissions_of_roles(roles: str | Iterable[str]) -> frozenset[str]:
    """Everything a set of live roles grants together (ADR 0067).

    The union, and only the union: holding two roles never grants something
    neither grants alone.
    """
    granted: frozenset[str] = frozenset()
    for role in _as_roles(roles):
        granted |= permissions_for(role)
    return granted


def sorted_roles(roles: Iterable[str]) -> list[str]:
    """Roles in `ROLE_ORDER`, widest first. Unknown names go last."""
    order = {role: index for index, role in enumerate(ROLE_ORDER)}
    return sorted(set(roles), key=lambda role: (order.get(role, len(order)), role))


def is_staff(roles: Iterable[str]) -> bool:
    """Whether these roles make somebody staff: any role but a model's."""
    return any(role != MODEL_ROLE for role in roles)


#: What a refused grant says. The same words wherever it is refused.
GRANT_REFUSED = "You can only give people access you hold yourself."


def can_grant(actor_roles: str | Iterable[str], target_role: str) -> bool:
    """Whether somebody holding `actor_roles` may hand `target_role` to another.

    **Only access they already hold in full.** Inviting is how an account comes
    to exist, so an invitation is a grant - and an affiliate manager who could
    invite an admin could make themselves one: invite a second address, open
    the link, set the password. Found by doing exactly that (Settings audit,
    30 September 2026). Holding `invitations.send` decides *whether* somebody
    may invite; this decides *what to*.

    A model's role grants nothing, so anybody who may invite may invite a model.

    **Checked against everything the actor holds together** (ADR 0067): a
    role may be given when each thing it grants is in the union of the
    actor's live roles. One role or several may be passed.
    """
    if target_role not in VALID_ROLES:
        return False
    return permissions_for(target_role) <= permissions_of_roles(actor_roles)


def has_permission(roles: str | Iterable[str], permission: str) -> bool:
    """Whether a role, or a person's several roles together, grant a permission.

    An unrecognised permission raises rather than returning False: a typo in a
    check should fail loudly during development, not silently deny access in
    production and look like a permissions bug.
    """
    if permission not in ALL_PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")
    return permission in permissions_of_roles(roles)
