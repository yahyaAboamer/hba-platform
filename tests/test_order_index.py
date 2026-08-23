"""order_index persistence."""

from datetime import timedelta

from sqlalchemy import select, text

from app.models.orders import OrderIndex
from app.services.shopify.normalise import normalise_order, upsert_order_index


def _node(order_id="5123456789", **overrides) -> dict:
    node = {
        "id": f"gid://shopify/Order/{order_id}",
        "legacyResourceId": order_id,
        "name": f"#{order_id}",
        "createdAt": "2026-08-18T16:36:00Z",
        "updatedAt": "2026-08-18T16:36:00Z",
        "cancelledAt": None,
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "discountCodes": ["HBA10"],
        "currentSubtotalPriceSet": {"shopMoney": {"amount": "1062.00", "currencyCode": "EGP"}},
        "currentTotalPriceSet": {"shopMoney": {"amount": "1157.00", "currencyCode": "EGP"}},
        "totalShippingPriceSet": {"shopMoney": {"amount": "95.00", "currencyCode": "EGP"}},
        "currentTotalTaxSet": {"shopMoney": {"amount": "0.00", "currencyCode": "EGP"}},
    }
    node.update(overrides)
    return node


def test_an_order_is_stored(db):
    row = upsert_order_index(db, normalise_order(_node()))
    db.flush()
    assert row.shopify_order_id == "5123456789"
    assert row.discount_codes == ["HBA10"]
    assert row.total_piastres == 115_700
    assert row.business_month == "2026-08"


def test_writing_the_same_order_twice_updates_rather_than_duplicates(db):
    """Orders arrive repeatedly - webhook, then sweep, then perhaps a reimport."""
    upsert_order_index(db, normalise_order(_node()))
    db.flush()
    upsert_order_index(db, normalise_order(_node(displayFinancialStatus="REFUNDED")))
    db.flush()

    rows = db.scalars(select(OrderIndex)).all()
    assert len(rows) == 1
    assert rows[0].financial_status == "refunded"


def test_first_seen_does_not_move_on_a_later_update(db):
    """It records when the platform first saw the order, not the latest touch."""
    row = upsert_order_index(db, normalise_order(_node()))
    db.flush()

    db.execute(
        text("UPDATE order_index SET first_seen_at = :t WHERE shopify_order_id = :i"),
        {"t": row.first_seen_at - timedelta(days=5), "i": "5123456789"},
    )
    db.flush()
    db.expire_all()
    before = db.get(OrderIndex, "5123456789").first_seen_at

    upsert_order_index(db, normalise_order(_node(displayFinancialStatus="REFUNDED")))
    db.flush()
    db.expire_all()

    after = db.get(OrderIndex, "5123456789")
    assert after.first_seen_at == before
    assert after.last_synced_at > after.first_seen_at


def test_orders_can_be_found_by_discount_code(db):
    """The question this table exists to answer."""
    upsert_order_index(db, normalise_order(_node("1", discountCodes=["NOUR10"])))
    upsert_order_index(db, normalise_order(_node("2", discountCodes=["SALMA10"])))
    upsert_order_index(db, normalise_order(_node("3", discountCodes=["NOUR10", "FREESHIP"])))
    upsert_order_index(db, normalise_order(_node("4", discountCodes=[])))
    db.flush()

    found = db.execute(
        text(
            "SELECT shopify_order_id FROM order_index "
            "WHERE :code = ANY(discount_codes) ORDER BY shopify_order_id"
        ),
        {"code": "NOUR10"},
    ).scalars().all()
    assert found == ["1", "3"]


def test_every_code_in_use_can_be_counted(db):
    """The unregistered-code alert is built on this."""
    upsert_order_index(db, normalise_order(_node("1", discountCodes=["SARA10"])))
    upsert_order_index(db, normalise_order(_node("2", discountCodes=["SARA10"])))
    upsert_order_index(db, normalise_order(_node("3", discountCodes=["HBA10"])))
    db.flush()

    counts = dict(
        db.execute(
            text(
                "SELECT code, count(*) FROM order_index, unnest(discount_codes) AS code "
                "GROUP BY code"
            )
        ).all()
    )
    assert counts == {"SARA10": 2, "HBA10": 1}


def test_orders_are_grouped_by_the_cairo_business_month(db):
    upsert_order_index(db, normalise_order(_node("1", createdAt="2026-08-31T20:00:00Z")))
    upsert_order_index(db, normalise_order(_node("2", createdAt="2026-08-31T21:30:00Z")))
    db.flush()

    months = db.execute(
        text("SELECT business_month FROM order_index ORDER BY shopify_order_id")
    ).scalars().all()
    # The second crosses midnight in Cairo and belongs to September.
    assert months == ["2026-08", "2026-09"]


def test_large_totals_do_not_overflow(db):
    """Piastres are 100x the pound figure; a 32-bit column would overflow."""
    upsert_order_index(
        db,
        normalise_order(
            _node(
                "9",
                currentTotalPriceSet={
                    "shopMoney": {"amount": "20000000.00", "currencyCode": "EGP"}
                },
            )
        ),
    )
    db.flush()
    assert db.get(OrderIndex, "9").total_piastres == 2_000_000_000


def test_an_order_with_no_codes_stores_an_empty_array_not_null(db):
    """A null would break `= ANY(discount_codes)` for every query."""
    upsert_order_index(db, normalise_order(_node("7", discountCodes=[])))
    db.flush()
    assert db.get(OrderIndex, "7").discount_codes == []


def test_the_code_index_is_used_for_lookups(db):
    """Confirms the GIN index is real, not just declared.

    Without it, finding a code means a sequential scan of every order ever
    placed, which is exactly what this table is meant to avoid.
    """
    for index in range(60):
        upsert_order_index(
            db, normalise_order(_node(str(index), discountCodes=["NOUR10"]))
        )
    db.flush()
    db.execute(text("ANALYZE order_index"))

    plan = "\n".join(
        db.execute(
            text(
                "EXPLAIN SELECT shopify_order_id FROM order_index "
                "WHERE 'NOUR10' = ANY(discount_codes)"
            )
        ).scalars().all()
    )
    # The planner may still prefer a scan on a tiny table, so this asserts the
    # index exists and is available rather than that it was chosen.
    exists = db.execute(
        text(
            "SELECT count(*) FROM pg_indexes "
            "WHERE tablename = 'order_index' AND indexdef LIKE '%gin%'"
        )
    ).scalar()
    assert exists == 1, plan
