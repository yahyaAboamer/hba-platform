"""Read-only: records a model has in months her month list does not offer.

The admin profile's month control offers a model only her own months
(`months_for`, the rule her portal uses), as the approved export does. This
lists any model whose attributed orders or payroll records fall outside those
months, so a real case can be reported rather than every model's list being
widened on speculation. It writes nothing.

    DATABASE_URL=... .venv/Scripts/python.exe docs/repair/batch-2/visual/outside_months.py
"""
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.affiliates import AffiliateProfile
from app.models.attributed_orders import AttributedOrder
from app.models.payroll import PayrollMonth
from app.services.portal import months_for

with SessionLocal() as db:
    found = 0
    for a in db.scalars(select(AffiliateProfile).order_by(AffiliateProfile.id)):
        months = set(months_for(db, a))
        orders = db.execute(
            select(AttributedOrder.business_month, func.count())
            .where(AttributedOrder.affiliate_id == a.id)
            .group_by(AttributedOrder.business_month)
        ).all()
        payroll = db.scalars(select(PayrollMonth.month).where(PayrollMonth.affiliate_id == a.id)).all()
        out_orders = [(m, n) for m, n in orders if m not in months]
        out_payroll = [m for m in payroll if m not in months]
        if out_orders or out_payroll:
            found += 1
            print(
                f"affiliate {a.id} start={a.collaboration_start_month} "
                f"offered={min(months)}..{max(months)} "
                f"orders_outside={out_orders} payroll_outside={out_payroll}"
            )
    print(f"models with records outside their months: {found}")
