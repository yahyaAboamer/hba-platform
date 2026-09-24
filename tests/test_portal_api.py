"""What a model sees about their own money, over HTTP.

Phase 9. Every figure here already existed and had been exercised on the
maintainer's screens for months, so this file is not about arithmetic - it is
about the three things that go wrong when the same figure is shown to the
person whose money it is:

* an agreed month quietly showing a **recalculation** instead of what they were
  paid (§11.1),
* carry-forward leaving their own arithmetic unable to close (§11.4),
* a customer's details reaching a model dashboard (§19).

The last one is asserted rather than asserted-about: the response is searched
for values that were deliberately put into the database, so the test fails if
somebody ever adds a field that carries them.
"""

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app
from app.models.payouts import PayoutMethod
from tests.support_policy import approved_before_the_switch

#: Where their money goes, so a payment can freeze a masked copy of it.
ADDRESS = 'https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp' 

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
PASSWORD = "quiet-harbour-lantern"
AUGUST = "2026-08"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    """A go-live month, so nothing here is accidentally historical."""
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture(autouse=True)
def _working_month(monkeypatch):
    """Pin what "this month" means.

    The portal decides which months to offer from the working month, so a suite
    that read the real clock would offer a different list every September.
    """
    monkeypatch.setattr(
        "app.services.portal.working_month", lambda: SEPTEMBER, raising=True
    )


@pytest.fixture()
def admin(fresh_database):
    with TestClient(app) as client:
        response = client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield client


def _account(email: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, "
                "display_name) VALUES (:e, :p, 'active', 'Model') RETURNING id"
            ),
            {"e": email, "p": hash_password(PASSWORD)},
        ).scalar_one()


def _affiliate(admin, name="Nour", email="nour@example.com", code="NOUR10") -> dict:
    """A model with an account and a registered code.

    The code period is written straight in. Registering one through the API
    calls Shopify to settle which month ownership starts from (§10.4), and this
    file is about what the portal reports given a registry, not about
    verification.
    """
    response = admin.post(
        "/api/affiliates",
        json={"user_account_id": _account(email), "name": name},
    )
    assert response.status_code == 201, response.text
    affiliate = response.json()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO discount_code_period "
                "(affiliate_id, code, start_month, shopify_verified_at) "
                "VALUES (:a, :c, '2025-01', now())"
            ),
            {"a": affiliate["id"], "c": code},
        )
        # **Active**, because these tests pay her. `create_affiliate` makes an
        # application, and `payments.on_the_desk` no longer lists one - the
        # approved export's desk is `participants(month)`. A model who is paid
        # and is still an application is not a state the product produces.
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'active' WHERE id = :id"),
            {"id": affiliate["id"]},
        )
    return affiliate


def _sign_in(email: str = "nour@example.com") -> TestClient:
    """Their own client - a session that owns the profile, holding no permission."""
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def _terms(admin, affiliate_id, rate_bp=1000, start="2026-01", **extra):
    response = admin.put(
        f"/api/affiliates/{affiliate_id}/pay-history",
        json={
            "periods": [
                {
                    "start_month": start,
                    "compensation_type": "commission",
                    "commission_rate_bp": rate_bp,
                    **extra,
                }
            ],
            "outcomes": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["periods"][0]


def _rate_change(admin, affiliate_id, *, until, before_bp, after_bp, from_month):
    """Two arrangements, written together, because that is now one act.

    ADR 0036 replaced `POST /compensation` — which recorded one period and
    superseded whatever was open — with a route that writes the **whole**
    history. Calling `_terms` twice against it is not a rate change any more;
    it is a rewrite, and the second call would leave the earlier months with no
    arrangement at all.

    Which is the right behaviour for a screen that shows a model's whole year
    and saves it once, and the wrong helper for a test whose subject is a rate
    changing mid-year.
    """
    response = admin.put(
        f"/api/affiliates/{affiliate_id}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "end_month": until,
                    "compensation_type": "commission",
                    "commission_rate_bp": before_bp,
                },
                {
                    "start_month": from_month,
                    "compensation_type": "commission",
                    "commission_rate_bp": after_bp,
                },
            ],
            "outcomes": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["periods"]


#: Values a customer would recognise as their own. Written into the order index
#: **nowhere** - there is no column for any of them, which is the point - but
#: kept here so the no-PII test says what it is looking for.
CUSTOMER_NAME = "Farida Hassan"
CUSTOMER_ADDRESS = "14 Road 9, Maadi, Cairo"
CUSTOMER_EMAIL = "farida@example.com"


def _order(
    affiliate_id,
    order_id,
    base,
    *,
    month=AUGUST,
    state="earned",
    code="NOUR10",
    number=None,
    placed=None,
):
    """An order already attributed, written straight in.

    The paths that produce these have their own tests; this file is about what
    the portal reports, so it starts from the row.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, "
                "placed_at, business_month, discount_codes, subtotal_piastres, "
                "total_piastres, shipping_piastres, tax_piastres, currency, "
                "original_subtotal_piastres, original_total_piastres) "
                "VALUES (:i, :n, now(), :m, ARRAY[:c], :b, :b, 0, 0, 'EGP', :p, :p)"
            ),
            {
                "i": order_id,
                "n": number or f"#{order_id}",
                "m": month,
                "c": code,
                "b": base,
                # What the order came to when it was placed. `None` reproduces
                # a row indexed before the platform started asking for it.
                "p": placed,
            },
        )
        connection.execute(
            text(
                "INSERT INTO attributed_order (shopify_order_id, affiliate_id, "
                "business_month, commission_base_piastres, commission_state) "
                "VALUES (:i, :a, :m, :b, :s)"
            ),
            {"i": order_id, "a": affiliate_id, "m": month, "b": base, "s": state},
        )


def _deliver(order_id: str) -> None:
    """Mark an order arrived, so a pending one becomes earned."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'earned', "
                "delivered_at = now() WHERE shopify_order_id = :i"
            ),
            {"i": order_id},
        )


