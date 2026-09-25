"""The audit trail as sentences (Settings → Reference, *Recent activity*).

The approved export writes each entry as what happened, in words, with who
and when under it (Admin lines 773-779, `ACTIVITY`): *Recorded a payment of EGP
1,900.00 to Yahya Aboamer for September 2026*. The trail itself stays exactly
as written - action codes and masked payloads (docs/limits.md); this only
reads it.

**Nothing here can reveal more than the row already holds.** Payloads were
masked when they were written; a sentence names a model or a member of staff
by the name on record, and a destination only by its method.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.affiliates import AffiliateProfile
from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.models.payroll import PayrollMonth

_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()

_ROLE = {
    "admin": "admin",
    "affiliate_manager": "affiliate manager",
    "content_manager": "content manager",
    "affiliate": "model",
}

_METHOD = {"instapay": "InstaPay", "wallet": "a wallet", "bank": "a bank account"}

_PAY_TYPE = {
    "commission": "commission",
    "fixed_plus_commission": "salary plus commission",
    "base_guarantee": "a guaranteed minimum with commission",
}


def _month(value) -> str:
    try:
        year, month = str(value).split("-")[:2]
        return f"{_MONTHS[int(month) - 1]} {int(year)}"
    except (ValueError, IndexError, TypeError):
        return str(value)


def _egp(piastres) -> str:
    try:
        value = int(piastres)
    except (TypeError, ValueError):
        return "an amount"
    sign = "-" if value < 0 else ""
    value = abs(value)
    return f"{sign}EGP {value // 100:,}.{value % 100:02d}"


class _Names:
    """Names for the subjects and actors of one page of events, in two queries."""

    def __init__(self, db: Session, events: list[AuditEvent]):
        affiliate_ids, user_ids, payroll_ids = set(), set(), set()
        for event in events:
            for key in ((event.after_json or {}).get("allocations") or {}):
                if str(key).isdigit():
                    payroll_ids.add(int(key))
            kind, _, ident = (event.subject or "").partition(":")
            if ident.isdigit():
                (affiliate_ids if kind == "affiliate" else user_ids if kind == "user" else set()).add(int(ident))
            if event.actor_id:
                user_ids.add(event.actor_id)
        self.affiliates = dict(
            db.execute(
                select(AffiliateProfile.id, AffiliateProfile.name).where(AffiliateProfile.id.in_(affiliate_ids))
            ).all()
        ) if affiliate_ids else {}
        self.users = {
            row.id: (row.display_name or row.email)
            for row in db.execute(
                select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(UserAccount.id.in_(user_ids))
            ).all()
        } if user_ids else {}

        self.months = dict(
            db.execute(select(PayrollMonth.id, PayrollMonth.month).where(PayrollMonth.id.in_(payroll_ids))).all()
        ) if payroll_ids else {}

    def allocated(self, after: dict) -> str:
        """*for September 2026* - the months a payment was allocated to."""
        months = sorted({self.months[int(k)] for k in (after.get("allocations") or {}) if str(k).isdigit() and int(k) in self.months})
        if not months:
            return ""
        words = [_month(m) for m in months]
        return " for " + (words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1])

    def subject(self, subject: str | None) -> str:
        kind, _, ident = (subject or "").partition(":")
        if kind == "affiliate" and ident.isdigit():
            return self.affiliates.get(int(ident), "a model no longer on file")
        if kind == "user" and ident.isdigit():
            return self.users.get(int(ident), "an account no longer on file")
        if kind == "invitation":
            return ident
        return subject or "the platform"

    def who(self, event: AuditEvent) -> str:
        if event.actor_id and event.actor_id in self.users:
            return self.users[event.actor_id]
        return event.actor_email or "The platform"


def sentence(event: AuditEvent, names: _Names) -> str:
    """One entry in words. An action nobody has written words for yet still
    reads as a sentence, from its own name - never as a code."""
    a, b = event.after_json or {}, event.before_json or {}
    who = names.subject(event.subject)
    month = _month(a.get("month") or b.get("month")) if (a.get("month") or b.get("month")) else None
    action = event.action or ""

    if action.startswith("adjustment."):
        kind = action.split(".", 1)[1]
        amount = _egp(a.get("amount_piastres"))
        source = _month(a.get("source_month"))
        if kind == "credit":
            return f"Carried {amount} overpaid to {who} in {source} forward to {_month(a.get('destination_month'))}"
        if kind == "writeoff":
            return f"Wrote off {amount} overpaid to {who} in {source}"
        return f"Recorded a correction of {amount} for {who}, {source}"

    words = {
        "affiliate.applied": f"{who} applied to the programme",
        "affiliate.created": f"Added {a.get('name') or who} as a {'house account' if a.get('account_kind') == 'house' else 'model'}",
        "affiliate.collaboration_start_set": (
            f"Recorded that {who} started with HBA in {_month(a.get('collaboration_start_month'))}"
            if a.get("collaboration_start_month") else f"Cleared the month {who} started with HBA"
        ),
        "affiliate.details_updated": f"Corrected {who}'s {_listed(a, {'name': 'name', 'phone': 'phone', 'email': 'sign-in email'})}",
        "affiliate.measurements_updated": f"{who} updated her measurements",
        "affiliate.shipping_address_updated": (
            f"Changed where {who}'s parcels go" if a.get("by") == "staff" else f"{who} changed where her parcels go"
        ),
        "affiliate.status_changed": f"Made {who} {a.get('status') or 'a different status'}",
        "application.approved": f"Approved {who}'s application",
        "auth.bootstrap": "Set up the platform's first admin account",
        "auth.login": f"{who} signed in",
        "auth.logout": f"{who} signed out",
        "auth.password_reset": f"{who} set a new password",
        "auth.password_reset_requested": f"{who} asked to reset their password",
        "code.registered": f"Registered the code {a.get('code')} for {who}" + (f" from {_month(a['start_month'])}" if a.get("start_month") else ""),
        "code.verified": f"Shopify confirmed {who}'s code",
        "code.corrected": f"Corrected {who}'s code from {b.get('code')} to {a.get('code')}",
        "code.replaced": f"Replaced {who}'s code {b.get('code')} with {a.get('code')}",
        "code.closed": f"Closed {who}'s code {a.get('code') or b.get('code')}" + (f" after {_month(a['end_month'])}" if a.get("end_month") else ""),
        "compensation.set": f"Set {who}'s terms to {_PAY_TYPE.get(a.get('compensation_type'), 'new terms')}" + (f" from {_month(a['start_month'])}" if a.get("start_month") else ""),
        "compensation.corrected": f"Corrected {who}'s terms",
        "compensation.closed": f"Ended {who}'s terms" + (f" after {_month(a['end_month'])}" if a.get("end_month") else ""),
        "compensation.history_replaced": f"Replaced {who}'s earlier terms",
        "invitation.create": f"Invited {who}" + (f" as {_ROLE.get(a.get('role'), a.get('role'))}" if a.get("role") else ""),
        "invitation.resend": f"Sent {who} a new invitation link",
        "invitation.revoked": f"Withdrew the invitation to {a.get('email') or who}",
        "invitation.accept": f"{who} accepted their invitation",
        "payment.recorded": f"Recorded a payment of {_egp(a.get('amount_piastres'))} to {who}" + names.allocated(a),
        "payment.allocated": f"Allocated a payment to {who}" + (f" for {month}" if month else ""),
        "payout_destination.set": f"Recorded where {who}'s payments go ({_METHOD.get(a.get('method'), 'a new method')})",
        "payout_destination.changed": f"Changed where {who}'s payments go ({_METHOD.get(a.get('method'), 'a new method')})",
        "payout_destination.revealed": f"Revealed {who}'s full payment details",
        "payroll.approved": f"Approved {who}'s {month or 'month'} at {_egp(a.get('obligation_piastres'))}",
        "payroll.reopened": f"Reopened {who}'s {month or 'month'}",
        "policy_version.created": f"Put a new commission policy in force from {_month(a.get('effective_month'))}",
        "shopify.connection_updated": "Updated the Shopify connection",
        "staff.preference_changed": f"Turned {'on' if a.get('on') else 'off'} “{a.get('switch')}” for themselves",
        "staff.role_changed": f"Changed {who}'s access to {_ROLE.get(a.get('role'), a.get('role'))}",
        "staff.suspended": f"Suspended {who}'s access",
        "staff.reactivated": f"Restored {who}'s access",
        "target.requirements_set": f"Set {who}'s content targets for {month}",
        "target.requirements_set_for_year": f"Set {who}'s content targets for the year",
        "target.actuals_recorded": f"Recorded achieved content for {who}, {month}",
        "target.actuals_cleared": f"Cleared {who}'s achieved content for {month}",
        "target.outcome_recorded": f"Recorded {who}'s target outcome for {month}",
        "target.verified": f"Confirmed {who}'s achieved content for {month}",
        "target.unverified": f"Took back the confirmation of {who}'s achieved content for {month}",
    }
    if action in words:
        return words[action]
    return f"{action.replace('_', ' ').replace('.', ': ', 1).capitalize()} - {who}"


def _listed(after: dict, labels: dict) -> str:
    parts = [labels[key] for key in labels if key in after]
    if not parts:
        return "details"
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def describe(db: Session, events: list[AuditEvent]) -> list[dict]:
    """`sentence` and `who` for each event, in one pass."""
    names = _Names(db, events)
    return [{"sentence": sentence(event, names), "who": names.who(event)} for event in events]
