"""Carry-forward, reopen, historical months, and the payroll API.

Phase 6 Tasks 4-7. §11.2, §11.4, §11.5.

Two things here answer questions HBA asked directly. **Carry-forward** is why an
August order can be paid in September while remaining an August sale — and
`settled_in_snapshot_id` is what lets her dashboard say so instead of leaving her
to work out the difference. **Historical months** are why eight months of
imported orders do not appear as a debt.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.payroll import CalculationState
from app.services.affiliates import create_affiliate
from app.services.audit import AuditEvent
from app.services.compensation import set_terms
from app.services.payroll import (
    ALREADY_SETTLED_OUTSIDE,
    NO_GO_LIVE_MONTH,
    approve_month,
    blockers_for,
    carried_into,
    carry_forward_summary,
    get_month,
    historical_sales,
    is_historical,
    months_left_reopened,
    reconciliation_for,
    reopen_month,
    snapshots_for,
)

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}
AUGUST = "2026-08"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    """A go-live month, so the historical guard does not block every test."""
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _affiliate(db, name="Nour", kind=AccountKind.MODEL):
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
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    return affiliate


def _order(db, affiliate, order_id, base, *, month=AUGUST,
           state=CommissionState.EARNED):
    db.add(
        OrderIndex(
            shopify_order_id=order_id,
            order_number=f"#{order_id}",
            placed_at=datetime(2026, 8, 29, 12, tzinfo=timezone.utc),
            business_month=month,
            discount_codes=["NOUR10"],
            subtotal_piastres=base,
            total_piastres=base,
            shipping_piastres=0,
            tax_piastres=0,
            currency="EGP",
        )
    )
    db.flush()
    row = AttributedOrder(
        shopify_order_id=order_id,
        affiliate_id=affiliate.id,
        business_month=month,
        commission_base_piastres=base,
        commission_state=state,
    )
    db.add(row)
    db.flush()
    return row


# ── Carry-forward (§11.4) ──────────────────────────────────────────────────────


def test_an_order_still_travelling_at_approval_carries_into_the_next_month(db):
    """The common path, not an edge case. Egyptian cash-on-delivery routinely
    straddles month end - an order placed 29 August may still be travelling
    when payroll runs on 5 September.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "paid", 200_000)
    late = _order(db, affiliate, "late", 84_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)

    # It arrives in September.
    late.commission_state = CommissionState.EARNED
    db.flush()

    carried = carried_into(db, affiliate, SEPTEMBER)

    assert [row.shopify_order_id for row in carried] == ["late"]


def test_a_carried_order_keeps_its_own_month(db):
    """August sales means orders placed in August, and that never shifts.
    Carry-forward is about which payroll pays it, never which month it belongs
    to - conflating the two is what makes a model's arithmetic disagree with
    her payment.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "paid", 200_000)
    late = _order(db, affiliate, "late", 84_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)
    late.commission_state = CommissionState.EARNED
    db.flush()

    carried = carried_into(db, affiliate, SEPTEMBER)

    assert carried[0].business_month == AUGUST


def test_the_carried_line_says_where_it_came_from(db):
    """§11.4's own wording: "Carried forward from August - 2 orders, E£840"."""
    affiliate = _affiliate(db)
    _order(db, affiliate, "paid", 200_000)
    _order(db, affiliate, "late-1", 50_000, state=CommissionState.PENDING)
    _order(db, affiliate, "late-2", 34_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)
    db.execute(
        text(
            "UPDATE attributed_order SET commission_state = 'earned' "
            "WHERE shopify_order_id LIKE 'late-%'"
        )
    )
    db.flush()

    lines = carry_forward_summary(db, affiliate, SEPTEMBER)

    assert lines == [{"from_month": AUGUST, "orders": 2, "piastres": 84_000}]


def test_an_order_already_paid_does_not_carry(db):
    """It was settled by August's payroll. Carrying it would pay it twice."""
    affiliate = _affiliate(db)
    _order(db, affiliate, "paid", 200_000)
    approve_month(db, affiliate, AUGUST)

    assert carried_into(db, affiliate, SEPTEMBER) == []


