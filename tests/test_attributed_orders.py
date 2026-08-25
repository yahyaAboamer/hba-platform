"""The table where money begins, and the two fields that never move.

Spec §9.2, §9.4, §10.2, §17. Phase 3 decided *whose* order this is; this is
where that decision is written down and made permanent.

Two invariants are enforced by the database rather than by care:

    affiliate_id    - orders never move between models (§9.2, §17)
    business_month  - the month it was placed, never recomputed (ADR 0005)

Both are the same failure in different clothes: a month that was already
calculated silently disagreeing with itself afterwards.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import (
    VALID_COMMISSION_STATES,
    AttributedOrder,
    CommissionState,
)
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate


def _affiliate(db, name="Nour", kind=AccountKind.MODEL):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name, account_kind=kind)


def _order(db, order_id="1", codes=("NOUR10",), month="2026-04"):
    row = OrderIndex(
        shopify_order_id=order_id,
        order_number=f"#{order_id}",
        placed_at=f"{month}-15T12:00:00+00:00",
        business_month=month,
        discount_codes=list(codes),
        subtotal_piastres=106_200,
        total_piastres=115_700,
        shipping_piastres=9_500,
        tax_piastres=0,
        currency="EGP",
    )
    db.add(row)
    db.flush()
    return row


def _attribute(db, order, affiliate, **extra):
    values = {
        "shopify_order_id": order.shopify_order_id,
        "affiliate_id": affiliate.id,
        "business_month": order.business_month,
        "commission_base_piastres": 106_200,
        "commission_state": CommissionState.PENDING,
        **extra,
    }
    row = AttributedOrder(**values)
    db.add(row)
    db.flush()
    return row


# ── A row existing means the order is attributed ───────────────────────────────


def test_an_attributed_order_records_what_the_sale_is_worth(db):
    """The whole point of the second tier: order_index says a sale happened,
    this says what it is worth and to whom.
    """
    affiliate = _affiliate(db)
    order = _order(db)

    row = _attribute(db, order, affiliate)

    assert row.affiliate_id == affiliate.id
    assert row.commission_base_piastres == 106_200
    assert row.business_month == "2026-04"
    assert row.commission_state == CommissionState.PENDING


def test_there_is_no_such_thing_as_an_attributed_order_with_no_affiliate(db):
    """An unattributed order is an order_index row with nothing here. Allowing
    a null affiliate would duplicate order_index at nine times the cost and
    leave every future reader a column that is usually empty.
    """
    order = _order(db)

    db.add(
        AttributedOrder(
            shopify_order_id=order.shopify_order_id,
            affiliate_id=None,
            business_month=order.business_month,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_an_order_can_only_be_attributed_once(db):
    """The order id is the primary key. Two rows for one order would be two
    people paid for one sale.
    """
    first = _affiliate(db, "Nour")
    second = _affiliate(db, "Sara")
    order = _order(db)
    _attribute(db, order, first)

    db.add(
        AttributedOrder(
            shopify_order_id=order.shopify_order_id,
            affiliate_id=second.id,
            business_month=order.business_month,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_an_order_that_shopify_never_indexed_cannot_be_attributed(db):
    """The foreign key makes the thin row and the financial row the same order
    by construction, not by a join key somebody remembers to maintain.
    """
    affiliate = _affiliate(db)

    db.add(
        AttributedOrder(
            shopify_order_id="does-not-exist",
            affiliate_id=affiliate.id,
            business_month="2026-04",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── The two frozen fields ──────────────────────────────────────────────────────


def test_an_order_never_moves_to_another_model(db):
    """§9.2 and §17. Reassigning an order would change what an already
    calculated month was worth, and the month would disagree with itself.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    order = _order(db)
    _attribute(db, order, nour)
    db.commit()

    with pytest.raises(DBAPIError) as caught:
        db.execute(
            text(
                "UPDATE attributed_order SET affiliate_id = :new "
                "WHERE shopify_order_id = :id"
            ),
            {"new": sara.id, "id": order.shopify_order_id},
        )
    assert "never move between models" in str(caught.value)
    db.rollback()


def test_an_orders_month_never_shifts(db):
    """Moving an order's business month moves money between payroll periods -
    the same failure as reassigning it, wearing a different hat.
    """
    affiliate = _affiliate(db)
    order = _order(db, month="2026-04")
    _attribute(db, order, affiliate)
    db.commit()

    with pytest.raises(DBAPIError) as caught:
        db.execute(
            text(
                "UPDATE attributed_order SET business_month = '2026-05' "
                "WHERE shopify_order_id = :id"
            ),
            {"id": order.shopify_order_id},
        )
    assert "move money between months" in str(caught.value)
    db.rollback()


