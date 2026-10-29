"""A bonus HBA adds to one of a model's months (ADR 0070).

The owner, 29 October 2026: a button on every model to add a bonus, with an
optional reason that only staff see, and the month's summary saying a bonus
was added.

## Where it lives in the money

**On top of everything else, after the guarantee comparison** - the same place
carried orders go (`commission/calculate.py`). A guaranteed minimum is a floor
under her month's work; a bonus added inside the comparison would be swallowed
by the floor for exactly the model who earned least, and a bonus that makes no
difference is not one.

**Only on a month nobody has agreed.** Approval freezes the bonuses with the
figure (`payroll.approve_month`), so an agreed month's money is still read
from its snapshot and never moves under the word *Approved*. A bonus for a
month already agreed goes on the current month, or the month is reopened.

**Whole pounds**, because every payout is rounded to the pound once, on the
total (ADR 0004) - a bonus of EGP 500.50 would quietly lose its fifty piastres.

## The reason is for staff

It is stored here and in the audit trail, and returned only by the staff
routes. The portal builds what a model reads from the calculation, and the
calculation carries each bonus's id and amount and never its reason.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import parse_month, utcnow
from app.core.money import format_egp
from app.modules.affiliates.models.affiliates import AccountKind, AffiliateProfile
from app.modules.affiliates.models.payroll import CalculationState, PayrollBonus, PayrollMonth
from app.shared.services.audit import record_audit

#: Ten thousand times a typical bonus. A typo of three extra zeros is the
#: likeliest way to add the wrong amount, and this is where it is caught.
MAX_BONUS_PIASTRES = 100_000 * 100

REASON_MAX = 500


def live_bonuses_on(db: Session, payroll_month_id: int | None) -> list[PayrollBonus]:
    """The bonuses a month is paying, oldest first. Withdrawn ones are not."""
    if payroll_month_id is None:
        return []
    return list(
        db.scalars(
            select(PayrollBonus)
            .where(PayrollBonus.payroll_month_id == payroll_month_id)
            .where(PayrollBonus.withdrawn_at.is_(None))
            .order_by(PayrollBonus.id)
        )
    )


def bonus_lines_for(db: Session, affiliate: AffiliateProfile, month: str) -> list[dict]:
    """What the calculation carries: each live bonus's id and amount.

    **No reason, deliberately.** These lines are frozen into the snapshot and
    read by the portal; the reason is staff-only, and the safest way to keep
    it from her screens is never to put it where her screens read.
    """
    payroll_month_id = db.scalar(
        select(PayrollMonth.id)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .where(PayrollMonth.month == month)
    )
    return [
        {"bonus_id": row.id, "amount_piastres": int(row.amount_piastres)}
        for row in live_bonuses_on(db, payroll_month_id)
    ]


def _refuse_unless_open(db: Session, affiliate: AffiliateProfile, month: str) -> None:
    """Why this month cannot take a bonus, as a sentence, or nothing."""
    from app.modules.affiliates.services.payroll import get_month, is_historical, working_month

    if affiliate.account_kind == AccountKind.HOUSE:
        raise ValueError("A house account is never paid, so it cannot have a bonus.")
    if is_historical(month):
        raise ValueError(
            "That month was settled outside the platform, before it went live."
        )
    if month > working_month():
        raise ValueError("A bonus goes on this month or an earlier one, not a future month.")
    payroll_month = get_month(db, affiliate, month)
    if payroll_month is not None and payroll_month.calculation_state != CalculationState.DRAFT:
        raise ValueError(
            f"{affiliate.name}'s {month} is already agreed. Add the bonus to "
            "the current month, or reopen that one first."
        )


def add_bonus(
    db: Session,
    affiliate: AffiliateProfile,
    *,
    month: str,
    amount_piastres: int,
    reason: str | None = None,
    operation_key: str | None = None,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollBonus:
    """Add a bonus to a month nobody has agreed. Takes the money gate.

    A retry carrying the same `operation_key` is handed the bonus the first
    attempt made, rather than paying it twice.
    """
    from app.modules.affiliates.services.money_gate import hold_money_gate
    from app.modules.affiliates.services.payroll import open_month

    month = parse_month(month)
    if isinstance(amount_piastres, bool) or not isinstance(amount_piastres, int):
        raise ValueError("A bonus is an amount in piastres.")
    if amount_piastres <= 0:
        raise ValueError("A bonus has to be more than nothing.")
    if amount_piastres % 100:
        raise ValueError("A bonus is in whole pounds.")
    if amount_piastres > MAX_BONUS_PIASTRES:
        raise ValueError(
            f"A bonus of more than {format_egp(MAX_BONUS_PIASTRES)} is refused. "
            "Check the amount."
        )
    reason = (reason or "").strip() or None
    if reason and len(reason) > REASON_MAX:
        raise ValueError(f"Keep the reason under {REASON_MAX} characters.")

    # Approval reads the bonuses to freeze them. Without the gate a bonus
    # committing between approval's read and its snapshot would be on a month
    # agreed without it - added, and never paid.
    hold_money_gate(db, affiliate)

    if operation_key:
        existing = db.scalar(
            select(PayrollBonus).where(PayrollBonus.operation_key == operation_key)
        )
        if existing is not None:
            if (
                existing.payroll_month.affiliate_id != affiliate.id
                or existing.payroll_month.month != month
                or int(existing.amount_piastres) != amount_piastres
            ):
                raise ValueError("That request was already used for a different bonus.")
            if existing.withdrawn_at is not None:
                # A late retry of a bonus taken back since. Answering it with
                # success would say a bonus is on the month when none is.
                raise ValueError("That bonus was added and then withdrawn. Add it again if it is wanted.")
            return existing

    _refuse_unless_open(db, affiliate, month)
    payroll_month = open_month(db, affiliate, month)

    bonus = PayrollBonus(
        payroll_month_id=payroll_month.id,
        amount_piastres=amount_piastres,
        reason=reason,
        operation_key=operation_key,
        created_by=actor_id,
    )
    db.add(bonus)
    db.flush()
    payroll_month.updated_at = utcnow()

    record_audit(
        db,
        action="payroll.bonus_added",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={"month": month, "bonus_id": bonus.id, "amount_piastres": amount_piastres},
        reason=reason,
    )
    return bonus


def withdraw_bonus(
    db: Session,
    affiliate: AffiliateProfile,
    bonus_id: int,
    *,
    actor_id: int | None = None,
    actor_email: str | None = None,
) -> PayrollBonus:
    """Take a bonus back, while its month is still unagreed. Takes the gate."""
    from app.modules.affiliates.services.money_gate import hold_money_gate

    hold_money_gate(db, affiliate)

    bonus = db.get(PayrollBonus, bonus_id)
    if bonus is None or bonus.payroll_month.affiliate_id != affiliate.id:
        raise LookupError("No such bonus")
    if bonus.withdrawn_at is not None:
        # Already done - the same answer a second click deserves.
        return bonus
    if bonus.payroll_month.calculation_state != CalculationState.DRAFT:
        raise ValueError(
            f"{affiliate.name}'s {bonus.payroll_month.month} is already agreed "
            "with this bonus in it. Reopen the month to take it back."
        )

    bonus.withdrawn_at = utcnow()
    bonus.withdrawn_by = actor_id
    bonus.payroll_month.updated_at = utcnow()
    db.flush()

    record_audit(
        db,
        action="payroll.bonus_withdrawn",
        subject=f"affiliate:{affiliate.id}",
        actor_id=actor_id,
        actor_email=actor_email,
        after={
            "month": bonus.payroll_month.month,
            "bonus_id": bonus.id,
            "amount_piastres": int(bonus.amount_piastres),
        },
    )
    return bonus


def bonuses_for(db: Session, affiliate: AffiliateProfile) -> list[dict]:
    """Every bonus this model has had, newest first, for staff. With reasons."""
    from app.shared.models.identity import UserAccount

    rows = db.execute(
        select(PayrollBonus, PayrollMonth.month, PayrollMonth.calculation_state)
        .join(PayrollMonth, PayrollMonth.id == PayrollBonus.payroll_month_id)
        .where(PayrollMonth.affiliate_id == affiliate.id)
        .order_by(PayrollMonth.month.desc(), PayrollBonus.id.desc())
    ).all()

    people = {
        row.id: (row.display_name or row.email)
        for row in db.execute(
            select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(
                UserAccount.id.in_(
                    {b.created_by for b, *_ in rows if b.created_by}
                    | {b.withdrawn_by for b, *_ in rows if b.withdrawn_by}
                )
            )
        ).all()
    } if rows else {}

    return [
        {
            "id": bonus.id,
            "month": month,
            "amount_piastres": int(bonus.amount_piastres),
            "amount": format_egp(int(bonus.amount_piastres)),
            "reason": bonus.reason,
            "added_by": people.get(bonus.created_by),
            "added_at": bonus.created_at.isoformat(),
            "withdrawn_by": people.get(bonus.withdrawn_by),
            "withdrawn_at": bonus.withdrawn_at.isoformat() if bonus.withdrawn_at else None,
            # Agreed months keep their bonuses; only an open one can be undone.
            "can_withdraw": bonus.withdrawn_at is None and state == CalculationState.DRAFT,
        }
        for bonus, month, state in rows
    ]
