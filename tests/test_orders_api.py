"""The order index, over HTTP. Read-only.

No test here asserts that any figure changes, because nothing on this router
can change one. What is asserted is that the four ways an order can end up
here - attributed, unattributed, held, carried - each read correctly, since
those are facts `attributed_order` alone cannot show: an unattributed or held
order has no row there at all.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
MONTH = "2026-04"


@pytest.fixture()
def anonymous(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _make_account(email: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Model') RETURNING id"
            ),
            {"e": email, "p": hash_password("quiet-harbour-lantern")},
        ).scalar_one()


def _affiliate(client, name="Nour", email="nour@example.com", **extra) -> dict:
    body = {"user_account_id": _make_account(email), "name": name, **extra}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _register_code(client, affiliate_id, code, start_month="2026-01"):
    """A registered code, written straight in.

    Registering through the API calls Shopify to verify the code exists
    (§10.4); this file is about what the order screen reports given a
    registry, not about verification, so it writes the row the way the
    other helpers here write `order_index` and `attributed_order` directly.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO discount_code_period "
                "(affiliate_id, code, start_month, shopify_verified_at) "
                "VALUES (:a, :c, :m, now())"
            ),
            {"a": affiliate_id, "c": code, "m": start_month},
        )


def _order_index(order_id, codes, *, month=MONTH, base=100_000, cancelled=False):
    """A raw `order_index` row, with no attribution decided yet.

    Written straight in, the way an import would leave it before attribution
    runs - which is exactly the state this router has to be able to describe.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency, cancelled_at) "
                "VALUES (:i, :n, now(), :m, :codes, :b, :b, 0, 0, 'EGP', "
                + ("now()" if cancelled else "NULL")
                + ")"
            ),
            {"i": order_id, "n": f"#{order_id}", "m": month, "codes": codes, "b": base},
        )


def _paid_order(affiliate_id, order_id, base, *, month=MONTH, state="earned",
                 codes=None, settled_in=None):
    _order_index(order_id, codes or ["NOUR10"], month=month, base=base)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO attributed_order (shopify_order_id, affiliate_id, "
                "business_month, commission_base_piastres, commission_state, "
                "settled_in_snapshot_id) "
                "VALUES (:i, :a, :m, :b, :s, :snap)"
            ),
            {
                "i": order_id,
                "a": affiliate_id,
                "m": month,
                "b": base,
                "s": state,
                "snap": settled_in,
            },
        )


# ── Permission ───────────────────────────────────────────────────────────────


def test_anonymous_access_is_refused(anonymous):
    assert anonymous.get(f"/api/orders/{MONTH}").status_code == 401


def test_an_affiliate_cannot_read_the_order_index(client):
    """§6.5's boundary, checked here too: this is not their screen."""
    _demote_to("affiliate")
    assert client.get(f"/api/orders/{MONTH}").status_code == 403


# ── The four outcomes ────────────────────────────────────────────────────────


def test_an_attributed_order_shows_who_it_belongs_to(client):
    nour = _affiliate(client)
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-1", 240_000)

    body = client.get(f"/api/orders/{MONTH}").json()

    assert len(body["orders"]) == 1
    row = body["orders"][0]
    assert row["outcome"] == "attributed"
    assert row["affiliate_id"] == nour["id"]
    assert row["affiliate_name"] == "Nour"
    assert row["base_piastres"] == 240_000
    assert row["commission_state"] == "earned"


def test_an_unattributed_order_has_no_owner_and_no_figure(client):
    """No registered code matched. Indexed, real, and paid to nobody - a
    zero here would be a different and wrong answer (app/services/attribution.py).
    """
    _order_index("o-2", [])

    row = client.get(f"/api/orders/{MONTH}").json()["orders"][0]

    assert row["outcome"] == "unattributed"
    assert row["affiliate_id"] is None
    assert row["base_piastres"] is None


def test_a_held_order_names_every_code_that_conflicted(client):
    """§9.2. Two registered codes on one order. A human decides, and cannot
    decide a conflict without knowing what conflicted.
    """
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _register_code(client, sara["id"], "SARA10")
    _order_index("o-3", ["NOUR10", "SARA10"])

    row = client.get(f"/api/orders/{MONTH}").json()["orders"][0]

    assert row["outcome"] == "held"
    assert row["affiliate_id"] is None
    assert sorted(row["matched_codes"]) == ["NOUR10", "SARA10"]