def test_nothing_carries_from_a_month_that_was_never_approved(db):
    """An unapproved August will pay its own orders when it is approved. Only
    an order whose month is already closed is genuinely carried.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    assert carried_into(db, affiliate, SEPTEMBER) == []


def test_a_pending_order_does_not_carry_until_it_arrives(db):
    """Nothing carries forward a sale that has not happened yet."""
    affiliate = _affiliate(db)
    _order(db, affiliate, "paid", 200_000)
    _order(db, affiliate, "still-travelling", 50_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)

    assert carried_into(db, affiliate, SEPTEMBER) == []


# ── Reopen (§11.5) ─────────────────────────────────────────────────────────────


def test_reopening_requires_a_written_reason(db):
    """The most dangerous operation in the platform - it touches a month
    somebody has been paid for.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)

    with pytest.raises(ValueError, match="written reason"):
        reopen_month(db, affiliate, AUGUST, reason="  ")


def test_reopening_returns_the_month_to_draft(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)

    reopen_month(db, affiliate, AUGUST, reason="an order was attributed wrongly")

    month = get_month(db, affiliate, AUGUST)
    assert month.calculation_state == CalculationState.DRAFT
    assert month.active_snapshot_id is None


def test_the_old_version_survives_a_reopen(db):
    """§11.5. The prior snapshot is preserved as a version, never overwritten -
    it is what the payments already made were made against.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    original = approve_month(db, affiliate, AUGUST)

    reopen_month(db, affiliate, AUGUST, reason="recalculating")

    versions = snapshots_for(db, get_month(db, affiliate, AUGUST))
    assert [row.version for row in versions] == [1]
    assert versions[0].approved_obligation_piastres == (
        original.approved_obligation_piastres
    )


def test_re_approving_creates_the_next_version(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)
    reopen_month(db, affiliate, AUGUST, reason="one order was missing")
    _order(db, affiliate, "2", 100_000)

    second = approve_month(db, affiliate, AUGUST)

    assert second.version == 2
    assert second.approved_obligation_piastres == 30_000
    assert len(snapshots_for(db, get_month(db, affiliate, AUGUST))) == 2


def test_reopening_releases_the_orders_that_version_paid(db):
    """So the recalculation can pay them again. Leaving them settled would make
    the new version pay nothing and look like a month with no sales.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)
    assert db.get(AttributedOrder, "1").settled_in_snapshot_id is not None

    reopen_month(db, affiliate, AUGUST, reason="recalculating")

    assert db.get(AttributedOrder, "1").settled_in_snapshot_id is None


def test_reopening_does_not_touch_a_month_settled_elsewhere(db):
    """§11.4. An order carried into September and paid there stays there when
    August is reopened - that month is settled.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "august", 200_000)
    late = _order(db, affiliate, "late", 84_000, state=CommissionState.PENDING)
    approve_month(db, affiliate, AUGUST)
    late.commission_state = CommissionState.EARNED
    late.business_month = AUGUST
    db.flush()
    september = approve_month(db, affiliate, SEPTEMBER)
    late.settled_in_snapshot_id = september.id
    db.flush()

    reopen_month(db, affiliate, AUGUST, reason="recalculating")

    assert db.get(AttributedOrder, "late").settled_in_snapshot_id == september.id


def test_reopening_an_unapproved_month_is_refused(db):
    affiliate = _affiliate(db)

    with pytest.raises(ValueError, match="not approved"):
        reopen_month(db, affiliate, AUGUST, reason="nothing to reopen")


def test_the_reason_reaches_the_audit_trail(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)
    reopen_month(db, affiliate, AUGUST, reason="Nour's code was mistyped")
    db.flush()

    from sqlalchemy import select

    event = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "payroll.reopened")
    ).one()
    assert "mistyped" in event.reason


# ── Reconciliation (§11.5) ─────────────────────────────────────────────────────


def test_a_higher_re_approval_reports_an_underpayment(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)
    reopen_month(db, affiliate, AUGUST, reason="an order was missing")
    _order(db, affiliate, "2", 100_000)
    approve_month(db, affiliate, AUGUST)

    result = reconciliation_for(db, affiliate, AUGUST)

    assert result["outcome"] == "underpaid"
    assert result["difference_piastres"] == 10_000


def test_a_lower_re_approval_leaves_the_choice_to_a_person(db):
    """§11.5. An overpayment is a credit or a write-off, and which one is a
    business judgement about a person HBA knows. The platform reports.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    _order(db, affiliate, "2", 100_000)
    approve_month(db, affiliate, AUGUST)
    reopen_month(db, affiliate, AUGUST, reason="an order was not hers")
    db.execute(text("DELETE FROM attributed_order WHERE shopify_order_id = '2'"))
    db.flush()
    approve_month(db, affiliate, AUGUST)

    result = reconciliation_for(db, affiliate, AUGUST)

    assert result["outcome"] == "overpaid"
    assert result["difference_piastres"] == -10_000
    assert result["resolution"] is None, "the platform must not decide"


