"""What a month is worth, over HTTP.

Phase 4 Task 8, and the read side of the commission engine.

Nothing here freezes a figure. Approving a month is Phase 6's job, and doing it
on a GET would mean a month could be settled by whoever happened to load a page.
Every payout comes back marked provisional.

§6.5: a model may never touch anything deciding what she is owed. The
`affiliate` role holds no permissions at all, so it is refused here as
everywhere - proven per endpoint, not assumed.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}
MONTH = "2026-04"


@pytest.fixture()
def anonymous(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client(fresh_database):
    """Signed in as the administrator."""
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
            {"e": email, "p": hash_password("a-long-enough-password")},
        ).scalar_one()


def _affiliate(client, name="Nour", email="nour@example.com", **extra) -> dict:
    body = {"user_account_id": _make_account(email), "name": name, **extra}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _terms(client, affiliate_id, rate_bp=1000, **extra):
    body = {
        "start_month": "2026-01",
        "compensation_type": "commission",
        "commission_rate_bp": rate_bp,
        **extra,
    }
    response = client.post(f"/api/affiliates/{affiliate_id}/compensation", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _paid_order(affiliate_id, order_id, base, *, month=MONTH, state="earned"):
    """An order already attributed, written straight in.

    The paths that produce these are covered by their own tests; this file is
    about what the endpoints report, so it starts from the row.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency) "
                "VALUES (:i, :n, now(), :m, ARRAY['NOUR10'], :b, :b, 0, 0, 'EGP')"
            ),
            {"i": order_id, "n": f"#{order_id}", "m": month, "b": base},
        )
        connection.execute(
            text(
                "INSERT INTO attributed_order (shopify_order_id, affiliate_id, "
                "business_month, commission_base_piastres, commission_state) "
                "VALUES (:i, :a, :m, :b, :s)"
            ),
            {"i": order_id, "a": affiliate_id, "m": month, "b": base, "s": state},
        )


# ── One model's month ──────────────────────────────────────────────────────────


def test_a_month_reports_what_it_is_worth(client):
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 106_200)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["sales"]["earned_piastres"] == 106_200
    assert body["payout"]["piastres"] == 10_600
    assert body["payout"]["display"] == "E£106.00"
    assert body["is_payable"] is True


def test_the_orders_behind_the_figure_come_with_it(client):
    """A figure nobody can take apart is a figure nobody can argue with, and
    the first question about a payout is always *which sales is that?*
    """
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 60_000)
    _paid_order(affiliate["id"], "2", 46_200)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert len(body["orders_detail"]) == 2
    assert sum(row["base_piastres"] for row in body["orders_detail"]) == 106_200
    assert all(row["counts_toward_payout"] for row in body["orders_detail"])


def test_no_customer_ever_appears(client):
    """Order number, date, value, whether it counts. Never a name, an address,
    or anything the customer typed.
    """
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 60_000)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    allowed = {
        "shopify_order_id",
        "state",
        "base_piastres",
        "base",
        "counts_toward_payout",
        "delivered_at",
        "return_status",
        "base_frozen_at",
    }
    assert set(body["orders_detail"][0]) == allowed


def test_pending_sales_are_shown_not_hidden(client):
    """A model should be able to see what is coming rather than wonder why her
    month looks small.
    """
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 100_000)
    _paid_order(affiliate["id"], "2", 50_000, state="pending")

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["sales"]["earned_piastres"] == 100_000
    assert body["sales"]["pending_piastres"] == 50_000
    assert body["orders"]["pending"] == 1


def test_every_payout_is_marked_provisional(client):
    """Approving a month is Phase 6's job. Doing it on a GET would mean a month
    could be settled by whoever happened to load a page.
    """
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 100_000)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["payout"]["is_provisional"] is True


def test_both_figures_are_reported(client):
    """The audit has to show what was calculated as well as what would be paid."""
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])
    _paid_order(affiliate["id"], "1", 106_237)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["payout"]["exact_unrounded_piastres"] == "10623.7"
    assert body["payout"]["piastres"] == 10_600


# ── Blockers are the point ─────────────────────────────────────────────────────


def test_a_month_with_no_terms_says_so(client):
    """The sales are real and worth reporting; what she is owed is not
    calculable, and §11.3 refuses approval rather than warning.
    """
    affiliate = _affiliate(client)
    _paid_order(affiliate["id"], "1", 100_000)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["sales"]["earned_piastres"] == 100_000
    assert body["is_payable"] is False
    assert "no_compensation_terms_for_this_month" in body["blockers"]