def _hit_targets(admin, affiliate_id, month, *, verified: bool):
    """Record a month they met, and optionally confirm the numbers.

    §15: verification is what unlocks a guarantee, and it confirms the numbers
    rather than the outcome - the two steps are separate here because the gap
    between them is a state a model actually sits in.
    """
    response = admin.put(
        f"/api/targets/{month}",
        json={
            # The revision the server last handed out. Optimistic
            # concurrency arrived in 04A: a save without a matching one
            # is refused, because two people run payroll and both open
            # that screen at month end.
            "revision": _target_revision(admin, month),
            "rows": [
                {
                    "affiliate_id": affiliate_id,
                    "required_videos": 4,
                    "required_stories": 8,
                    "actual_videos": 4,
                    "actual_stories": 8,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    if verified:
        confirmed = admin.post(
            f"/api/targets/{month}/verify", json={"affiliate_ids": [affiliate_id]}
        )
        assert confirmed.status_code == 200, confirmed.text


def _missed_targets(admin, affiliate_id, month):
    """A month recorded and confirmed as short of what was asked."""
    response = admin.put(
        f"/api/targets/{month}",
        json={
            # The revision the server last handed out. Optimistic
            # concurrency arrived in 04A: a save without a matching one
            # is refused, because two people run payroll and both open
            # that screen at month end.
            "revision": _target_revision(admin, month),
            "rows": [
                {
                    "affiliate_id": affiliate_id,
                    "required_videos": 4,
                    "required_stories": 8,
                    "actual_videos": 1,
                    "actual_stories": 2,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    confirmed = admin.post(
        f"/api/targets/{month}/verify", json={"affiliate_ids": [affiliate_id]}
    )
    assert confirmed.status_code == 200, confirmed.text


def _egp(piastres: int) -> str:
    """The formatted figure, from the platform's own formatter.

    Rather than re-typing the currency symbol in twenty assertions - one
    mistyped glyph is a failure that says nothing about the code.
    """
    from app.core.money import format_egp

    return format_egp(piastres)


def _destination(admin, affiliate_id):
    """Somewhere to pay them, so a payment can freeze a masked copy of it."""
    response = admin.put(
        f"/api/affiliates/{affiliate_id}/payout-destination",
        json={
            "method": PayoutMethod.INSTAPAY,
            "instapay_address_url": ADDRESS,
            "instapay_phone": "01001234567",
        },
    )
    assert response.status_code in (200, 201), response.text


def _proof(admin, affiliate_id) -> str:
    """A screenshot, uploaded the way §14's flow does it - before the payment.

    `payment_transaction` is append-only, so proof is attached at the moment
    the payment is recorded rather than added to the row afterwards.
    """
    image = Image.new("RGB", (600, 900), (240, 240, 250))
    out = io.BytesIO()
    image.save(out, format="PNG")

    response = admin.post(
        f"/api/affiliates/{affiliate_id}/proof",
        files={"file": ("transfer.png", out.getvalue(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["proof_file_id"]


def _pay(admin, affiliate_id, month, piastres, *, proof=None, note=None) -> int:
    """Money that has already moved, allocated against that month's snapshot.

    Payments allocate to a **snapshot**, not to a month (§11.5): money paid
    against a superseded version stays attached to the version it settled.
    """
    balance = admin.get(f"/api/payments/{month}").json()["affiliates"]
    mine = next(row for row in balance if row["affiliate_id"] == affiliate_id)

    response = admin.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate_id,
            "amount_piastres": piastres,
            "allocations": [
                {
                    "payroll_snapshot_id": mine["payroll_snapshot_id"],
                    "piastres": piastres,
                }
            ],
            "reference": "IPN-77",
            # §14 refuses a partial payment with no explanation: *a partial
            # payment and a typo look identical without one.*
            "note": note,
            "proof_file_id": proof,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]



def _approve(admin, affiliate_id, month):
    """Agree a month the way the screen does: preview, then commit what it said.

    05B refuses a commit that carries no record of what was on the screen, so
    the fingerprint the preview hands out is handed straight back. Two lines,
    and they keep these tests about **behaviour** rather than about the calling
    convention.
    """
    seen = admin.post(
        f"/api/payroll/{month}/approve",
        json={"affiliate_ids": [affiliate_id]},
    ).json()["results"][0]
    response = admin.post(
        f"/api/payroll/{month}/approve",
        json={
            "affiliate_ids": [affiliate_id],
            "preview": False,
            "source_versions": {str(affiliate_id): seen["source_version"]},
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["results"][0]
    assert result["approved"] is True, result
    return result


# -- Who may look -------------------------------------------------------------


def test_a_maintainer_is_refused_from_the_model_routes(admin):
    """Two gates, never mixed (§6.1). An administrator is not the subject of
    any affiliate record, and there is already an admin route for their month.
    """
    assert admin.get(f"/api/me/earnings/{AUGUST}").status_code == 403
    assert admin.get("/api/me/months").status_code == 403


def test_anonymous_access_is_refused(fresh_database):
    with TestClient(app) as anonymous:
        assert anonymous.get(f"/api/me/earnings/{AUGUST}").status_code == 401


def test_the_route_takes_no_affiliate_id_at_all(admin):
    """Reaching another model's month is not refused - it is unexpressible.

    Driven with two real models rather than by reading the signature.
    """
    nour = _affiliate(admin)
    sara = _affiliate(admin, "Sara", "sara@example.com", "SARA10")
    _terms(admin, nour["id"])
    _terms(admin, sara["id"])
    _order(nour["id"], "1", 100_000)
    _order(sara["id"], "2", 500_000, code="SARA10")

    mine = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert mine["sales"]["earned_piastres"] == 100_000
    assert len(mine["orders_detail"]) == 1


def test_a_paused_model_still_sees_what_they_were_owed(admin):
    """§8. *Not earning, may return.* Locking them out would make paused and
    archived the same thing to the only person they affect.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)
    model = _sign_in()

    admin.patch(f"/api/affiliates/{affiliate['id']}", json={"status": "inactive"})

    assert model.get(f"/api/me/earnings/{AUGUST}").status_code == 200


# -- No customer, ever --------------------------------------------------------


def test_nothing_a_customer_typed_can_reach_their_screen(admin):
    """§19, and the reason it is structural rather than a filter.

    There is no column on `order_index` or `attributed_order` for a customer's
    name, address, phone or email - §10.2's thin row never stored them. This
    asserts the response carries no field that could hold one, so adding such a
    field later fails here rather than in front of twenty models.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    served = str(body).lower()
    for leaked in (CUSTOMER_NAME, CUSTOMER_ADDRESS, CUSTOMER_EMAIL):
        assert leaked.lower() not in served

    keys = {key for row in body["orders_detail"] for key in row}
    for forbidden in ("customer", "email", "phone", "address", "name"):
        assert not any(forbidden in key for key in keys), keys


# -- §11.1: is this figure settled? -------------------------------------------


def test_an_open_month_is_marked_as_still_moving(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["state"] == "open"
    assert body["amount_piastres"] == 10_600


def test_an_agreed_month_is_marked_agreed(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["state"] == "agreed"
    assert body["amount_piastres"] == 10_600


# ── Phase 10 Batch C: which policy governed this ────────────────────────────


def test_an_agreed_month_names_the_policy_in_force(admin):
    created = admin.post(
        "/api/policy/versions",
        json={"effective_month": "2026-01", "summary_markdown": "x"},
    ).json()
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["policy_version"] == {"id": created["id"], "effective_month": "2026-01"}


def test_the_full_text_is_readable_from_the_portal(admin):
    _affiliate(admin)
    created = admin.post(
        "/api/policy/versions",
        json={"effective_month": "2026-01", "summary_markdown": "The full text."},
    ).json()

    response = _sign_in().get(f"/api/me/policy/{created['id']}")

    assert response.status_code == 200
    assert response.json()["summary_markdown"] == "The full text."


def test_an_open_month_names_no_policy(admin):
    """Nothing has been frozen yet - naming one would claim a decision that
    has not been made."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["state"] == "open"
    assert body["policy_version"] is None


def test_an_agreed_month_with_no_policy_yet_names_none(admin):
    """A deployment before anyone has written policy v1 must still be able to
    approve payroll - the column is nullable for exactly this."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["policy_version"] is None


def test_an_agreed_month_shows_what_was_paid_not_what_it_recalculates_to(admin):
    """The trap the maintainer's payroll screen already fell into.

    `calculate_month` keeps moving after approval. A late order arriving in
    September changes what August *would* come to and never what August *is* -
    and they are the person who would notice a settled figure moving.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 106_200)
    _approve(admin, affiliate["id"], AUGUST)

    # An August order that arrives after August was agreed.
    _order(affiliate["id"], "2", 500_000, state="pending")
    _deliver("2")

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["state"] == "agreed"
    assert body["amount_piastres"] == 10_600


def test_the_breakdown_adds_up_to_the_total(admin):
    """They are the one person guaranteed to add it up.

    ADR 0004 rounds once, on the total, so display-rounded lines can miss it by
    up to half a pound. Where they do, the difference gets a line of its own
    rather than being left for them to find.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    # 106,237 x 10% = 10,623.7 piastres, rounded to EGP 106.00.
    _order(affiliate["id"], "1", 106_237)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert sum(line["piastres"] for line in body["makeup"]) == body["amount_piastres"]
    assert body["makeup"][-1]["label"] == "Rounded to the nearest pound"


def test_a_salary_is_its_own_line(admin):
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="fixed_plus_commission",
        fixed_amount_piastres=500_000,
    )
    _order(affiliate["id"], "1", 100_000)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    labels = [line["label"] for line in body["makeup"]]
    assert "Your monthly salary" in labels
    assert sum(line["piastres"] for line in body["makeup"]) == body["amount_piastres"]


def test_a_guarantee_says_what_it_replaced(admin):
    """§9.5. Never both, never one on top of the other - and a floor they cannot
    place against their own commission is a floor they will assume is a mistake.
    """
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _order(affiliate["id"], "1", 100_000)
    _hit_targets(admin, affiliate["id"], AUGUST, verified=True)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["guarantee_applied"] is True
    assert body["makeup"][0]["label"] == "Your guaranteed minimum"
    assert "commission" in body["makeup"][0]["detail"]


def test_a_guarantee_that_did_not_apply_is_still_named(admin):
    """The bug the browser found, and the screen it came from.

    Sara is on a guaranteed minimum of EGP 8,000. Their targets have not been
    recorded, so §9.5's comparison has no answer and they are paid their commission
    of EGP 1,100. Nothing about that figure is wrong - but the first version of
    this screen showed EGP 1,100 and never mentioned the guarantee at all, and
    the honest reading of that is *they have forgotten my minimum*.
    """
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _order(affiliate["id"], "1", 1_100_000)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["amount_piastres"] == 110_000
    assert body["guarantee"] == {
        "piastres": 800_000,
        "amount": "EGP 8,000.00",
        "applied": False,
        # §15. `null` is a third answer, and the one that decides which
        # sentence they read: nobody has recorded their month, rather than they
        # missed their targets.
        "targets_achieved": None,
        "targets_verified": False,
    }


def test_a_missed_target_says_so_without_calling_it_a_penalty(admin):
    """§11.3. A confirmed miss costs them the guarantee and nothing else - they
    are paid their commission, promptly, and the month approves.
    """
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _order(affiliate["id"], "1", 1_100_000)
    _missed_targets(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["guarantee"]["targets_achieved"] is False
    assert body["guarantee"]["applied"] is False
    # Missing a target is not missing information, so nothing blocks.
    assert body["waiting_on"] == []


def test_a_commission_only_month_has_no_guarantee_to_explain(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)

    assert _sign_in().get(f"/api/me/earnings/{AUGUST}").json()["guarantee"] is None


# -- §11.4: the order they sold in August and was paid for in September --------


def test_a_carried_order_names_the_month_that_paid_it(admin):
    """August's side. They counted August's orders themselves; the total is short
    by one, and this is the line that closes the gap.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)
    _order(affiliate["id"], "2", 200_000, state="pending")
    # Agreed before ADR 0040, which is what leaves an order behind at all:
    # the live rule counts a travelling order in its own month, so nothing
    # new is ever carried. The backlog is still paid, and still explained.
    with approved_before_the_switch():
        _approve(admin, affiliate["id"], AUGUST)

    _deliver("2")
    _approve(admin, affiliate["id"], SEPTEMBER)

    august = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert august["carried_out"] == [
        {
            "to_month": SEPTEMBER,
            "orders": 1,
            "base_piastres": 200_000,
            "base": "EGP 2,000.00",
        }
    ]
    late = next(row for row in august["orders_detail"] if row["order_number"] == "#2")
    assert late["paid_in_month"] == SEPTEMBER


def test_an_order_settled_by_its_own_month_is_not_labelled(admin):
    """Labelling every row would bury the one that matters."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["orders_detail"][0]["paid_in_month"] is None
    assert body["carried_out"] == []


def test_the_month_that_paid_it_says_where_it_came_from(admin):
    """September's side, at August's rate. ADR 0029.

    A rate change in September must not rewrite what an August sale was worth,
    so the carried line carries its own month's rate and says so.
    """
    affiliate = _affiliate(admin)
    # A rate change is a new period, never an edit - the database refuses two
    # that overlap, which is what keeps August's months on August's rate.
    _rate_change(
        admin,
        affiliate["id"],
        until=AUGUST,
        before_bp=1000,
        after_bp=2000,
        from_month=SEPTEMBER,
    )
    _order(affiliate["id"], "1", 100_000)
    _order(affiliate["id"], "2", 200_000, state="pending")
    # As above: only a delivered-only agreement leaves an order for a later
    # payroll to pay, and paying it at August's rate is what this checks.
    with approved_before_the_switch():
        _approve(admin, affiliate["id"], AUGUST)

    _deliver("2")

    september = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert september["carried_in"] == [
        {
            "from_month": AUGUST,
            "orders": 1,
            "base_piastres": 200_000,
            "base": "EGP 2,000.00",
            "commission_rate_bp": 1000,
            "piastres": 20_000,
            "amount": "EGP 200.00",
        }
    ]
    carried = next(
        line for line in september["makeup"] if line["label"].startswith("Carried")
    )
    assert "10% - that month's rate" in carried["detail"]


# -- §9.4: an order that did not arrive ---------------------------------------


def test_every_order_state_is_shown_in_their_words(admin):
    """A void order stays visible, and says **why** it is void.

    The approved chips are *Delivered*, *Pending* and *Failed delivery*. A
    courier's failure is the only void order that reads *Failed delivery*: a
    cancelled order and one refunded while travelling did not fail, and each
    keeps its own word. A delivered order later cancelled and refunded is
    still delivered, and still counted (F04).
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, state="earned")
    _order(affiliate["id"], "2", 200_000, state="pending")
    _order(affiliate["id"], "3", 300_000, state="void")
    _delivery("3", "failed")
    _order(affiliate["id"], "4", 0, state="void", placed=150_000)
    _order(affiliate["id"], "5", 80_000, state="void")
    _order(affiliate["id"], "6", 90_000, state="earned")
    _delivery("6", "delivered")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE order_index SET cancelled_at = now() "
                "WHERE shopify_order_id IN ('4', '6')"
            )
        )
        connection.execute(
            text(
                "UPDATE order_index SET financial_status = 'refunded' "
                "WHERE shopify_order_id IN ('5', '6')"
            )
        )

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    states = {row["order_number"]: row["state_text"] for row in body["orders_detail"]}
    assert states == {
        "#1": "Delivered",
        "#2": "Pending",
        "#3": "Failed delivery",
        "#4": "Cancelled",
        "#5": "Refunded",
        "#6": "Delivered",
    }
    statuses = {row["order_number"]: row["status"] for row in body["orders_detail"]}
    assert statuses["#6"] == "delivered", "refunded after delivery still counts"
    assert body["sales"]["pending_piastres"] == 200_000


# -- ADR 0036: a month from before the platform --------------------------------


def test_a_month_before_go_live_with_no_terms_shows_sales_and_says_why(
    admin, monkeypatch
):
    """**The fallback, not the normal shape.** ADR 0036 kept it deliberately.

    Once the pay history has been entered and the month approved, it comes back
    `agreed` like any other - see the test below. This is what is left when
    that has not happened, and a month whose terms nobody has entered cannot be
    calculated and must not be guessed at.

    An empty commission on a month full of sales reads as *HBA did not pay me
    for March*, so the reason travels with it.
    """
    from app.config import settings

    affiliate = _affiliate(admin)
    _order(affiliate["id"], "1", 100_000, month="2025-11")
    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    body = _sign_in().get("/api/me/earnings/2025-11").json()

    assert body["state"] == "historical"
    assert body["amount_piastres"] is None
    assert body["sales"]["earned_piastres"] == 100_000
    assert "HBA paid you" in body["note"]
    # Their words, not the platform's. They do not know what a platform is, and
    # a blank where the figure goes reads as *they did not pay me for March*.
    assert "platform" not in body["note"].lower()
    assert body["waiting_on"] == []


# -- Blockers, in language that does not accuse them ---------------------------


def test_a_month_with_no_terms_says_hba_has_not_set_them(admin):
    affiliate = _affiliate(admin)
    _order(affiliate["id"], "1", 100_000)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert [item["who"] for item in body["waiting_on"]] == ["hba"]
    assert "HBA has not set" in body["waiting_on"][0]["text"]


def test_unverified_targets_never_read_as_their_failure(admin):
    """`targets_achieved_but_not_verified` means they hit them and somebody here
    is slow. Shown raw it reads as an accusation.
    """
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _order(affiliate["id"], "1", 100_000)
    _hit_targets(admin, affiliate["id"], AUGUST, verified=False)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    waiting = body["waiting_on"][0]
    assert waiting["who"] == "hba"
    assert "You hit your targets" in waiting["text"]


def test_an_agreed_month_stays_settled_when_a_later_order_blocks_the_month(admin):
    """The live blocker list keeps answering *could this be approved now*, and
    after approval that question has a stale answer.

    A multi-code order landing in August after August was agreed blocks the
    month afresh - correctly, for the maintainer, who may still have to reopen
    it. To them it would read as "your September payment is stuck" on money that
    is already in their account.
    """
    affiliate = _affiliate(admin)
    _affiliate(admin, "Sara", "sara@example.com", "SARA10")
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)
    _approve(admin, affiliate["id"], AUGUST)

    # Two registered codes on one order: nobody owns it until a person decides.
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, "
                "placed_at, business_month, discount_codes, subtotal_piastres, "
                "total_piastres, shipping_piastres, tax_piastres, currency) "
                "VALUES ('9', '#9', now(), :m, ARRAY['NOUR10','SARA10'], "
                "50000, 50000, 0, 0, 'EGP')"
            ),
            {"m": AUGUST},
        )

    # The blocker is real: the maintainer's own view of the month says so.
    held = admin.get(f"/api/payroll/{AUGUST}").json()["affiliates"]
    mine = next(row for row in held if row["affiliate_id"] == affiliate["id"])
    assert "orders_held_for_multi_code_review" in mine["blockers"]

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["state"] == "agreed"
    assert body["waiting_on"] == []


def test_an_agreed_month_is_not_waiting_on_anything(admin):
    """*Already approved* is the good outcome, not a blocker. Showing it under
    "waiting on" would turn a finished month into a stuck one.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["waiting_on"] == []


# -- Which months they are offered ----------------------------------------------


def test_they_are_offered_their_own_months_newest_first(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, month="2026-07")

    body = _sign_in().get("/api/me/months").json()

    assert body["months"] == [SEPTEMBER, AUGUST, "2026-07"]
    assert body["working_month"] == SEPTEMBER


def test_months_before_they_joined_are_not_offered(admin):
    """An empty month from before they existed gives them no way to tell whether
    nothing happened or something is broken.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, month=SEPTEMBER)

    body = _sign_in().get("/api/me/months").json()

    assert body["months"] == [SEPTEMBER]


def test_a_model_with_nothing_yet_gets_this_month(admin):
    _affiliate(admin)

    body = _sign_in().get("/api/me/months").json()

    assert body["months"] == [SEPTEMBER]


def test_a_month_is_validated_before_anything_is_read(admin):
    _affiliate(admin)

    assert _sign_in().get("/api/me/earnings/august").status_code == 400


# -- §15: what was asked, and whether it changes what they are paid ------------


def test_a_target_says_whether_it_decides_their_pay(admin):
    """§15, and the clause that matters. On a guaranteed minimum a target
    decides money; on commission it is informational, and a model who reads a
    missed target as money gone has been told something untrue.
    """
    guaranteed = _affiliate(admin)
    commission = _affiliate(admin, "Sara", "sara@example.com", "SARA10")
    _terms(
        admin,
        guaranteed["id"],
        compensation_type="base_guarantee",
        base_amount_piastres=800_000,
    )
    _terms(admin, commission["id"])
    _hit_targets(admin, guaranteed["id"], AUGUST, verified=True)
    _hit_targets(admin, commission["id"], AUGUST, verified=True)

    mine = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()["targets"]
    theirs = _sign_in("sara@example.com").get(
        f"/api/me/earnings/{AUGUST}"
    ).json()["targets"]

    assert mine["determines_pay"] is True
    assert theirs["determines_pay"] is False
    assert mine["required_videos"] == 4
    assert mine["actual_stories"] == 8
    assert mine["achieved"] is True
    assert mine["verified"] is True


def test_a_month_with_no_target_recorded_has_nothing_to_show(admin):
    """Rather than a row of dashes. A target that was never set is not a target
    they failed, and where it *would* have decided their pay the guarantee note is
    already saying so in the one place they are looking.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000)

    assert _sign_in().get(f"/api/me/earnings/{AUGUST}").json()["targets"] is None


def test_nothing_about_a_target_can_be_changed_from_their_side(admin):
    """§6.5. They see what was recorded; recording is HBA's, and the portal
    offers no route that would let them touch it.
    """
    from app.api.affiliate_self import router

    writable = [
        route.path
        for route in router.routes
        if set(route.methods) - {"GET", "HEAD", "OPTIONS"}
    ]

    # **The whole list, on purpose.** This is the guard that says what a model
    # is allowed to change about themselves, and it fails when anybody adds a
    # route rather than when they add a bad one - which is the only way it
    # stays a decision rather than a habit.
    #
    # None of these touches a figure:
    #
    #   measurements       her height and her weight. A05 gives that write to
    #                      her and the read to staff, and **the absence of a
    #                      maintainer route is the enforcement** - a permission
    #                      check inside a shared service would still leave a
    #                      function an admin route could call. Added in 02B,
    #                      and this assertion failing is what made adding it a
    #                      decision rather than an afternoon.
    #   notifications      mutes an email.
    #   payout-destination moves where money is sent. The one that asks for a
    #                      password (§6.4.1).
    #   shipping-address   where a parcel goes. **Staff write this one too**
    #                      (D11), unlike her measurements - HBA types it into
    #                      the order, so a model who has moved must not become
    #                      a parcel that cannot be sent. Added in 03B.
    #
    # Only one of the four asks for a password, and the difference is the
    # subject rather than the sensitivity: the payout destination is where
    # *money* goes. Asking for a password before she corrects a house number
    # teaches her to type it into anything that asks.
    #
    # What is still absent is the point: nothing here writes a target, a rate,
    # an order or a month state.
    assert sorted(writable) == [
        "/api/me/measurements",
        "/api/me/notifications",
        "/api/me/payout-destination",
        "/api/me/shipping-address",
    ]


# -- §14: what has arrived ---------------------------------------------------


def test_an_unpaid_month_shows_what_is_outstanding(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get("/api/me/payments").json()

    assert body["months"] == [
        {
            "month": AUGUST,
            "state": "unpaid",
            "obligation_piastres": 100_000,
            "obligation": _egp(100_000),
            "paid_piastres": 0,
            "paid": _egp(0),
            "adjusted_piastres": 0,
            "adjusted": _egp(0),
            "credited_piastres": 0,
            "credited": _egp(0),
            "balance_piastres": 100_000,
            "balance": _egp(100_000),
        }
    ]
    assert body["outstanding_piastres"] == 100_000
    assert body["payments"] == []


def test_a_payment_says_when_it_arrived_and_what_it_settled(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)
    _pay(admin, affiliate["id"], AUGUST, 100_000)

    body = _sign_in().get("/api/me/payments").json()

    assert body["months"][0]["state"] == "settled"
    assert body["outstanding_piastres"] == 0

    payment = body["payments"][0]
    assert payment["amount_piastres"] == 100_000
    assert payment["settles"] == [
        {"month": AUGUST, "piastres": 100_000, "amount": _egp(100_000)}
    ]
    assert payment["reference"] == "IPN-77"


def test_a_month_still_being_worked_out_is_not_an_unpaid_bill(admin):
    """An open month has no agreed figure to settle against. Listing it here
    would put a debt on the screen for a number that is still moving.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)

    body = _sign_in().get("/api/me/payments").json()

    assert body["months"] == []
    assert body["outstanding_piastres"] == 0


def test_their_own_destination_stays_masked_on_the_payment(admin):
    """They supplied it, so it tells them nothing they do not know - and a
    screen printing an account number in full is one worth photographing over
    their shoulder.
    """
    affiliate = _affiliate(admin)
    _destination(admin, affiliate["id"])
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)
    _pay(admin, affiliate["id"], AUGUST, 100_000)

    body = _sign_in().get("/api/me/payments").json()

    served = str(body)
    assert ADDRESS not in served
    assert "01001234567" not in served


def test_a_month_settled_partly_without_a_transfer_says_so_on_its_own_row(admin):
    """The gap the browser found.

    A month agreed at 1,000 pounds, transferred as 940 with the remaining 60
    written off, is `settled` and correct. Their row read *E1,000.00 - paid* and
    the transfer below it read *E940.00*, which is sixty pounds short until they
    read a panel further down and connects it themselves.

    The row now carries both parts, so the arithmetic closes where they are
    looking.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)
    _pay(
        admin,
        affiliate["id"],
        AUGUST,
        94_000,
        note="Rounded down; the rest is being written off",
    )

    written_off = admin.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "writeoff",
            "source_month": AUGUST,
            "amount_piastres": 6_000,
            "reason": "Transfer fee absorbed by HBA",
        },
    )
    assert written_off.status_code == 201, written_off.text

    row = _sign_in().get("/api/me/payments").json()["months"][0]

    assert row["state"] == "settled"
    assert row["obligation_piastres"] == 100_000
    assert row["paid_piastres"] == 94_000
    assert row["adjusted_piastres"] == 6_000
    # The three account for each other exactly. That is the property the row
    # exists to let them check.
    assert row["paid_piastres"] + row["adjusted_piastres"] == row[
        "obligation_piastres"
    ]
    assert row["balance_piastres"] == 0


# -- §11.5: a credit they cannot see is a credit they cannot check -------------


def test_an_adjustment_is_visible_to_them_with_its_reason(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)

    made = admin.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "writeoff",
            "source_month": AUGUST,
            "amount_piastres": 25_000,
            "reason": "Transfer fee absorbed by HBA",
        },
    )
    assert made.status_code == 201, made.text

    body = _sign_in().get("/api/me/payments").json()

    assert len(body["adjustments"]) == 1
    adjustment = body["adjustments"][0]
    assert adjustment["kind"] == "writeoff"
    assert adjustment["kind_text"] == "Written off by HBA"
    assert adjustment["amount_piastres"] == 25_000
    assert adjustment["reason"] == "Transfer fee absorbed by HBA"
    assert adjustment["from_month"] == AUGUST


# -- §14 and ADR 0017: the screenshot ----------------------------------------


def test_they_can_see_the_screenshot_of_their_own_payment(admin):
    """Visible proof removes an entire category of *did you send it?* messages,
    which is the whole reason it is kept.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)
    payment_id = _pay(
        admin, affiliate["id"], AUGUST, 100_000, proof=_proof(admin, affiliate["id"])
    )

    model = _sign_in()
    assert model.get("/api/me/payments").json()["payments"][0]["has_proof"] is True

    served = model.get(f"/api/me/payments/{payment_id}/proof")

    assert served.status_code == 200
    # Re-encoded on the way in, so what comes back is a JPEG whatever was sent.
    assert served.headers["content-type"] == "image/jpeg"
    assert served.content[:2] == b"\xff\xd8"


def test_one_models_screenshot_is_not_served_to_another(admin):
    """§14. Served **only to the affiliate it belongs to** - and the risk ADR
    0017 accepted was exposure to them, not to everybody on the programme.
    """
    nour = _affiliate(admin)
    _affiliate(admin, "Sara", "sara@example.com", "SARA10")
    _terms(admin, nour["id"])
    _order(nour["id"], "1", 1_000_000)
    _approve(admin, nour["id"], AUGUST)
    payment_id = _pay(
        admin, nour["id"], AUGUST, 100_000, proof=_proof(admin, nour["id"])
    )

    sara = _sign_in("sara@example.com")

    assert sara.get(f"/api/me/payments/{payment_id}/proof").status_code == 404
    assert sara.get("/api/me/payments").json()["payments"] == []


def test_a_payment_with_no_screenshot_says_so_rather_than_erroring(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000)
    _approve(admin, affiliate["id"], AUGUST)
    payment_id = _pay(admin, affiliate["id"], AUGUST, 100_000)

    model = _sign_in()

    assert model.get("/api/me/payments").json()["payments"][0]["has_proof"] is False
    assert model.get(f"/api/me/payments/{payment_id}/proof").status_code == 404


def test_the_payment_routes_refuse_a_maintainer(admin):
    """Two gates, never mixed. There is already an admin route for both."""
    assert admin.get("/api/me/payments").status_code == 403
    assert admin.get("/api/me/payments/1/proof").status_code == 403


# -- A month the calendar has not reached (Phase 10) -------------------------


def test_a_month_that_has_not_started_says_so(admin, monkeypatch):
    """The first thing twenty people will see.

    A model invited before go-live opens on the go-live month, and that month
    has nothing in it. *Still adding up, nothing* is true and lands as though
    the platform is broken or they have earned nothing.
    """
    from datetime import datetime, timezone

    import app.services.portal as portal

    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])

    # The clock says August, pinned rather than assumed - a suite that only
    # passed because it happened to run before September silently broke the
    # day it did not (found on 2026-09-01, mid-session).
    monkeypatch.setattr(
        portal, "utcnow", lambda: datetime(2026, 8, 15, tzinfo=timezone.utc)
    )
    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["not_started"] is True
    assert body["state"] == "open"


def test_a_month_that_has_begun_does_not(admin):
    """August is the current month in this suite, so it has started - and an
    open month with no sales yet is a completely different sentence.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert body["not_started"] is False


def test_a_historical_month_never_reads_as_not_started(admin, monkeypatch):
    """It is the opposite: settled long ago, not yet to come."""
    from app.config import settings

    affiliate = _affiliate(admin)
    _order(affiliate["id"], "1", 100_000, month="2025-11")
    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    body = _sign_in().get("/api/me/earnings/2025-11").json()

    assert body["state"] == "historical"
    assert body["not_started"] is False


def test_a_historical_month_counts_its_orders_the_same_way(admin, monkeypatch):
    """The business's addition, and it is right: the orders are real and the
    counting is real. Only the *payment* happened elsewhere.

    Reporting one lump of sales and nothing else made a month they worked look
    like a month that did not happen.
    """
    from app.config import settings

    affiliate = _affiliate(admin)
    _order(affiliate["id"], "h1", 100_000, month="2025-11", state="earned")
    _order(affiliate["id"], "h2", 40_000, month="2025-11", state="pending")
    _order(affiliate["id"], "h3", 25_000, month="2025-11", state="void")
    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    body = _sign_in().get("/api/me/earnings/2025-11").json()

    assert body["state"] == "historical"
    # R3. The same shape as any other month, counted the same way: what she
    # sold is not a question the platform answers differently either side of
    # go-live.
    # A08 added `uses` to this shape, and all three orders are uses: the
    # helper leaves `delivery_state` unresolved, and D03 counts an order the
    # courier has not answered for. A use is a delivery outcome and the three
    # counts beside it are commission states, so the void order appearing in
    # one and not the other is the distinction working rather than a
    # miscount.
    assert body["orders"] == {
        "earned": 1,
        "pending": 1,
        "void": 1,
        "counted": 2,
        "uses": 3,
    }
    assert body["sales"]["counted_piastres"] == 140_000
    assert body["sales"]["earned_piastres"] == 100_000
    assert body["sales"]["pending_piastres"] == 40_000
    assert body["sales"]["failed_piastres"] == 25_000
    # And every order is listed, exactly as in any other month.
    assert len(body["orders_detail"]) == 3
    # The one thing still withheld: March's rates live in the old system, and
    # guessing at them is how somebody is told the wrong number (ADR 0014).
    assert body["amount_piastres"] is None


# -- Their year (the fifth screen) ---------------------------------------------


def test_the_year_reports_earnings_and_orders_as_different_things(admin):
    """The constraint the business set, and it is the whole design.

    The first attempt charted earnings *and* sales. On a commission
    arrangement those move together, so drawing both is drawing one thing with
    two y-axes - which is exactly what they said on seeing it.

    So one series is money and the other is a count. Sales travel with the
    order count, where they make a bar mean something rather than repeating
    the line.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 1_000_000, month="2026-07")
    _order(affiliate["id"], "2", 400_000, month=AUGUST)
    _order(affiliate["id"], "3", 600_000, month=AUGUST)

    body = _sign_in().get("/api/me/year").json()

    august = next(m for m in body["months"] if m["month"] == AUGUST)
    assert august["orders"] == 2
    assert august["sales_piastres"] == 1_000_000
    assert august["earned_piastres"] == 100_000
    # A number for the axis, not a name to translate.
    assert august["number"] == 8


def test_the_year_reads_left_to_right(admin):
    """Oldest first. A chart is read in one direction and the data should
    arrive in it.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, month="2026-07")
    _order(affiliate["id"], "2", 100_000, month=AUGUST)

    months = [m["month"] for m in _sign_in().get("/api/me/year").json()["months"]]

    assert months == sorted(months)


def test_a_month_before_go_live_has_no_figure_rather_than_a_zero(admin, monkeypatch):
    """The same fallback, on the Year chart.

    A zero is a claim that they earned nothing. They did not - the commission
    was agreed elsewhere, and the sales are still real. Once the month is
    approved the point fills in, which is the test below.
    """
    from app.config import settings

    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "old", 500_000, month="2025-11")
    _order(affiliate["id"], "new", 100_000, month=AUGUST)
    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)

    body = _sign_in().get("/api/me/year").json()
    old = next(m for m in body["months"] if m["month"] == "2025-11")

    assert old["earned_piastres"] is None
    assert old["sales_piastres"] == 500_000
    assert old["orders"] == 1
    # And it is excluded from the totals, which are about what they were paid
    # through this platform.
    assert body["total_earned_piastres"] == 10_000


def test_the_year_is_hers_alone(admin):
    _affiliate(admin)
    _affiliate(admin, "Sara", "sara@example.com", "SARA10")

    assert admin.get("/api/me/year").status_code == 403
    assert _sign_in().get("/api/me/year").status_code == 200


# ── Phase 2: the month window, the average order, and the three arrangements ──
#
# `docs/plans/2026-09-03-portal-redesign.md`. The design prototype the business
# built modelled one kind of model - pure commission - and printed a sentence
# under the targets saying they never affect pay. These are the tests that stop
# that sentence, or anything like it, reaching a screen where it would be false.


def test_a_salary_model_is_paid_the_salary_and_the_commission(admin):
    """`fixed_plus_commission` means *both*, and the breakdown has to show both.

    The one rule in the whole compensation model most easily got wrong from its
    name, and it was got wrong twice while this screen was being designed - by
    the prototype, and by the first preview built from it, which showed the
    salary alone. The engine was right each time. This is here so the screen
    cannot drift away from it again.
    """
    affiliate = _affiliate(admin)
    _terms(
        admin,
        affiliate["id"],
        compensation_type="fixed_plus_commission",
        fixed_amount_piastres=900_000,
    )
    _order(affiliate["id"], "9101", 100_000, month=SEPTEMBER)
    _deliver("9101")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    labels = [line["label"] for line in body["makeup"]]

    assert "Commission on this month's sales" in labels
    assert "Your monthly salary" in labels
    # 10% of EGP 1,000 is EGP 100, and the salary is EGP 9,000 on top - never instead.
    assert body["amount_piastres"] == 910_000
    assert sum(line["piastres"] for line in body["makeup"]) == body["amount_piastres"]


@pytest.mark.parametrize(
    ("kind", "extra", "decides"),
    [
        ("commission", {}, False),
        ("fixed_plus_commission", {"fixed_amount_piastres": 900_000}, False),
        ("base_guarantee", {"base_amount_piastres": 500_000}, True),
    ],
)
def test_only_a_guarantee_lets_targets_decide_pay(admin, kind, extra, decides):
    """`determines_pay` is what the sentence under the targets is driven by.

    It is true on exactly one arrangement. On the other two a missed target
    costs nothing, and a screen that could not tell the difference would teach
    somebody to read every shortfall as money gone.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], compensation_type=kind, **extra)
    _hit_targets(admin, affiliate["id"], SEPTEMBER, verified=False)

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["targets"]["determines_pay"] is decides


def test_a_month_with_no_terms_says_it_is_hba_who_has_not_finished(admin):
    """Every blocker is HBA's own work, and the screen has to say so.

    §11.3 blocks on missing information, and all of the information missing is
    information HBA records. A blocker that did not name whose move it is reads
    as an accusation - `targets_achieved_but_not_verified` especially, which
    means they hit them and somebody here is slow.
    """
    affiliate = _affiliate(admin)  # deliberately no compensation terms

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["waiting_on"], "a month nobody can calculate must say why"
    assert all(item["who"] == "hba" for item in body["waiting_on"])
    assert any("HBA" in item["text"] for item in body["waiting_on"])


def test_the_month_window_says_when_it_closes(admin):
    """The second question - *when does it land* - had no answer on the screen."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["window"]["opens"] == "2026-09-01"
    # September has thirty days, and a table of month lengths is exactly the
    # sort of thing that is right until February.
    assert body["window"]["closes"] == "2026-09-30"
    assert 0 <= body["window"]["progress_pct"] <= 100


def test_an_agreed_month_is_finished_whatever_the_calendar_says(admin):
    """Approval is what ends a month, not the last day of it.

    So a month agreed early is full and has no days left - a progress bar
    still filling under a figure that cannot change would be describing a
    month that is already over.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9102", 100_000, month=SEPTEMBER)
    _deliver("9102")
    _approve(admin, affiliate["id"], SEPTEMBER)

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["state"] == "agreed"
    assert body["window"]["progress_pct"] == 100
    assert body["window"]["days_left"] is None


def test_the_average_order_is_absent_rather_than_zero(admin):
    """Nothing to average is not the same as an average of nothing.

    A zero here would be a claim that a typical order under their code is worth
    nothing, which on a month before their first sale is both false and the
    worst possible first impression.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    client = _sign_in()

    empty = client.get(f"/api/me/earnings/{SEPTEMBER}").json()
    assert empty["sales"]["average_order_piastres"] is None
    assert empty["sales"]["average_order"] is None

    _order(affiliate["id"], "9103", 100_000, month=SEPTEMBER)
    _order(affiliate["id"], "9104", 50_000, month=SEPTEMBER)
    _deliver("9103")
    _deliver("9104")

    counted = client.get(f"/api/me/earnings/{SEPTEMBER}").json()
    assert counted["sales"]["average_order_piastres"] == 75_000
    assert counted["sales"]["average_order"] == _egp(75_000)


def test_a_travelling_order_is_part_of_the_average(admin):
    """R3, F02. The average is of the orders the month is paid on.

    It left a travelling order out, on the reasoning that it had no settled
    base - true while the month did not count it, and false since. An average
    over the delivered half, printed beside a figure earned on both, describes
    no month she had.

    A failed delivery is still excluded: it earned nothing and never will.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9105", 100_000, month=SEPTEMBER)
    _deliver("9105")
    _order(affiliate["id"], "9106", 900_000, month=SEPTEMBER, state="pending")
    _order(affiliate["id"], "9107", 800_000, month=SEPTEMBER, state="void")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    # EGP 10,000 over two counted orders.
    assert body["sales"]["average_order_piastres"] == 500_000
    assert body["sales"]["counted_piastres"] == 1_000_000


# ── Phase 3: what one order was worth ────────────────────────────────────────


def test_an_order_row_carries_the_commission_it_earned(admin):
    """The worked example, computed on the server like every other figure.

    §11.1's rule about a second implementation of what somebody is owed
    applies to one order as much as to a month. The browser is handed the
    answer; it never multiplies anything.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1500)
    _order(affiliate["id"], "9201", 84_915, month=SEPTEMBER)
    _deliver("9201")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9201"]

    # 15% of EGP 849.15 is EGP 127.3725, exact to the piastre before any rounding.
    assert row["commission_piastres"] == 12_737
    assert row["commission"] == _egp(12_737)


def test_the_rows_agree_with_the_month_they_are_part_of(admin):
    """Per-order figures and the month's commission line describe one thing.

    ADR 0004 divides one numerator once for the whole month, so the rows can
    miss the total by rounding - but only by rounding. A gap wider than the
    number of rows would mean the two were computed from different rates or
    different orders, which is the failure this is here to catch.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1500)
    for index, base in enumerate((84_915, 50_915, 50_915), start=1):
        _order(affiliate["id"], f"930{index}", base, month=SEPTEMBER)
        _deliver(f"930{index}")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    rows = sum(
        o["commission_piastres"]
        for o in body["orders_detail"]
        if o["commission_piastres"] is not None
    )
    (line,) = [
        m for m in body["makeup"] if m["label"] == "Commission on this month's sales"
    ]
    counted = len([o for o in body["orders_detail"] if o["state"] == "earned"])

    assert abs(rows - line["piastres"]) <= counted


def _row(month, number):
    body = _sign_in().get(f"/api/me/earnings/{month}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == number]
    return body, row


def _set(order_id: str, **columns) -> None:
    """Change an attributed order the way a later Shopify fact would."""
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE attributed_order SET {assignments} "
                "WHERE shopify_order_id = :i"
            ),
            {"i": order_id, **columns},
        )


def test_a_pending_order_shows_the_commission_it_counts_for(admin):
    """The owner asked for it, and ADR 0040 is why it is true.

    EGP 2,000 on its way at 10% is EGP 200: the month is paid on it, so its
    row says what it is worth rather than a dash.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9801", 200_000, month=SEPTEMBER, state="pending")

    body, row = _row(SEPTEMBER, "#9801")

    assert row["commission_piastres"] == 20_000
    assert row["commission"] == _egp(20_000)
    assert row["counted"] is True
    assert row["rate_missing"] is False
    assert row["forgone_piastres"] is None
    assert body["amount_piastres"] == 20_000, "the month counts it too"
    assert body["policy"] == "pending_inclusive"


def test_delivery_leaves_the_commission_where_it_was(admin):
    """Pending to delivered is the same order arriving: EGP 200 before and
    after, one row, and the month does not count it twice."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9802", 200_000, month=SEPTEMBER, state="pending")

    _deliver("9802")
    body, row = _row(SEPTEMBER, "#9802")

    assert row["state"] == "earned"
    assert row["commission_piastres"] == 20_000
    assert len(body["orders_detail"]) == 1
    assert body["amount_piastres"] == 20_000


def test_a_failed_delivery_leaves_the_count_and_is_struck_through(admin):
    """What it would have earned stays on the row, struck through - the
    approved portal's failed-delivery presentation - and no total includes it.

    The base survives the failure (F03, `attribute_order`), so the figure is
    worked out on that rather than on a placed-at value it does not need.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9803", 200_000, month=SEPTEMBER, state="pending")

    _set("9803", commission_state="void")
    body, row = _row(SEPTEMBER, "#9803")

    assert row["commission_piastres"] is None
    assert row["counted"] is False
    assert row["forgone_piastres"] == 20_000
    assert row["forgone"] == _egp(20_000)
    assert body["amount_piastres"] == 0
    assert body["sales"]["counted_piastres"] == 0


def test_a_refund_after_delivery_keeps_the_commission(admin):
    """F04: delivery is the end of the story. The order stays earned (the
    ingestion path is pinned in `test_best_sellers`), and its row keeps its
    EGP 200 with the refund recorded beside it."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9804", 200_000, month=SEPTEMBER, state="pending")
    _deliver("9804")

    _set(
        "9804",
        financial_status="refunded",
        return_status="returned",
        refunded_merchandise_piastres=200_000,
    )
    body, row = _row(SEPTEMBER, "#9804")

    assert row["commission_piastres"] == 20_000
    assert body["amount_piastres"] == 20_000


def test_a_pending_order_keeps_its_own_months_rate(admin):
    """Today's raise does not reach back: August's pending EGP 1,000 is worth
    August's 10%, EGP 100, not September's 20%."""
    affiliate = _affiliate(admin)
    _rate_change(
        admin,
        affiliate["id"],
        until=AUGUST,
        before_bp=1000,
        after_bp=2000,
        from_month=SEPTEMBER,
    )
    _order(affiliate["id"], "9805", 100_000, month=AUGUST, state="pending")
    _order(affiliate["id"], "9806", 100_000, month=SEPTEMBER, state="pending")

    _, august = _row(AUGUST, "#9805")
    _, september = _row(SEPTEMBER, "#9806")

    assert august["commission_piastres"] == 10_000
    assert september["commission_piastres"] == 20_000


def test_no_rate_is_not_available_rather_than_zero(admin):
    """A month nobody set terms for cannot be answered, and says so."""
    affiliate = _affiliate(admin)
    _order(affiliate["id"], "9807", 200_000, month=SEPTEMBER, state="pending")

    _, row = _row(SEPTEMBER, "#9807")

    assert row["commission_piastres"] is None
    assert row["commission"] is None
    assert row["rate_missing"] is True
    assert row["counted"] is True


def test_a_valid_zero_is_a_figure_not_an_absence(admin):
    """An order the customer paid nothing for earned exactly nothing, at a
    rate that exists - `EGP 0.00`, distinguishable from *not available*."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9808", 0, month=SEPTEMBER, state="pending")

    _, row = _row(SEPTEMBER, "#9808")

    assert row["commission_piastres"] == 0
    assert row["commission"] == _egp(0)
    assert row["rate_missing"] is False


def test_an_agreed_month_reports_the_rule_it_was_agreed_under(admin):
    """A pending-inclusive approval says so, and so does the statement."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9809", 200_000, month=AUGUST, state="pending")
    _approve(admin, affiliate["id"], AUGUST)

    body, row = _row(AUGUST, "#9809")
    statement = admin.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()

    assert body["state"] == "agreed"
    assert body["policy"] == "pending_inclusive"
    assert row["commission_piastres"] == 20_000
    assert statement["policy"] == "pending_inclusive"
    assert statement["counted_sales_piastres"] == 200_000


def test_a_month_agreed_delivered_only_is_described_as_it_was_agreed(admin):
    """An older snapshot carries no policy, which means delivered-only.

    Its figures do not move, it is not described as counting pending, and a
    pending order in it shows no commission there - it was left for the
    payroll after it arrives (§11.4). The live rule is not applied backwards.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9810", 100_000, month=AUGUST)
    _deliver("9810")
    _order(affiliate["id"], "9811", 200_000, month=AUGUST, state="pending")
    # Approved through the ordinary path with the old rule restored around it:
    # the snapshot is append-only, so a legacy month is born, not edited.
    with approved_before_the_switch():
        _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()
    delivered = next(o for o in body["orders_detail"] if o["order_number"] == "#9810")
    pending = next(o for o in body["orders_detail"] if o["order_number"] == "#9811")
    statement = admin.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()

    assert body["policy"] == "delivered_only"
    assert body["amount_piastres"] == 10_000, "10% of the delivered EGP 1,000 only"
    assert delivered["commission_piastres"] == 10_000
    assert pending["counted"] is False
    assert pending["commission_piastres"] is None
    assert statement["policy"] == "delivered_only"
    assert statement["counted_sales_piastres"] == 100_000


def test_a_delivery_that_fails_after_approval_says_so(admin):
    """The approved sentence for a late failure: counted by August's
    agreement, then failed - the difference is settled later (05C), and the
    row says that rather than pretending August never counted it."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1000)
    _order(affiliate["id"], "9812", 200_000, month=AUGUST, state="pending")
    _order(affiliate["id"], "9813", 100_000, month=AUGUST, state="pending")
    _approve(admin, affiliate["id"], AUGUST)
    _set("9812", commission_state="void")
    _delivery("9812", "failed")
    _deliver("9813")

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()
    failed = next(o for o in body["orders_detail"] if o["order_number"] == "#9812")
    delivered = next(o for o in body["orders_detail"] if o["order_number"] == "#9813")

    assert failed["status"] == "failed"
    assert failed["state_text"] == "Failed delivery"
    assert failed["failed_after_approval"] is True
    assert failed["forgone_piastres"] == 20_000
    assert delivered["failed_after_approval"] is False
    # *Commission is 10% of EGP 1,000.00* - August's own rate, from its snapshot.
    assert delivered["rate_bp"] == 1000
    assert delivered["commission_piastres"] == 10_000


def test_an_order_is_worth_the_rate_of_its_own_month(admin):
    """§11.4's rule, applied to the row as well as to the carry.

    An order sold in August is worth August's percentage when it is read in
    September. Reading it at today's rate would show somebody a figure their
    payment never used.
    """
    affiliate = _affiliate(admin)
    # A raise from September onward. August must not follow it.
    _rate_change(
        admin,
        affiliate["id"],
        until=AUGUST,
        before_bp=1000,
        after_bp=2000,
        from_month=SEPTEMBER,
    )
    _order(affiliate["id"], "9501", 100_000, month=AUGUST)
    _deliver("9501")

    august = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()
    (row,) = [o for o in august["orders_detail"] if o["order_number"] == "#9501"]

    assert row["commission_piastres"] == 10_000, "August is 10%, not September's 20%"


# ── A cancelled order still says what it was ────────────────────────────────
#
# Shopify zeroes the current totals on a cancelled order, and the platform
# stores those because §9.3 pays on what the customer actually paid. The
# consequence reached a model's screen: a struck-through EGP 0.00, which claims
# the order was worth nothing *and* was cancelled. `original_total_piastres`
# keeps the placed-at figure so the row can say what it was.


def test_a_cancelled_order_still_says_what_it_came_to(admin):
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    # Cancelled: Shopify reports it worth nothing now, and EGP 1,200 when placed.
    _order(affiliate["id"], "9601", 0, month=SEPTEMBER, state="void", placed=120_000)

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9601"]

    assert row["base_piastres"] == 0, "it is worth nothing now, and says so"
    assert row["placed_piastres"] == 120_000
    assert row["placed"] == _egp(120_000)


def test_the_placed_figure_is_absent_where_the_base_already_says_it(admin):
    """No screen should be able to show the same money twice under two labels."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9602", 120_000, month=SEPTEMBER, placed=120_000)
    _deliver("9602")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9602"]

    assert row["base_piastres"] == 120_000
    assert row["placed_piastres"] is None


def test_an_order_indexed_before_the_column_existed_offers_no_figure(admin):
    """`NULL` is *we never asked Shopify*, and must not become a zero.

    A zero would be indistinguishable from an order that was genuinely free,
    and would put "EGP 0.00" back on the screen this whole change removed it
    from.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9603", 0, month=SEPTEMBER, state="void", placed=None)

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9603"]

    assert row["placed_piastres"] is None
    assert row["placed"] is None


def test_the_placed_figure_is_never_paid_on(admin):
    """The rule the whole change hangs on.

    These columns exist so a screen can say what a cancelled order was. If
    they ever reached `calculate.py`, HBA would be paying commission on
    parcels that were cancelled.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1500)
    _order(affiliate["id"], "9604", 0, month=SEPTEMBER, state="void", placed=500_000)

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["amount_piastres"] == 0, "a cancelled order earns nothing"
    assert body["sales"]["earned_piastres"] == 0
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9604"]
    assert row["commission_piastres"] is None


# ── Batch 3: a void row keeps its figures, and the year drops today ─────────


def test_a_void_order_says_what_it_would_have_earned(admin):
    """The business asked for the figure rather than the words.

    "Nothing earned" says what did not happen and gives a model nothing to
    check against her own record. The forgone commission is shown struck
    through beside the value it would have earned it on.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1500)
    _order(
        affiliate["id"], "9701", 0, month=SEPTEMBER, state="void", placed=120_000
    )

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9701"]

    assert row["placed_piastres"] == 120_000
    # 15% of EGP 1,200 is EGP 180.
    assert row["forgone_piastres"] == 18_000
    assert row["forgone"] == _egp(18_000)


def test_the_forgone_figure_never_reaches_a_total(admin):
    """It is money that did not happen. No figure on any screen includes it."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=1500)
    _order(
        affiliate["id"], "9702", 0, month=SEPTEMBER, state="void", placed=500_000
    )

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert body["amount_piastres"] == 0
    assert body["sales"]["earned_piastres"] == 0
    assert body["sales"]["average_order_piastres"] is None


def test_an_order_still_travelling_has_forgone_nothing(admin):
    """It has not lost anything *yet*, which is a different sentence from a
    parcel that never arrived."""
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9703", 100_000, month=SEPTEMBER, state="pending")

    body = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()
    (row,) = [o for o in body["orders_detail"] if o["order_number"] == "#9703"]

    assert row["forgone_piastres"] is None


def test_the_year_leaves_out_the_month_in_progress(admin):
    """A part-month drawn beside finished ones reads as a collapse.

    September at three days old plotted next to a full August made the line
    fall off a cliff, and the business asked for it to wait until the month
    ends.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9801", 1_000_000, month=AUGUST)
    _deliver("9801")
    _approve(admin, affiliate["id"], AUGUST)
    _order(affiliate["id"], "9802", 500_000, month=SEPTEMBER)
    _deliver("9802")

    body = _sign_in().get("/api/me/year").json()
    by_month = {row["month"]: row for row in body["months"]}

    # Still returned, so the screen can say why it is absent rather than
    # simply losing it.
    assert by_month[SEPTEMBER]["in_progress"] is True
    assert by_month[AUGUST]["in_progress"] is False

    # And every summary covers the closed months only, so the headline can be
    # reached by adding up the points on screen.
    assert body["total_earned_piastres"] == by_month[AUGUST]["earned_piastres"]
    assert body["best_month"] == AUGUST
    assert body["closed_months"] == 1


def test_orders_are_counted_across_every_month_including_today(admin):
    """A tally of things that happened, not a figure still being decided.

    Leaving today's out would under-report her own work.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "9803", 1_000_000, month=AUGUST)
    _deliver("9803")
    _order(affiliate["id"], "9804", 500_000, month=SEPTEMBER)
    _deliver("9804")

    body = _sign_in().get("/api/me/year").json()

    assert body["total_orders"] == 2


# -- ADR 0036: an approved month from before the platform is an ordinary month --


MARCH = "2026-03"


def _backfilled(admin, monkeypatch, *, base=500_000, rate_bp=1000, outcome=None):
    """A model whose March has terms, orders and an approved payroll.

    **The order of these lines is the order the business has to work in, and it
    is not a convenience.** Terms, then targets, then approval: both
    `assert_correctable` and `assert_month_recordable` refuse to change what an
    approved month was calculated from, so approving comes last.

    The go-live month moves partway through on purpose. The terms and the
    orders are entered while March is still an ordinary month; approval happens
    once it is behind go-live, which is the situation in production.
    """
    from app.config import settings
    from app.db import SessionLocal
    from app.services.affiliates import get_affiliate
    from app.services.targets import record_outcome

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], rate_bp=rate_bp, start="2026-01")
    _order(affiliate["id"], "march", base, month=MARCH)
    _order(affiliate["id"], "august", 100_000, month=AUGUST)
    monkeypatch.setattr(settings, "go_live_month", "2026-08", raising=False)

    if outcome is not None:
        with SessionLocal() as session:
            record_outcome(
                session,
                get_affiliate(session, affiliate["id"]),
                MARCH,
                outcome=outcome,
            )
            session.commit()

    _approve(admin, affiliate["id"], MARCH)
    return affiliate


def test_an_approved_month_before_go_live_reads_exactly_like_a_later_one(
    admin, monkeypatch
):
    """**The whole of task #17, in one assertion.**

    The business's words: *"I don't want the models to feel that we treated
    them differently."* March has a figure, a state of `agreed`, and no word
    anywhere saying it is a lesser kind of month.
    """
    _backfilled(admin, monkeypatch)

    body = _sign_in().get(f"/api/me/earnings/{MARCH}").json()

    assert body["state"] == "agreed"
    assert body["amount_piastres"] == 50_000
    assert body["sales"]["earned_piastres"] == 500_000
    assert body["note"] is None
    assert "historical" not in str(body).lower()


def test_the_year_chart_draws_a_backfilled_month_like_the_rest(
    admin, monkeypatch
):
    """ADR 0036. Seven months of her own year drawn hollow, next to two that
    were real, is the feeling being removed.
    """
    _backfilled(admin, monkeypatch)

    body = _sign_in().get("/api/me/year").json()
    march = next(m for m in body["months"] if m["month"] == MARCH)

    assert march["earned_piastres"] == 50_000
    assert march["state"] == "agreed"
    # And it counts. A total that skipped it would disagree with the chart it
    # sits under, which is the one thing the Year screen may never do.
    assert body["total_earned_piastres"] >= 50_000


def test_a_backfilled_month_is_never_owed_and_never_listed_as_unpaid(
    admin, monkeypatch
):
    """The protection ADR 0014 gave, kept where approving cannot bypass it.

    March is agreed at EGP 500 and nothing about it is outstanding. A row here
    reading "not paid yet" would be a debt that never existed.
    """
    _backfilled(admin, monkeypatch)

    body = _sign_in().get("/api/me/payments").json()

    assert [row["month"] for row in body["months"]] == []
    assert body["outstanding_piastres"] == 0


def test_the_old_dashboard_is_named_once_and_only_to_somebody_who_had_one(
    admin, monkeypatch
):
    """ADR 0036. One line, on the Payments tab, and nowhere else.

    Without it the list starting at go-live reads as *my earlier months are
    missing*. With a banner it reads as an apology for records nobody had
    reason to doubt.
    """
    _backfilled(admin, monkeypatch)

    body = _sign_in().get("/api/me/payments").json()

    assert body["settled_outside"] is not None
    assert MARCH in body["settled_outside"]["months"]
    assert "HBA paid you" in body["settled_outside"]["text"]


def test_a_model_who_joined_after_go_live_never_learns_there_was_an_old_one(
    admin, monkeypatch
):
    """The conditional half of the decision, and the reason it is conditional.

    A model who joins in October has no month before go-live. Telling her the
    platform replaced something invites a question about records she has no
    reason to doubt.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-08", raising=False)
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"], start=AUGUST)
    _order(affiliate["id"], "august", 100_000, month=AUGUST)
    _approve(admin, affiliate["id"], AUGUST)

    body = _sign_in().get("/api/me/payments").json()

    assert body["settled_outside"] is None


def test_a_backfilled_target_shows_an_outcome_and_no_counts(admin, monkeypatch):
    """ADR 0036, and the one place a month before go-live reads differently
    from a new one - because it *is* different.

    The business knows March's target was met. It does not have March's video
    and story numbers, and inventing them to match would be fabricating
    evidence for a figure that decides money.
    """
    _backfilled(admin, monkeypatch, outcome="met")

    body = _sign_in().get(f"/api/me/earnings/{MARCH}").json()

    assert body["targets"]["numbers_kept"] is False
    assert body["targets"]["required_videos"] is None
    assert body["targets"]["actual_videos"] is None
    assert body["targets"]["achieved"] is True
    assert body["targets"]["verified"] is True


def _target_revision(admin, month):
    """What the targets grid looked like when it was last read.

    Fetched rather than remembered: these helpers set a target and move on, and
    the revision is only here to satisfy the concurrency check 04A added.
    """
    return admin.get(f"/api/targets/{month}").json()["revision"]


# -- §15 / UI24: her own targets, current and past ----------------------------


def test_her_targets_cover_every_month_she_can_look_at(admin):
    """The tab answers *how has this been going*, which one month cannot.

    Same months as her picker, newest first. A history that stopped at the
    months somebody happened to set a target for would silently hide the ones
    nobody set - and those are the months that block a guaranteed minimum.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, month=AUGUST)
    _hit_targets(admin, affiliate["id"], AUGUST, verified=True)

    her = _sign_in()
    listed = her.get("/api/me/months").json()["months"]
    rows = her.get("/api/me/targets").json()["months"]

    assert [row["month"] for row in rows] == listed