def test_a_month_approved_once_has_nothing_to_reconcile(db):
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)

    assert reconciliation_for(db, affiliate, AUGUST)["outcome"] == "not_reconcilable"


def test_a_month_left_reopened_is_reported(db):
    """The dangerous state is not reopening; it is forgetting. A month in draft
    with payments made against a superseded snapshot is a balance nobody is
    watching.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)
    approve_month(db, affiliate, AUGUST)
    reopen_month(db, affiliate, AUGUST, reason="recalculating")

    stuck = months_left_reopened(db, AUGUST)

    assert [row.affiliate_id for row in stuck] == [affiliate.id]


def test_a_month_never_approved_is_not_reported_as_stuck(db):
    """It was never reopened. Reporting it would make the alert meaningless
    through volume - every open month would appear.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    assert months_left_reopened(db, AUGUST) == []


# ── Historical months (§11.2) ──────────────────────────────────────────────────


def test_a_month_before_go_live_is_historical(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-08", raising=False)

    assert is_historical("2026-07") is True
    assert is_historical("2026-08") is False, "go-live itself is live"
    assert is_historical("2026-09") is False


def test_a_historical_month_is_not_approvable(db, monkeypatch):
    """§11.2. Money already settled outside the platform, ready to be paid a
    second time.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-09", raising=False)
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    blockers, _ = blockers_for(db, affiliate, AUGUST)

    assert ALREADY_SETTLED_OUTSIDE in blockers
    with pytest.raises(ValueError):
        approve_month(db, affiliate, AUGUST)


def test_a_historical_month_shows_sales_and_no_commission(db):
    """ADR 0014. March's rates exist only in the old system and in somebody's
    memory; applying today's would be actively misleading.
    """
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    result = historical_sales(db, affiliate, AUGUST)

    assert result["net_sales_piastres"] == 200_000
    assert result["commission"] is None
    assert result["is_payable"] is False
    assert "Settled before the platform" in result["label"]


def test_an_unconfigured_go_live_blocks_every_approval(db, monkeypatch):
    """The failure this exists to prevent: a go-live that defaulted to
    something would silently make eight months of imported orders approvable.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "", raising=False)
    affiliate = _affiliate(db)
    _order(db, affiliate, "1", 200_000)

    blockers, _ = blockers_for(db, affiliate, AUGUST)

    assert NO_GO_LIVE_MONTH in blockers
    with pytest.raises(ValueError):
        approve_month(db, affiliate, AUGUST)


# ── The API ────────────────────────────────────────────────────────────────────


def _make_account(email: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Model') RETURNING id"
            ),
            {"e": email, "p": hash_password("a-long-enough-password")},
        ).scalar_one()


def _api_affiliate(client, name="Nour", email="nour@example.com") -> dict:
    body = {"user_account_id": _make_account(email), "name": name}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    affiliate = response.json()
    client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    return affiliate


def _api_order(affiliate_id, order_id, base, *, month=AUGUST, state="earned"):
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


