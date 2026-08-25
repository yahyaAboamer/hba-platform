"""Writing down whose order this is, and what it is worth.

Phase 4 Task 5. Phase 3's `resolve()` decided and recorded nothing; this is
where the three pure modules meet the database.

It runs inside `upsert_order_index`, so every path that indexes an order
attributes it - webhook, reconciliation sweep, bulk import. A missed
attribution is not a visible failure: the order belongs to nobody, quietly,
until someone notices the sales are missing.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.commission.attribute import attribute_order
from app.services.shopify.fulfilment import DELIVERED, FAILED, IN_FLIGHT
from app.services.shopify.normalise import upsert_order_index

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

PAID = 115_700
SHIPPING = 9_500
EXPECTED_BASE = 106_200


def _affiliate(db, name="Nour", code="NOUR10", kind=AccountKind.MODEL):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=kind
    )
    if code:
        register_code(db, affiliate, code, "2026-01")
    return affiliate


def _order(db, order_id="1", codes=("NOUR10",), month="2026-04", **extra):
    values = {
        "shopify_order_id": order_id,
        "order_number": f"#{order_id}",
        "placed_at": datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
        "business_month": month,
        "discount_codes": list(codes),
        "subtotal_piastres": EXPECTED_BASE,
        "total_piastres": PAID,
        "shipping_piastres": SHIPPING,
        "tax_piastres": 0,
        "currency": "EGP",
        "delivery_state": DELIVERED,
        "delivered_at": datetime(2026, 4, 20, 10, tzinfo=timezone.utc),
        **extra,
    }
    row = OrderIndex(**values)
    db.add(row)
    db.flush()
    return row


# ── The ordinary path ──────────────────────────────────────────────────────────


def test_an_order_with_one_registered_code_becomes_hers(db):
    affiliate = _affiliate(db)
    order = _order(db)

    row = attribute_order(db, order)

    assert row is not None
    assert row.affiliate_id == affiliate.id
    assert row.commission_base_piastres == EXPECTED_BASE
    assert row.business_month == "2026-04"


def test_a_delivered_order_is_earned_and_pays(db):
    _affiliate(db)
    row = attribute_order(db, _order(db))

    assert row.commission_state == CommissionState.EARNED
    assert row.counts_toward_payout is True


def test_an_order_still_travelling_is_pending(db):
    _affiliate(db)
    row = attribute_order(db, _order(db, delivery_state=IN_FLIGHT, delivered_at=None))

    assert row.commission_state == CommissionState.PENDING
    assert row.counts_toward_payout is False


def test_a_failed_delivery_is_void(db):
    _affiliate(db)
    row = attribute_order(db, _order(db, delivery_state=FAILED, delivered_at=None))

    assert row.commission_state == CommissionState.VOID


def test_an_order_nobody_owns_is_left_alone(db):
    """Indexed and belonging to nobody. Not an error - it is what an
    unregistered code looks like.
    """
    order = _order(db, codes=("UNKNOWN10",))

    assert attribute_order(db, order) is None
    assert db.get(AttributedOrder, order.shopify_order_id) is None


# ── Held, rather than guessed ──────────────────────────────────────────────────


def test_two_registered_codes_write_nothing_and_say_so(db, caplog):
    """§9.2. The order waits for a human rather than silently paying the wrong
    person or paying twice.
    """
    _affiliate(db, "Nour", "NOUR10")
    _affiliate(db, "Sara", "SARA10")
    order = _order(db, codes=("NOUR10", "SARA10"))

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        assert attribute_order(db, order) is None

    assert db.get(AttributedOrder, order.shopify_order_id) is None
    assert "ANOMALY attribution_held" in caplog.text
    assert "NOUR10,SARA10" in caplog.text


def test_a_finished_return_changes_nothing(db):
    """ADR 0025. The parcel arrived, so the sale is hers. What the customer did
    afterwards is between them and HBA - read, stored, and not acted on.
    """
    _affiliate(db)
    order = _order(db, return_status="RETURNED", return_activity=True, return_open=False)

    row = attribute_order(db, order)

    assert row.commission_state == CommissionState.EARNED
    assert row.counts_toward_payout is True
    assert row.return_status == "RETURNED", "the fact is still recorded"


def test_an_open_return_on_a_delivered_order_changes_nothing_either(db):
    """There is no longer a state where a delivered order goes back to pending.
    Earned is terminal.
    """
    _affiliate(db)
    order = _order(
        db, return_status="IN_PROGRESS", return_activity=True, return_open=True
    )

    row = attribute_order(db, order)

    assert row.commission_state == CommissionState.EARNED


def test_a_return_before_delivery_still_leaves_it_pending(db):
    """Nothing has arrived, so nothing is settled."""
    _affiliate(db)
    order = _order(
        db,
        delivery_state=IN_FLIGHT,
        delivered_at=None,
        return_status="IN_PROGRESS",
        return_activity=True,
        return_open=True,
    )

    row = attribute_order(db, order)

    assert row.commission_state == CommissionState.PENDING


# ── What it refuses to do ──────────────────────────────────────────────────────


def test_an_order_is_never_moved_to_another_model(db, caplog):
    """§9.2 and §17. The trigger would refuse it; this reports **why**, rather
    than letting an IntegrityError surface somewhere unrelated.
    """
    nour = _affiliate(db, "Nour", "NOUR10")
    order = _order(db)
    attribute_order(db, order)

    # The code is handed to Sara for the same month - a registration mistake.
    sara = _affiliate(db, "Sara", None)
    from app.models.codes import DiscountCodePeriod

    db.query(DiscountCodePeriod).filter_by(code="NOUR10").update(
        {"affiliate_id": sara.id}
    )
    db.flush()

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        row = attribute_order(db, order)

    assert row.affiliate_id == nour.id, "the order moved"
    assert "ANOMALY attribution_conflict" in caplog.text


def test_a_delivered_order_is_never_recalculated(db):
    """ADR 0025. A late webhook carrying an exchange's edited subtotal would
    otherwise rewrite a figure a payroll has already been approved on - and it
    holds from the moment of delivery, not ten days later.
    """
    _affiliate(db)
    order = _order(db)
    attribute_order(db, order)

    order.total_piastres = 999_999
    db.flush()
    row = attribute_order(db, order)

    assert row.commission_base_piastres == EXPECTED_BASE


def test_an_order_still_travelling_is_recalculated(db):
    """A genuine edit before it ships should be reflected."""
    _affiliate(db)
    order = _order(db, delivery_state=IN_FLIGHT, delivered_at=None)
    attribute_order(db, order)

    order.total_piastres = PAID + 10_000
    db.flush()
    row = attribute_order(db, order)

    assert row.commission_base_piastres == EXPECTED_BASE + 10_000


def test_losing_its_codes_does_not_un_attribute_an_order(db):
    """Orders do not move between models, and that includes moving to nobody."""
    affiliate = _affiliate(db)
    order = _order(db)
    attribute_order(db, order)

    order.discount_codes = []
    db.flush()
    row = attribute_order(db, order)

    assert row is not None
    assert row.affiliate_id == affiliate.id


# ── Every ingestion path attributes ────────────────────────────────────────────


def test_indexing_an_order_attributes_it(db):
    """The hook is inside `upsert_order_index`, so webhook, sweep and bulk
    import all attribute. Hooking the three call sites separately would work
    until somebody added a fourth.
    """
    affiliate = _affiliate(db)

    upsert_order_index(
        db,
        {
            "shopify_order_id": "7001",
            "order_number": "#7001",
            "placed_at": datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
            "business_month": "2026-04",
            "discount_codes": ["NOUR10"],
            "subtotal_piastres": EXPECTED_BASE,
            "total_piastres": PAID,
            "shipping_piastres": SHIPPING,
            "tax_piastres": 0,
            "currency": "EGP",
            "delivery_state": DELIVERED,
        },
    )

    row = db.get(AttributedOrder, "7001")
    assert row is not None
    assert row.affiliate_id == affiliate.id
    assert row.commission_base_piastres == EXPECTED_BASE


def test_re_indexing_the_same_order_does_not_double_write(db):
    """Orders arrive more than once - a webhook, then a sweep, then perhaps a
    re-import.
    """
    _affiliate(db)
    values = {
        "shopify_order_id": "7002",
        "order_number": "#7002",
        "placed_at": datetime(2026, 4, 15, 12, tzinfo=timezone.utc),
        "business_month": "2026-04",
        "discount_codes": ["NOUR10"],
        "subtotal_piastres": EXPECTED_BASE,
        "total_piastres": PAID,
        "shipping_piastres": SHIPPING,
        "tax_piastres": 0,
        "currency": "EGP",
        "delivery_state": DELIVERED,
    }

    upsert_order_index(db, values)
    upsert_order_index(db, values)

    rows = db.query(AttributedOrder).filter_by(shopify_order_id="7002").all()
    assert len(rows) == 1


def test_a_house_account_is_attributed_but_not_payable(db):
    """HBA10 is a real code used by real customers and needs a working
    dashboard. Reporting its orders as unattributed would be a different and
    wrong answer; excluding it from payable totals is Task 7's job.
    """
    house = _affiliate(db, "House", "HBA10", kind=AccountKind.HOUSE)
    order = _order(db, codes=("HBA10",))

    row = attribute_order(db, order)

    assert row.affiliate_id == house.id
    assert row.commission_state == CommissionState.EARNED