def test_a_carried_order_says_which_payroll_actually_paid_it(client):
    """§11.4. `attributed_order.settled_in_snapshot_id` names a snapshot, not a
    month - the screen has to walk from one to the other to say anything a
    person can read.
    """
    nour = _affiliate(client)
    _register_code(client, nour["id"], "NOUR10")

    with engine.begin() as connection:
        payroll_month_id = connection.execute(
            text(
                "INSERT INTO payroll_month (affiliate_id, month, calculation_state) "
                "VALUES (:a, '2026-05', 'approved') RETURNING id"
            ),
            {"a": nour["id"]},
        ).scalar_one()
        snapshot_id = connection.execute(
            text(
                "INSERT INTO payroll_snapshot (payroll_month_id, version, "
                "payload_json, content_hash, approved_obligation_piastres, "
                "exact_unrounded_piastres) "
                "VALUES (:m, 1, '{}', 'x', 24000, '24000') RETURNING id"
            ),
            {"m": payroll_month_id},
        ).scalar_one()
        connection.execute(
            text(
                "UPDATE payroll_month SET active_snapshot_id = :s WHERE id = :m"
            ),
            {"s": snapshot_id, "m": payroll_month_id},
        )

    # Placed in April, paid by May's payroll.
    _paid_order(nour["id"], "o-4", 240_000, month=MONTH, settled_in=snapshot_id)

    row = client.get(f"/api/orders/{MONTH}").json()["orders"][0]

    assert row["is_carried"] is True
    assert row["paid_in_month"] == "2026-05"
    assert row["business_month"] == MONTH


def test_an_order_paid_by_its_own_month_is_not_called_carried(client):
    """Settled, but by the month it belongs to. That is the ordinary case, not
    carry-forward, and must not be flagged as one.
    """
    nour = _affiliate(client)
    _register_code(client, nour["id"], "NOUR10")

    with engine.begin() as connection:
        payroll_month_id = connection.execute(
            text(
                "INSERT INTO payroll_month (affiliate_id, month, calculation_state) "
                f"VALUES (:a, '{MONTH}', 'approved') RETURNING id"
            ),
            {"a": nour["id"]},
        ).scalar_one()
        snapshot_id = connection.execute(
            text(
                "INSERT INTO payroll_snapshot (payroll_month_id, version, "
                "payload_json, content_hash, approved_obligation_piastres, "
                "exact_unrounded_piastres) "
                "VALUES (:m, 1, '{}', 'x', 24000, '24000') RETURNING id"
            ),
            {"m": payroll_month_id},
        ).scalar_one()

    _paid_order(nour["id"], "o-5", 240_000, settled_in=snapshot_id)

    row = client.get(f"/api/orders/{MONTH}").json()["orders"][0]

    assert row["is_carried"] is False
    assert row["paid_in_month"] == MONTH


# ── Totals ───────────────────────────────────────────────────────────────────


def test_totals_count_each_outcome(client):
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _register_code(client, sara["id"], "SARA10")
    _paid_order(nour["id"], "o-1", 100_000)
    _order_index("o-2", [])
    # Held: two *registered* codes on one order. A code that matches nothing,
    # like a typo, does not hold an order - it just leaves it attributed to
    # whichever registered code is actually on it.
    _order_index("o-3", ["NOUR10", "SARA10"])

    body = client.get(f"/api/orders/{MONTH}").json()

    assert body["totals"] == {
        "orders": 3,
        "held": 1,
        "unattributed": 1,
        "carried": 0,
        # *N orders - EGP X counted*, the line the approved list heads itself
        # with: every order here was delivered, so all three count.
        "counted_piastres": body["totals"]["counted_piastres"],
        "counted": body["totals"]["counted"],
    }


def test_a_month_with_nothing_is_not_an_error(client):
    body = client.get(f"/api/orders/{MONTH}").json()
    assert body["orders"] == []
    assert body["totals"]["orders"] == 0