def test_the_month_view_shows_what_blocks_each_model(client):
    ready = _api_affiliate(client, "Nour", "nour@example.com")
    _api_order(ready["id"], "1", 200_000)
    blocked = _api_affiliate(client, "Sara", "sara@example.com")
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM compensation_period WHERE affiliate_id = :a"),
            {"a": blocked["id"]},
        )

    body = client.get(f"/api/payroll/{AUGUST}").json()

    rows = {row["affiliate_id"]: row for row in body["affiliates"]}
    assert rows[ready["id"]]["is_payable"] is True
    assert rows[blocked["id"]]["is_payable"] is False
    assert body["totals"]["blocked_affiliates"] == 1


def test_approving_defaults_to_a_preview(client):
    """A default that writes is a default that eventually writes by accident."""
    affiliate = _api_affiliate(client)
    _api_order(affiliate["id"], "1", 200_000)

    body = client.post(
        f"/api/payroll/{AUGUST}/approve", json={"affiliate_ids": [affiliate["id"]]}
    ).json()

    assert body["preview"] is True
    assert body["results"][0]["approved"] is False
    assert body["results"][0]["obligation_piastres"] == 20_000
    assert (
        client.get(f"/api/payroll/{AUGUST}").json()["affiliates"][0][
            "calculation_state"
        ]
        == "draft"
    ), "the preview wrote nothing"


def test_committing_approves_and_freezes(client):
    affiliate = _api_affiliate(client)
    _api_order(affiliate["id"], "1", 200_000)

    body = client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [affiliate["id"]], "preview": False},
    ).json()

    assert body["results"][0]["approved"] is True
    assert body["results"][0]["version"] == 1
    assert (
        client.get(f"/api/payroll/{AUGUST}").json()["affiliates"][0][
            "calculation_state"
        ]
        == "approved"
    )


def test_one_blocked_model_does_not_stop_the_others(client):
    """Twenty months are twenty separate obligations. Refusing them all because
    one target is unverified would make month-end hostage to a single row.
    """
    ready = _api_affiliate(client, "Nour", "nour@example.com")
    _api_order(ready["id"], "1", 200_000)
    blocked = _api_affiliate(client, "Sara", "sara@example.com")
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM compensation_period WHERE affiliate_id = :a"),
            {"a": blocked["id"]},
        )

    body = client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [ready["id"], blocked["id"]], "preview": False},
    ).json()

    assert body["totals"]["approved"] == 1
    assert body["totals"]["blocked"] == 1


def test_reopening_over_http_needs_a_reason(client):
    affiliate = _api_affiliate(client)
    _api_order(affiliate["id"], "1", 200_000)
    client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [affiliate["id"]], "preview": False},
    )

    assert (
        client.post(
            f"/api/payroll/{AUGUST}/reopen",
            json={"affiliate_ids": [affiliate["id"]], "reason": ""},
        ).status_code
        == 422
    )

    response = client.post(
        f"/api/payroll/{AUGUST}/reopen",
        json={
            "affiliate_ids": [affiliate["id"]],
            "reason": "an order was attributed wrongly",
        },
    )
    assert response.status_code == 200


def test_a_month_left_reopened_is_visible_over_http(client):
    affiliate = _api_affiliate(client)
    _api_order(affiliate["id"], "1", 200_000)
    client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [affiliate["id"]], "preview": False},
    )
    client.post(
        f"/api/payroll/{AUGUST}/reopen",
        json={"affiliate_ids": [affiliate["id"]], "reason": "recalculating"},
    )

    body = client.get(f"/api/payroll/{AUGUST}/reopened").json()

    assert len(body["left_reopened"]) == 1


def test_a_model_may_not_approve_anything(client):
    """§6.5, and payroll.approve is not a permission the affiliate role holds."""
    affiliate = _api_affiliate(client)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))

    assert (
        client.post(
            f"/api/payroll/{AUGUST}/approve",
            json={"affiliate_ids": [affiliate["id"]], "preview": False},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/payroll/{AUGUST}/reopen",
            json={"affiliate_ids": [affiliate["id"]], "reason": "no"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("month", ["2026-13", "not-a-month", "2026"])
def test_a_month_that_is_not_a_month_is_refused(client, month):
    assert client.get(f"/api/payroll/{month}").status_code == 400
