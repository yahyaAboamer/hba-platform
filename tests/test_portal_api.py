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

#: Where their money goes, so a payment can freeze a masked copy of it.
ADDRESS = 'https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp' 

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}
PASSWORD = "a-long-enough-password"
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
    response = admin.post(
        f"/api/affiliates/{affiliate_id}/compensation",
        json={
            "start_month": start,
            "compensation_type": "commission",
            "commission_rate_bp": rate_bp,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


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
                "total_piastres, shipping_piastres, tax_piastres, currency) "
                "VALUES (:i, :n, now(), :m, ARRAY[:c], :b, :b, 0, 0, 'EGP')"
            ),
            {
                "i": order_id,
                "n": number or f"#{order_id}",
                "m": month,
                "c": code,
                "b": base,
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
    response = admin.post(
        f"/api/payroll/{month}/approve",
        json={"affiliate_ids": [affiliate_id], "preview": False},
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
    # 106,237 x 10% = 10,623.7 piastres, rounded to E£106.00.
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

    Sara is on a guaranteed minimum of E£8,000. Their targets have not been
    recorded, so §9.5's comparison has no answer and they are paid their commission
    of E£1,100. Nothing about that figure is wrong - but the first version of
    this screen showed E£1,100 and never mentioned the guarantee at all, and
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
        "amount": "E£8,000.00",
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
    _approve(admin, affiliate["id"], AUGUST)

    _deliver("2")
    _approve(admin, affiliate["id"], SEPTEMBER)

    august = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    assert august["carried_out"] == [
        {
            "to_month": SEPTEMBER,
            "orders": 1,
            "base_piastres": 200_000,
            "base": "E£2,000.00",
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
    _terms(admin, affiliate["id"], rate_bp=1000, end_month=AUGUST)
    _order(affiliate["id"], "1", 100_000)
    _order(affiliate["id"], "2", 200_000, state="pending")
    _approve(admin, affiliate["id"], AUGUST)

    _terms(admin, affiliate["id"], rate_bp=2000, start=SEPTEMBER)
    _deliver("2")

    september = _sign_in().get(f"/api/me/earnings/{SEPTEMBER}").json()

    assert september["carried_in"] == [
        {
            "from_month": AUGUST,
            "orders": 1,
            "base_piastres": 200_000,
            "base": "E£2,000.00",
            "commission_rate_bp": 1000,
            "piastres": 20_000,
            "amount": "E£200.00",
        }
    ]
    carried = next(
        line for line in september["makeup"] if line["label"].startswith("Carried")
    )
    assert "10% - that month's rate" in carried["detail"]


# -- §9.4: an order that did not arrive ---------------------------------------


def test_every_order_state_is_shown_in_their_words(admin):
    """A void order stays visible. §9.4 pays on delivery, and an order that
    vanishes without a word looks like a mistake somebody made.
    """
    affiliate = _affiliate(admin)
    _terms(admin, affiliate["id"])
    _order(affiliate["id"], "1", 100_000, state="earned")
    _order(affiliate["id"], "2", 200_000, state="pending")
    _order(affiliate["id"], "3", 300_000, state="void")

    body = _sign_in().get(f"/api/me/earnings/{AUGUST}").json()

    states = {row["order_number"]: row["state_text"] for row in body["orders_detail"]}
    assert states == {"#1": "Counted", "#2": "On its way", "#3": "Did not arrive"}
    assert body["sales"]["pending_piastres"] == 200_000


# -- ADR 0014: a month from before the platform --------------------------------


def test_a_month_before_go_live_behaves_like_any_other_month(admin, monkeypatch):
    """An empty commission on a month full of sales reads as *HBA did not pay
    me for March*, which is the opposite of true.
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

    assert writable == ["/api/me/payout-destination"]


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
    assert body["orders"] == {"earned": 1, "pending": 1, "void": 1}
    assert body["sales"]["earned_piastres"] == 100_000
    assert body["sales"]["pending_piastres"] == 40_000
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
    """A zero on a chart is a claim that they earned nothing. They did not - the
    commission was agreed elsewhere (ADR 0014), and the sales are still real.
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
