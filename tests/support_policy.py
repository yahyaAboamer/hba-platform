"""Agreeing a month the way the platform agreed one before ADR 0040.

The transition's backlog is months **already approved** under the
delivered-only rule, and a fresh test database has none: every month approved
now is written under the live rule. So a legacy month is born through the
ordinary approval path with the old behaviour restored around it.

Not by editing the row afterwards - `payroll_snapshot` is append-only and the
database refuses an update to it, which is the safeguard working and the
reason this reaches for the code path instead of the data.

Three things made an approval delivered-only, and all three are restored here:
the figure counted delivered orders only, the payload recorded no policy, and
only delivered orders were marked as settled by it. Reproducing fewer than all
three produces a row no real legacy month can be.
"""

from contextlib import contextmanager
from functools import partial

from app.models.attributed_orders import CommissionState
from app.services.commission.calculate import DELIVERED_ONLY


@contextmanager
def approved_before_the_switch():
    from app.services import payroll

    payload, counted = payroll._payload, payroll.COUNTED_STATES
    calculate = payroll.calculate_month

    def without_policy(*args, **kwargs):
        body = payload(*args, **kwargs)
        body.pop("policy", None)
        return body

    payroll._payload = without_policy
    payroll.COUNTED_STATES = (CommissionState.EARNED,)
    payroll.calculate_month = partial(calculate, policy=DELIVERED_ONLY)
    try:
        yield
    finally:
        payroll._payload, payroll.COUNTED_STATES = payload, counted
        payroll.calculate_month = calculate