def test_an_unrecorded_month_is_not_a_missed_one(admin):
    """§11.3, and the mistake that would matter most.

    An unrecorded month is what stops a guaranteed minimum. Showing it as a
    miss tells her the month is lost when it is merely waiting on HBA, and
    sends her to ask about the wrong thing.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, month=AUGUST)

    rows = _sign_in().get("/api/me/targets").json()["months"]
    august = next(row for row in rows if row["month"] == AUGUST)

    assert august["achieved"] is None
    assert august["actual_videos"] is None
    assert august["required_videos"] is None
    # Not `False`, which would say *the numbers were lost* about a month where
    # nothing was ever asked.
    assert august["numbers_kept"] is None


def test_her_history_shows_an_outcome_and_no_counts_for_an_old_month(
    admin, monkeypatch
):
    """ADR 0036 and H02, from her side of the screen.

    The business knows March was met. It does not know March's numbers, and
    inventing them to match the outcome would be fabricating the evidence for
    a figure that decided her pay.
    """
    _backfilled(admin, monkeypatch, outcome="met")

    rows = _sign_in().get("/api/me/targets").json()["months"]
    march = next(row for row in rows if row["month"] == MARCH)

    assert march["achieved"] is True
    assert march["numbers_kept"] is False
    assert march["required_videos"] is None
    assert march["actual_videos"] is None


def test_whether_a_month_decided_her_pay_follows_the_arrangement_of_that_month(
    admin,
):
    """§15, and the reason it is computed per month rather than once.

    She was on a guaranteed minimum until August and on commission from
    September. August's targets decided money and September's do not, and a
    screen reading only her *current* arrangement would tell her the opposite
    about one of them.
    """
    affiliate = _affiliate(admin)
    # Written as one history, because `PUT /pay-history` replaces the whole of
    # it (ADR 0036) and two `_terms` calls would leave August with none.
    written = admin.put(
        f"/api/affiliates/{affiliate['id']}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "end_month": AUGUST,
                    "compensation_type": "base_guarantee",
                    "commission_rate_bp": 1000,
                    "base_amount_piastres": 800_000,
                },
                {
                    "start_month": SEPTEMBER,
                    "compensation_type": "commission",
                    "commission_rate_bp": 1000,
                },
            ],
            "outcomes": {},
        },
    )
    assert written.status_code == 200, written.text
    _order(affiliate["id"], "1", 100_000, month=AUGUST)

    rows = {
        row["month"]: row
        for row in _sign_in().get("/api/me/targets").json()["months"]
    }

    assert rows[AUGUST]["determines_pay"] is True
    assert rows[SEPTEMBER]["determines_pay"] is False


def test_her_targets_are_only_ever_hers(admin):
    """The self endpoints take no id, so there is nothing to tamper with - but
    the assertion is worth having in the file that would notice if one grew.
    """
    mine = _affiliate(admin)
    other = _affiliate(admin, "Sara", "sara@example.com", "SARA10")
    _terms(admin, mine["id"])
    _terms(admin, other["id"])
    _hit_targets(admin, other["id"], AUGUST, verified=True)

    rows = _sign_in().get("/api/me/targets").json()["months"]

    assert all(row["achieved"] is None for row in rows)


# -- Her best sellers (the approved Wardrobe's first section) ------------------


def test_her_own_record_names_the_arrangement_she_is_on(admin):
    """*Your arrangement*, on her account screen.

    The payload carries the raw type and her screen puts the words on it, the
    way the roster's *Terms* column does - one vocabulary, written once.

    **A model with no terms is `None`, not commission.** A gap is not an
    arrangement, and answering the gap with the commonest of the three would
    quote her a basis nobody has agreed with her.
    """
    affiliate = _affiliate(admin)

    before = _sign_in().get("/api/me")
    assert before.status_code == 200, before.text
    assert before.json()["arrangement"] is None
    # Present whether or not anybody recorded it; the screen says less without
    # it rather than guessing a date.
    assert "since" in before.json()

    _terms(admin, affiliate["id"])

    after = _sign_in().get("/api/me")
    assert after.json()["arrangement"] == "commission"


def _line(order_id, product_id, total, quantity=1):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_line_item (shopify_line_item_id, shopify_order_id, "
                "shopify_product_id, title, quantity, discounted_total_piastres, "
                "original_total_piastres) VALUES (:l, :o, :p, :t, :q, :d, :d)"
            ),
            {
                "l": f"{order_id}-{product_id}",
                "o": order_id,
                "p": product_id,
                "t": f"Product {product_id}",
                "q": quantity,
                "d": total,
            },
        )


def test_her_best_sellers_are_her_own_sales_and_nobody_elses(admin):
    """The programme's list with her name above it would tell her something
    untrue about her own work."""
    nour = _affiliate(admin)
    sara = _affiliate(admin, name="Sara", email="sara@example.com", code="SARA10")
    _order(nour["id"], "bs-1", 100_000)
    _order(sara["id"], "bs-2", 900_000, code="SARA10")
    _line("bs-1", "P1", 100_000)
    _line("bs-2", "P2", 900_000)

    body = _sign_in().get("/api/me/best-sellers").json()

    assert [row["shopify_product_id"] for row in body["products"]] == ["P1"]
    # *Sales through NOUR10*, as the export names HBA15 - her code, never Sara's.
    assert body["codes"] == ["NOUR10"]


def test_a_travelling_order_sells_and_a_failed_one_does_not(admin):
    """ADR 0040, and the same basis as the money beside it.

    This read delivered-only, which was the live rule when it was written and
    stopped being it: her best sellers are the sales she is paid on, so a
    list that left out a travelling order would disagree with her own month.
    A failed delivery still sells nothing, and always did.
    """
    nour = _affiliate(admin)
    _order(nour["id"], "bs-3", 100_000, state="pending")
    _line("bs-3", "P3", 100_000)
    _order(nour["id"], "bs-9", 400_000, state="void")
    _line("bs-9", "P9", 400_000)

    rows = _sign_in().get("/api/me/best-sellers").json()["products"]

    assert [row["shopify_product_id"] for row in rows] == ["P3"]
    assert rows[0]["sales_piastres"] == 100_000
    assert rows[0]["sales"] == "EGP 1,000.00"


def test_best_sellers_rank_by_what_the_customer_paid(admin):
    nour = _affiliate(admin)
    _order(nour["id"], "bs-4", 300_000)
    _line("bs-4", "SMALL", 50_000, quantity=5)
    _line("bs-4", "BIG", 250_000, quantity=1)

    rows = _sign_in().get("/api/me/best-sellers").json()["products"]

    assert [row["shopify_product_id"] for row in rows] == ["BIG", "SMALL"]
    assert rows[1]["quantity"] == 5


# ── A08: the Uses chart had no field to read ──────────────────────────────────


def _delivery(order_id: str, state: str | None) -> None:
    """What the courier did, which is not what the commission did."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE order_index SET delivery_state = :s "
                "WHERE shopify_order_id = :i"
            ),
            {"s": state, "i": order_id},
        )


