"""A bonus HBA adds to a model's month (ADR 0070).

The owner, 29 October 2026: a button on every model to add a bonus, an
optional reason only staff see, and her month's summary saying a bonus was
added. Admin and the affiliate manager may add one.

What these hold, in the order it matters:

- the bonus is paid **on top of** a guaranteed minimum, never swallowed by it;
- an agreed month cannot gain or lose one;
- the reason never reaches her side of the platform.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app
from app.modules.affiliates.models.affiliates import AccountKind
from app.modules.affiliates.services.bonuses import add_bonus, withdraw_bonus
from app.modules.affiliates.services.commission.calculate import calculate_month
from app.modules.affiliates.services.overview import _attribute
from tests.test_commission_calculate import (
    MONTH,
    _affiliate,
    _earned,
    _guaranteed,
    _target,
)

PASSWORD = "quiet-harbour-lantern"
BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": PASSWORD}
AUGUST = "2026-08"
REASON = "Shot the Eid campaign on her day off"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


# -- The arithmetic -----------------------------------------------------------


def test_a_bonus_is_added_to_the_month(db):
    affiliate = _affiliate(db)
    from app.modules.affiliates.services.compensation import set_terms

    set_terms(db, affiliate, start_month="2026-01", compensation_type="commission", commission_rate_bp=1000)
    _earned(db, affiliate, "1", 1_000_000)

    add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000)
    result = calculate_month(db, affiliate, MONTH)

    assert result.bonus_piastres == 50_000
    assert result.payout_piastres == 100_000 + 50_000
    assert result.bonus_lines == [{"bonus_id": result.bonus_lines[0]["bonus_id"], "amount_piastres": 50_000}]


def test_a_bonus_is_paid_on_top_of_a_guaranteed_minimum(db):
    """The reason it sits after the comparison. Inside it, a model on an
    EGP 8,000 floor who sold EGP 200 of commission would be paid 8,000 with or
    without the bonus - the one person it would do nothing for is the one
    who earned least."""
    affiliate = _affiliate(db)
    _guaranteed(db, affiliate, base=800_000)
    _target(db, affiliate, actual=(8, 5), verified=True)
    _earned(db, affiliate, "1", 2_000_000)

    add_bonus(db, affiliate, month=MONTH, amount_piastres=100_000)
    result = calculate_month(db, affiliate, MONTH)

    assert result.guarantee_applied is True
    assert result.payout_piastres == 800_000 + 100_000

    parts = _attribute(result)
    assert parts.bonus_piastres == 100_000
    # The floor lifted her 6,000 over her commission; the bonus is not more
    # top-up, and the parts still add up to the figure.
    assert parts.guarantee_top_up_piastres == 600_000
    assert (
        parts.commission_piastres + parts.fixed_piastres
        + parts.guarantee_top_up_piastres + parts.bonus_piastres
    ) == result.payout_piastres


def test_a_withdrawn_bonus_is_not_paid(db):
    affiliate = _affiliate(db)
    from app.modules.affiliates.services.compensation import set_terms

    set_terms(db, affiliate, start_month="2026-01", compensation_type="commission", commission_rate_bp=1000)
    bonus = add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000)

    withdraw_bonus(db, affiliate, bonus.id)

    assert calculate_month(db, affiliate, MONTH).payout_piastres == 0
    assert bonus.withdrawn_at is not None, "kept, not deleted"


@pytest.mark.parametrize(
    "amount, words",
    [(0, "more than nothing"), (50_050, "whole pounds"), (10**12, "Check the amount")],
)
def test_an_impossible_amount_is_refused(db, amount, words):
    affiliate = _affiliate(db)
    with pytest.raises(ValueError, match=words):
        add_bonus(db, affiliate, month=MONTH, amount_piastres=amount)


def test_a_house_account_cannot_have_one(db):
    affiliate = _affiliate(db, name="Store", kind=AccountKind.HOUSE)
    with pytest.raises(ValueError, match="house account"):
        add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000)


def test_a_month_before_go_live_cannot_have_one(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-06", raising=False)
    affiliate = _affiliate(db)
    with pytest.raises(ValueError, match="settled outside"):
        add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000)


def test_a_future_month_cannot_have_one(db):
    affiliate = _affiliate(db)
    with pytest.raises(ValueError, match="future"):
        add_bonus(db, affiliate, month="2099-01", amount_piastres=50_000)


def test_the_same_request_twice_is_one_bonus(db):
    affiliate = _affiliate(db)
    first = add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000, operation_key="bonus-retry-1")
    second = add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000, operation_key="bonus-retry-1")

    assert first.id == second.id
    assert calculate_month(db, affiliate, MONTH).bonus_piastres == 50_000


def test_a_replay_never_reports_a_bonus_that_is_not_there(db):
    affiliate = _affiliate(db)
    first = add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000, operation_key="bonus-retry-2")

    with pytest.raises(ValueError, match="different bonus"):
        add_bonus(db, affiliate, month=MONTH, amount_piastres=90_000, operation_key="bonus-retry-2")

    withdraw_bonus(db, affiliate, first.id)
    with pytest.raises(ValueError, match="withdrawn"):
        add_bonus(db, affiliate, month=MONTH, amount_piastres=50_000, operation_key="bonus-retry-2")


# -- Over HTTP ----------------------------------------------------------------


@pytest.fixture()
def admin(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _model(admin) -> dict:
    with engine.begin() as connection:
        account = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES ('nour@example.com', :p, 'active', 'Nour') RETURNING id"
            ),
            {"p": hash_password(PASSWORD)},
        ).scalar_one()
    response = admin.post("/api/affiliates", json={"user_account_id": account, "name": "Nour"})
    assert response.status_code == 201, response.text
    affiliate = response.json()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'active' WHERE id = :id"),
            {"id": affiliate["id"]},
        )
    admin.put(
        f"/api/affiliates/{affiliate['id']}/pay-history",
        json={
            "periods": [
                {"start_month": "2026-01", "compensation_type": "commission", "commission_rate_bp": 1000}
            ],
            "outcomes": {},
        },
    )
    return affiliate


def _approve(admin, affiliate_id, month=AUGUST):
    seen = admin.post(f"/api/payroll/{month}/approve", json={"affiliate_ids": [affiliate_id]}).json()
    response = admin.post(
        f"/api/payroll/{month}/approve",
        json={
            "affiliate_ids": [affiliate_id],
            "preview": False,
            "source_versions": {str(affiliate_id): seen["results"][0]["source_version"]},
        },
    )
    assert response.status_code == 200, response.text
    return response


def _bonus(admin, affiliate_id, month=AUGUST, amount=50_000, reason=REASON):
    return admin.post(
        f"/api/affiliates/{affiliate_id}/bonuses",
        json={"month": month, "amount_piastres": amount, "reason": reason},
    )


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def test_staff_add_a_bonus_and_see_it_with_its_reason(admin):
    affiliate = _model(admin)

    assert _bonus(admin, affiliate["id"]).status_code == 201

    listed = admin.get(f"/api/affiliates/{affiliate['id']}/bonuses").json()["bonuses"]
    assert [(row["month"], row["amount_piastres"], row["reason"]) for row in listed] == [
        (AUGUST, 50_000, REASON)
    ]
    assert listed[0]["added_by"] == "Owner"
    assert listed[0]["can_withdraw"] is True


def test_approval_freezes_the_bonus_into_what_is_owed(admin):
    affiliate = _model(admin)
    _bonus(admin, affiliate["id"])

    _approve(admin, affiliate["id"])

    with engine.connect() as connection:
        owed = connection.execute(
            text(
                "SELECT s.approved_obligation_piastres, s.payload_json->>'bonus_piastres' "
                "FROM payroll_month m JOIN payroll_snapshot s ON s.id = m.active_snapshot_id "
                "WHERE m.affiliate_id = :a AND m.month = :m"
            ),
            {"a": affiliate["id"], "m": AUGUST},
        ).one()
    assert owed == (50_000, "50000")

    statement = admin.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}")
    assert statement.status_code == 200, statement.text
    assert statement.json()["bonus_piastres"] == 50_000
    assert statement.json()["total_piastres"] == 50_000


def test_an_agreed_month_neither_gains_nor_loses_a_bonus(admin):
    affiliate = _model(admin)
    added = _bonus(admin, affiliate["id"]).json()
    _approve(admin, affiliate["id"])

    refused = _bonus(admin, affiliate["id"], amount=10_000)
    assert refused.status_code == 409
    assert "already agreed" in refused.json()["detail"]

    kept = admin.post(f"/api/affiliates/{affiliate['id']}/bonuses/{added['id']}/withdraw")
    assert kept.status_code == 409
    assert "Reopen" in kept.json()["detail"]


def test_adding_a_bonus_moves_the_figure_a_preview_showed(admin):
    """05B. A bonus added after somebody looked at the month and before they
    agreed it changes what they would be agreeing, so the commit is refused."""
    affiliate = _model(admin)
    seen = admin.post(f"/api/payroll/{AUGUST}/approve", json={"affiliate_ids": [affiliate["id"]]}).json()

    _bonus(admin, affiliate["id"])
    response = admin.post(
        f"/api/payroll/{AUGUST}/approve",
        json={
            "affiliate_ids": [affiliate["id"]],
            "preview": False,
            "source_versions": {str(affiliate["id"]): seen["results"][0]["source_version"]},
        },
    )

    assert response.json()["results"][0]["approved"] is False


def test_withdrawing_takes_it_off_an_open_month(admin):
    affiliate = _model(admin)
    added = _bonus(admin, affiliate["id"]).json()

    response = admin.post(f"/api/affiliates/{affiliate['id']}/bonuses/{added['id']}/withdraw")

    assert response.status_code == 200, response.text
    row = admin.get(f"/api/affiliates/{affiliate['id']}/bonuses").json()["bonuses"][0]
    assert row["withdrawn_at"] is not None
    assert row["can_withdraw"] is False


def test_the_affiliate_manager_may_add_one(admin):
    affiliate = _model(admin)
    _demote_to("affiliate_manager")

    assert _bonus(admin, affiliate["id"]).status_code == 201


@pytest.mark.parametrize("role", ["content_manager", "operations_manager", "customer_service"])
def test_other_staff_may_not(admin, role):
    affiliate = _model(admin)
    _demote_to(role)

    assert _bonus(admin, affiliate["id"]).status_code == 403


def test_she_sees_the_bonus_and_never_the_reason(admin):
    affiliate = _model(admin)
    _bonus(admin, affiliate["id"])

    with TestClient(app) as model:
        signed_in = model.post("/api/auth/login", json={"email": "nour@example.com", "password": PASSWORD})
        assert signed_in.status_code == 200, signed_in.text
        model.headers["X-CSRF-Token"] = signed_in.json()["csrf"]

        open_month = model.get(f"/api/me/earnings/{AUGUST}")
        assert open_month.status_code == 200, open_month.text
        assert open_month.json()["bonus"]["piastres"] == 50_000
        assert open_month.json()["amount_piastres"] == 50_000
        assert {"label": "Bonus from HBA", "piastres": 50_000, "detail": None, "amount": "EGP 500.00"} in open_month.json()["makeup"]
        assert REASON not in open_month.text

        _approve(admin, affiliate["id"])
        for path in (f"/api/me/earnings/{AUGUST}", f"/api/me/home/{AUGUST}", "/api/me/payments", "/api/me/year"):
            response = model.get(path)
            assert response.status_code == 200, (path, response.text)
            assert REASON not in response.text, path

        agreed = model.get(f"/api/me/earnings/{AUGUST}").json()
        assert agreed["bonus"]["amount"] == "EGP 500.00"

        # Her own client holds no staff permission.
        assert model.get(f"/api/affiliates/{affiliate['id']}/bonuses").status_code == 403


def test_the_audit_trail_says_what_happened_in_words(admin):
    affiliate = _model(admin)
    added = _bonus(admin, affiliate["id"]).json()
    admin.post(f"/api/affiliates/{affiliate['id']}/bonuses/{added['id']}/withdraw")

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT action, reason, department FROM audit_event WHERE action LIKE 'payroll.bonus%' ORDER BY id")
        ).all()
    assert rows == [
        ("payroll.bonus_added", REASON, "affiliates"),
        ("payroll.bonus_withdrawn", None, "affiliates"),
    ]


def test_nobody_adds_a_bonus_to_their_own_profile(admin):
    """A member of staff may also be a model (ADR 0067). A bonus is money they
    could otherwise pay themselves."""
    with engine.connect() as connection:
        owner = connection.execute(
            text("SELECT id FROM user_account WHERE email = 'owner@example.com'")
        ).scalar_one()
    response = admin.post("/api/affiliates", json={"user_account_id": owner, "name": "Owner"})
    assert response.status_code == 201, response.text
    own = response.json()

    refused = _bonus(admin, own["id"])

    assert refused.status_code == 403
    assert "your own profile" in refused.json()["detail"]