def test_a_base_guarantee_with_no_target_recorded_blocks(client):
    """Nobody has said what she was asked for, so nobody can say whether the
    guarantee applies. §11.3 blocks on missing information.
    """
    affiliate = _affiliate(client)
    _terms(
        client,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _paid_order(affiliate["id"], "1", 200_000)

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["is_payable"] is False
    assert "no_target_recorded_for_this_month" in body["blockers"]
    assert body["targets"]["achieved"] is None


def test_a_verified_target_unlocks_the_guarantee_over_http(client):
    """The end of the chain, through the endpoints somebody actually calls:
    record the month on the grid, confirm it, and the guarantee applies.
    """
    affiliate = _affiliate(client)
    _terms(
        client,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _paid_order(affiliate["id"], "1", 200_000)

    client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                {
                    "affiliate_id": affiliate["id"],
                    "required_videos": 8,
                    "required_stories": 5,
                    "actual_videos": 8,
                    "actual_stories": 5,
                }
            ]
        },
    )
    client.post(
        f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
    )

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["is_payable"] is True
    assert body["targets"]["guarantee_applied"] is True
    assert body["payout"]["piastres"] == 800_000


def test_an_unverified_target_still_blocks_over_http(client):
    affiliate = _affiliate(client)
    _terms(
        client,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )

    client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                {
                    "affiliate_id": affiliate["id"],
                    "required_videos": 8,
                    "required_stories": 5,
                    "actual_videos": 8,
                    "actual_stories": 5,
                }
            ]
        },
    )

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["is_payable"] is False
    assert "targets_achieved_but_not_verified" in body["blockers"]
    assert body["targets"]["achieved"] is True
    assert body["targets"]["verified"] is False


# ── The whole programme ────────────────────────────────────────────────────────


def test_the_month_lists_every_affiliate(client):
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    _terms(client, nour["id"])
    _terms(client, sara["id"])
    _paid_order(nour["id"], "1", 100_000)
    _paid_order(sara["id"], "2", 200_000)

    body = client.get(f"/api/earnings/{MONTH}").json()

    assert body["totals"]["affiliates"] == 2
    assert body["totals"]["payable_piastres"] == 10_000 + 20_000


def test_the_payable_total_counts_only_what_could_be_paid_today(client):
    """A total that quietly included blocked months would be a number nobody
    could act on.
    """
    nour = _affiliate(client, "Nour", "nour@example.com")
    blocked = _affiliate(client, "Sara", "sara@example.com")
    _terms(client, nour["id"])
    _paid_order(nour["id"], "1", 100_000)
    _paid_order(blocked["id"], "2", 900_000)  # no terms

    body = client.get(f"/api/earnings/{MONTH}").json()

    assert body["totals"]["payable_piastres"] == 10_000
    assert body["totals"]["payable_affiliates"] == 1
    assert body["totals"]["blocked_affiliates"] == 1


def test_a_house_account_is_listed_with_real_sales_and_no_payout(client):
    """§8. Excluding it would report HBA's own orders as belonging to nobody,
    and its dashboard is what makes verification possible.
    """
    house = _affiliate(client, "House", "house@example.com", account_kind="house")
    _terms(client, house["id"])
    _paid_order(house["id"], "1", 500_000)

    body = client.get(f"/api/earnings/{MONTH}").json()
    row = next(item for item in body["affiliates"] if item["is_house"])

    assert row["sales"]["earned_piastres"] == 500_000
    assert row["payout"]["piastres"] == 0
    assert body["totals"]["payable_piastres"] == 0


# ── Who may look ───────────────────────────────────────────────────────────────


def test_a_model_may_not_read_earnings(client):
    """§6.5. The affiliate role holds no permissions at all."""
    affiliate = _affiliate(client)
    _demote_to("affiliate")

    assert client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").status_code == 403
    assert client.get(f"/api/earnings/{MONTH}").status_code == 403


def test_signing_out_closes_both_endpoints(anonymous):
    assert anonymous.get("/api/affiliates/1/earnings/2026-04").status_code == 401
    assert anonymous.get("/api/earnings/2026-04").status_code == 401


# ── Bad input ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("month", ["2026-13", "not-a-month", "2026", "2026-00"])
def test_a_month_that_is_not_a_month_is_refused(client, month):
    assert client.get(f"/api/earnings/{month}").status_code == 400


def test_an_affiliate_who_does_not_exist_is_a_404(client):
    assert client.get(f"/api/affiliates/99999/earnings/{MONTH}").status_code == 404


def test_a_month_with_nothing_in_it_is_zero_not_an_error(client):
    """An empty month is a real answer. Failing on one would make every new
    model's first month look broken.
    """
    affiliate = _affiliate(client)
    _terms(client, affiliate["id"])

    body = client.get(f"/api/affiliates/{affiliate['id']}/earnings/{MONTH}").json()

    assert body["payout"]["piastres"] == 0
    assert body["orders_detail"] == []
    assert body["is_payable"] is True