def test_the_year_carries_the_code_uses_its_chart_asks_for(admin):
    """A08. Home said 37 uses; the Uses tab said the history was unavailable.

    `PortalYearChart` reads `row.uses` and `my_year` returned `orders` and
    nothing else, so the chart had a metric with no field behind it. Both
    figures are hers and they must be the same figure.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "delivered", 400_000, month=AUGUST)
    _order(affiliate["id"], "travelling", 600_000, month=AUGUST, state="pending")
    _delivery("delivered", "delivered")
    _delivery("travelling", None)

    portal = _sign_in()
    august = next(
        m for m in portal.get("/api/me/year").json()["months"] if m["month"] == AUGUST
    )
    card = portal.get(f"/api/me/earnings/{AUGUST}").json()

    assert august["uses"] == 2
    assert august["uses"] == card["orders"]["uses"], (
        "the chart and the card above it are the same fact"
    )


def test_a_use_is_a_delivery_outcome_not_a_commission_state(admin):
    """A08, D03. Pending and delivered count; a refused parcel does not.

    And it is **not** the order count renamed. An order that was delivered and
    then failed to earn anything is still a use, so the two figures diverge on
    purpose — which is why the repair had to be its own field rather than an
    alias.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "delivered", 400_000, month=AUGUST)
    _order(affiliate["id"], "travelling", 600_000, month=AUGUST, state="pending")
    _order(affiliate["id"], "refused", 500_000, month=AUGUST, state="void")
    _delivery("delivered", "delivered")
    _delivery("travelling", None)
    _delivery("refused", "failed")

    august = next(
        m
        for m in _sign_in().get("/api/me/year").json()["months"]
        if m["month"] == AUGUST
    )

    # Two uses: the parcel that arrived and the one still travelling.
    assert august["uses"] == 2
    # Two counted orders as well here - but not for the same reason, and the
    # next test is the one where they part company.
    assert august["orders"] == 2