def test_writing_the_same_affiliate_back_is_not_a_move(db):
    """A recalculation that rewrites every column must not fail because one of
    them happens to already hold the right value.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    row = _attribute(db, order, affiliate)
    db.commit()

    db.execute(
        text(
            "UPDATE attributed_order SET affiliate_id = :same, "
            "commission_state = 'earned' WHERE shopify_order_id = :id"
        ),
        {"same": affiliate.id, "id": order.shopify_order_id},
    )
    db.commit()
    db.refresh(row)
    assert row.commission_state == CommissionState.EARNED


# ── What is deliberately not frozen ────────────────────────────────────────────


def test_the_base_and_state_move_freely(db):
    """This table is not append-only. An order edited before it ships should
    reflect the edit, and its state changes as the parcel travels.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    row = _attribute(db, order, affiliate)
    db.commit()

    row.commission_base_piastres = 98_000
    row.commission_state = CommissionState.EARNED
    row.refunded_merchandise_piastres = 8_200
    db.commit()
    db.refresh(row)

    assert row.commission_base_piastres == 98_000
    assert row.commission_state == CommissionState.EARNED
    assert row.refunded_merchandise_piastres == 8_200


def test_a_row_can_be_deleted_outright(db):
    """Not append-only means exactly that. An order wrongly attributed - a code
    registered to the wrong model, caught the same day - is removed and
    re-attributed, rather than corrected in place into somebody else's name.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    _attribute(db, order, affiliate)
    db.commit()

    db.execute(
        text("DELETE FROM attributed_order WHERE shopify_order_id = :id"),
        {"id": order.shopify_order_id},
    )
    db.commit()
    assert db.get(AttributedOrder, order.shopify_order_id) is None


# ── Guards on the values themselves ────────────────────────────────────────────


@pytest.mark.parametrize("state", sorted(VALID_COMMISSION_STATES))
def test_every_declared_state_is_accepted_by_the_database(db, state):
    """The constants and the CHECK constraint must not drift apart. If they do,
    the code writes a state the database rejects - discovered in production.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    row = _attribute(db, order, affiliate, commission_state=state)
    db.commit()
    assert row.commission_state == state


def test_a_state_nobody_defined_is_refused(db):
    affiliate = _affiliate(db)
    order = _order(db)

    with pytest.raises(IntegrityError):
        _attribute(db, order, affiliate, commission_state="probably_fine")


def test_a_negative_base_is_refused(db):
    """A refund larger than the order would otherwise produce one, and a
    negative base would quietly subtract from everything else she earned.
    """
    affiliate = _affiliate(db)
    order = _order(db)

    with pytest.raises(IntegrityError):
        _attribute(db, order, affiliate, commission_base_piastres=-1)


def test_only_earned_counts_toward_a_payout(db):
    """§9.4. Pending is shown separately rather than hidden, so a model can see
    what is coming; void counts for nothing.
    """
    affiliate = _affiliate(db)

    states = {}
    for index, state in enumerate(sorted(VALID_COMMISSION_STATES)):
        order = _order(db, order_id=str(100 + index))
        states[state] = _attribute(db, order, affiliate, commission_state=state)

    assert states[CommissionState.EARNED].counts_toward_payout is True
    assert states[CommissionState.PENDING].counts_toward_payout is False
    assert states[CommissionState.VOID].counts_toward_payout is False


def test_a_frozen_base_is_recognisable_as_frozen(db):
    """base_frozen_at records **when**, not merely whether. "Was this frozen
    before or after the exchange opened?" is a question a boolean cannot
    answer, and Task 3 has to answer it.
    """
    from app.core.businesstime import utcnow

    affiliate = _affiliate(db)
    order = _order(db)
    row = _attribute(db, order, affiliate)

    assert row.is_frozen is False
    row.base_frozen_at = utcnow()
    db.flush()
    assert row.is_frozen is True


# ── What happens to the row when its neighbours go ─────────────────────────────


def test_the_row_dies_with_its_order(db):
    """If an order is removed from the index, its financial detail has nothing
    left to describe.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    _attribute(db, order, affiliate)
    db.commit()

    db.execute(
        text("DELETE FROM order_index WHERE shopify_order_id = :id"),
        {"id": order.shopify_order_id},
    )
    db.commit()
    assert db.get(AttributedOrder, order.shopify_order_id) is None


def test_an_affiliate_with_earnings_cannot_be_deleted_out_from_under_them(db):
    """RESTRICT, where discount_code_period cascades. A code period is a fact
    about arrangement and can go with the affiliate; this is a fact about
    money. Affiliates are archived rather than deleted, so this should never
    fire - which is exactly when a guard earns its place.
    """
    affiliate = _affiliate(db)
    order = _order(db)
    _attribute(db, order, affiliate)
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(
            text("DELETE FROM affiliate_profile WHERE id = :id"), {"id": affiliate.id}
        )
        db.flush()
    db.rollback()