def test_an_invalid_month_is_refused(client):
    assert client.get("/api/orders/not-a-month").status_code == 400


# ── Looking one order up by number ──────────────────────────────────────────


def test_finding_an_order_by_its_number(client):
    nour = _affiliate(client)
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-9", 100_000)

    row = client.get("/api/orders/lookup/9").json()

    assert row["outcome"] == "attributed"
    assert row["order_number"] == "#o-9"


def test_finding_an_order_by_number_with_the_hash(client):
    """Support pastes what Shopify shows, which includes the #."""
    nour = _affiliate(client)
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-9", 100_000)

    row = client.get("/api/orders/lookup/%23o-9").json()

    assert row["order_number"] == "#o-9"


def test_a_number_matching_nothing_is_a_404(client):
    response = client.get("/api/orders/lookup/does-not-exist")
    assert response.status_code == 404


# -- One order, opened (the approved export's order view) ---------------------


def test_an_order_opens_with_its_model_and_lines(client):
    """The view the approved list opens into: whose it is and what was in it."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-9", 100_000)

    body = client.get("/api/orders/detail/o-9").json()

    assert body["affiliate_id"] == nour["id"]
    assert body["outcome"] == "attributed"
    assert body["lines"] == []
    # A figure or an explicit absence, never a missing key the screen would
    # have to guess about.
    assert "commission_piastres" in body


def test_an_unknown_order_is_a_404_not_an_empty_view(client):
    assert client.get("/api/orders/detail/nope").status_code == 404


def test_the_month_counts_what_did_not_fail(client):
    """*N orders - EGP X counted*: a failed parcel was never sales."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-10", 100_000)

    body = client.get(f"/api/orders/{MONTH}").json()

    assert body["totals"]["counted_piastres"] == sum(
        row["total_piastres"]
        for row in body["orders"]
        if not row["cancelled"] and row["delivery_state"] != "failed"
    )


def test_a_pending_order_opens_with_the_commission_it_counts_for(client):
    """The staff view of one order tells the story her own row does
    (`month_rule`): EGP 2,000 on its way at 10% is EGP 200 (ADR 0040)."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    response = client.put(
        f"/api/affiliates/{nour['id']}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "compensation_type": "commission",
                    "commission_rate_bp": 1000,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    _paid_order(nour["id"], "o-11", 200_000, state="pending")

    body = client.get("/api/orders/detail/o-11").json()

    assert body["commission_piastres"] == 20_000


def _terms(client, affiliate_id, rate_bp=1000):
    response = client.put(
        f"/api/affiliates/{affiliate_id}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "compensation_type": "commission",
                    "commission_rate_bp": rate_bp,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text


def _facts(order_id, **columns):
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE order_index SET {assignments} WHERE shopify_order_id = :i"),
            {"i": order_id, **columns},
        )


def test_a_failed_delivery_opens_as_failed_and_earned_nothing(client):
    """The approved order view: *Failed delivery*, commission EGP 0.00."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _terms(client, nour["id"])
    _paid_order(nour["id"], "o-12", 200_000, state="void")
    _facts("o-12", delivery_state="failed")

    body = client.get("/api/orders/detail/o-12").json()

    assert body["status"] == "failed"
    assert body["commission_piastres"] == 0


def test_a_cancelled_order_is_not_called_a_failed_delivery(client):
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _paid_order(nour["id"], "o-13", 0, state="void")
    _facts("o-13", cancelled_at=datetime(2026, 8, 3, tzinfo=timezone.utc))

    body = client.get("/api/orders/detail/o-13").json()

    assert body["status"] == "cancelled"


def test_delivered_then_cancelled_still_opens_as_delivered(client):
    """F04: it counts, so it must not read *Cancelled* beside *Counted in*."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _register_code(client, nour["id"], "NOUR10")
    _terms(client, nour["id"])
    _paid_order(nour["id"], "o-14", 200_000, state="earned")
    _facts(
        "o-14",
        delivery_state="delivered",
        cancelled_at=datetime(2026, 8, 20, tzinfo=timezone.utc),
        financial_status="refunded",
    )

    body = client.get("/api/orders/detail/o-14").json()

    assert body["status"] == "delivered"
    assert body["commission_piastres"] == 20_000