def test_an_order_refunded_in_transit_is_a_use_and_not_a_sale(admin):
    """A08. The case that proves `uses` cannot be `orders` under a new name.

    **This test replaced one that had the business rule backwards.** The
    earlier version built an order marked `void` *and* delivered, called it
    "delivered and later refunded", and concluded such an order "pays
    nothing". Both halves were wrong. ADR 0025 is that **delivery is final**:
    once the parcel arrives the sale is hers and a later refund, return or
    exchange changes nothing - so that combination cannot arise from the
    normal path at all, and `test_a_refund_after_delivery_keeps_the_sale_and_
    the_commission` now drives the real sequence.

    The divergence is real; it just lives on the other side of delivery. Money
    back **before** the parcel arrives voids the commission, and the courier
    never reported a failure - so her code was still used, and no sale
    completed. A use is a delivery outcome; a counted order is a commission
    state. Here they differ, and neither is the other renamed.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "refunded-in-transit", 400_000, month=AUGUST, state="void")
    # Never delivered and never failed: Shopify said nothing about the courier.
    _delivery("refunded-in-transit", None)

    august = next(
        m
        for m in _sign_in().get("/api/me/year").json()["months"]
        if m["month"] == AUGUST
    )

    assert august["uses"] == 1, "her code was used; the courier reported nothing"
    assert august["orders"] == 0, "the money went back before it arrived"


def test_an_order_refunded_after_delivery_counts_for_both(admin):
    """A08 and ADR 0025 together, on the screens rather than in the service.

    The rule HBA actually runs: a delivered order keeps its counted sales and
    its commission through a refund. So this one is a use **and** a counted
    sale, and her sales figure does not drop when the refund lands.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "kept", 400_000, month=AUGUST, state="earned")
    _delivery("kept", "delivered")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE order_index SET financial_status = 'refunded' "
                "WHERE shopify_order_id = 'kept'"
            ),
        )

    august = next(
        m
        for m in _sign_in().get("/api/me/year").json()["months"]
        if m["month"] == AUGUST
    )

    assert august["uses"] == 1
    assert august["orders"] == 1
    assert august["sales_piastres"] == 400_000, "the sale is hers and stays hers"


def test_a_month_with_no_orders_reports_no_uses_rather_than_nothing(admin):
    """A08. Zero is an answer; absent is not.

    The chart draws `null` as *Not available*, which is right for something it
    cannot know and wrong for a quiet month. A month she has is a month it can
    count.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "july", 100_000, month="2026-07")

    months = _sign_in().get("/api/me/year").json()["months"]

    for row in months:
        assert row["uses"] is not None, f"{row['month']} could be counted"
    july = next(m for m in months if m["month"] == "2026-07")
    assert july["uses"] == 1
