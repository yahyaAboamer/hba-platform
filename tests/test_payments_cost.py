"""What the month-end payments screen costs to draw.

06A review. The screen gained two things that each run the commission engine:
a forecast for every unapproved month, and a scan for open corrections across
every payable model. Both read perfectly well and neither is visible on a
seeded database with three models and one month.

Counts SQL statements rather than timing anything: a timing test on a laptop
proves nothing, and the failure being guarded is a **shape** - the cost growing
with models multiplied by months, on the one screen that is opened with every
model in front of you at month end.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.compensation import set_terms

MONTHS = ["2026-0{}".format(n) for n in range(1, 9)]
WORKING = "2026-08"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: WORKING, raising=True
    )


def _model(db, name):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=AccountKind.MODEL
    )
    register_code(db, affiliate, f"{name.upper()}10", "2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    affiliate.collaboration_start_month = "2026-01"
    db.flush()
    return affiliate


def _order(db, affiliate, order_id, month):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 3, 2, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=[f"{affiliate.name.upper()}10"],
            subtotal_piastres=200_000,
            total_piastres=200_000,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
        )
    )
    db.flush()
    db.add(
        AttributedOrder(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            business_month=month,
            commission_base_piastres=200_000,
            commission_state=CommissionState.EARNED,
        )
    )
    db.flush()


def _count(db, work):
    seen: list[str] = []

    def watch(conn, cursor, statement, *rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", watch)
    try:
        work()
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", watch)
    return seen


def test_the_correction_scan_does_not_cost_a_calculation_per_month_per_model(db):
    """The guard against the month-end screen getting slower every month.

    `open_corrections` walks every month a model can see and runs
    `correction_for` on each, and `correction_for` runs the whole commission
    engine. Multiplied by every payable model on the payments screen, that is
    models times months full calculations for one page.

    A correction is only possible on an **approved** month, and approved months
    are a small and knowable set. Walking the unapproved ones is work whose
    answer is always `None`.
    """
    from app.services.corrections import open_corrections

    affiliate = _model(db, "Nour")
    for index, month in enumerate(MONTHS):
        _order(db, affiliate, f"n{index}", month)

    seen = _count(db, lambda: open_corrections(db, affiliate))

    # Eight months, none of them approved. This should cost a bounded look at
    # what is approved, not a full calculation of all eight.
    assert len(seen) <= 12, (
        f"{len(seen)} queries for eight unapproved months:\n"
        + "\n".join(seen[:20])
    )


def test_an_approved_history_costs_a_calculation_for_every_month_of_it(db):
    """**Measured at nine queries per approved month, and left that way.**

    An unapproved month exits cheaply - `correction_for` checks the snapshot
    before it calculates anything - so a new model costs almost nothing. Once
    months start closing it is different: a correction can only exist on an
    approved month, and deciding whether one exists means running the whole
    commission engine against the frozen snapshot.

    At month end the payments screen does this for every payable model. Twenty
    models with eight approved months each is around 1,400 queries for one page
    load, and it grows with both numbers.

    ## Why it was measured and not optimised

    The obvious gate - skip the calculation unless an order changed since
    approval - is **wrong**. The fingerprint also covers her terms and her
    target outcome, so a corrected rate or a recorded target moves it without
    touching any order. A gate that missed those would silently stop reporting
    real corrections, and a missed correction is far worse than a slow screen.

    A correct gate is possible and is real work. At twenty models this is about
    a second, so the number is pinned here instead, where it fails loudly if it
    gets materially worse before somebody does that work.
    """
    from app.services.corrections import open_corrections
    from app.services.payroll import approve_month

    affiliate = _model(db, "Sara")
    for index, month in enumerate(MONTHS):
        _order(db, affiliate, f"s{index}", month)
        approve_month(db, affiliate, month)

    seen = _count(db, lambda: open_corrections(db, affiliate))

    # Eight approved months. Recorded so the cost per approved month is visible
    # rather than inferred: this is the number that multiplies by every model
    # on the month-end screen.
    per_month = len(seen) / len(MONTHS)
    assert per_month < 20, (
        f"{len(seen)} queries for {len(MONTHS)} approved months "
        f"({per_month:.1f} each)"
    )
    print(f"\nqueries for {len(MONTHS)} approved months: {len(seen)} "
          f"({per_month:.1f} per month)")
