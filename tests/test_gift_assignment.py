"""Gifts that reached nobody on the roster, and staff saying whose each was.

ADR 0060. Production, 15 October: 47 of HBA's free gifts had been shipped to
numbers no model had on her profile, so they were stored as customers and were
missing from the models' wardrobes with nothing on any screen saying so. And a
number written `+20 010…` was refused outright.
"""

import pytest
from sqlalchemy import select, text

from app.core.passwords import hash_password
from app.shared.models.audit import AuditEvent
from app.shared.models.identity import UserAccount
from app.shared.models.orders import OrderIndex
from app.modules.affiliates.models.shipments import ModelShipment
from app.modules.affiliates.services.affiliates import archive_affiliate, create_affiliate, create_house_account
from app.modules.affiliates.services.gifts import (
    ParcelRefused,
    assign_gift,
    dismiss_gift,
    unclaimed_gifts,
)
from app.shared.services.jobs import JobKind
from app.modules.affiliates.services.recipients import (
    ASSIGNED,
    NOT_A_MODEL,
    match_recipient,
    normalise_phone,
    record_shipment,
    rematch_for,
)

PROFILE = "01030000017"  # the number on her profile
PARCELS = "01030000882"  # the number HBA ships her gifts to
STRANGER = "01030000444"


def _model(db, name="Mahmoud", email="mahmoud@example.com", phone=PROFILE):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name, phone=phone)


def _order(db, order_id, *, original=0, codes=("sponsordis",), cancelled=False, placed="2026-08-15"):
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency, cancelled_at,"
            " original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, :p, '2026-08', :c, 0, 0, 0, 0, 'EGP',"
            " CASE WHEN :x THEN now() END, :o, :o)"
        ),
        {
            "i": order_id,
            "n": f"#{order_id}",
            "p": f"{placed}T10:00:00+00:00",
            "c": list(codes),
            "x": cancelled,
            "o": original,
        },
    )
    db.flush()


def _parcel(db, order_id, phone=PARCELS, **order):
    _order(db, order_id, **order)
    return record_shipment(db, db.get(OrderIndex, order_id), phone=phone)


def _listed(db):
    return [row["shopify_order_id"] for row in unclaimed_gifts(db)["gifts"]]


def _queued(db, kind):
    return list(
        db.execute(
            text("SELECT payload FROM background_job WHERE kind = :k"), {"k": kind}
        ).scalars()
    )


# ── +20 0… ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("written", ["+20 010 3000 0882", "+2001030000882", "0020 010 3000 0882"])
def test_the_country_code_and_the_zero_is_still_her_number(written):
    assert normalise_phone(written) == PARCELS


@pytest.mark.parametrize("unusable", ["+20 010 3000 088", "+20 010 3000 08821", "+20 022 1234 5678"])
def test_any_other_length_or_a_landline_is_still_refused(unusable):
    assert normalise_phone(unusable) is None


# ── The list ───────────────────────────────────────────────────────────────


def test_a_free_order_with_a_code_that_matched_nobody_is_listed(db):
    _model(db)
    _parcel(db, "3001")

    assert _listed(db) == ["3001"]


def test_an_exchange_a_purchase_a_cancelled_gift_and_a_match_are_not(db):
    """An exchange is free and carries no code; it is a customer swapping a size."""
    _model(db)
    _parcel(db, "3002", codes=())
    _parcel(db, "3003", original=50000)
    _parcel(db, "3004", cancelled=True)
    _parcel(db, "3005", phone=PROFILE)

    assert _listed(db) == []


def test_the_list_says_how_many_share_the_number_and_who_can_take_them(db):
    _model(db)
    gone = _model(db, name="Archived", email="gone@example.com", phone="01030000999")
    archive_affiliate(db, gone)
    create_house_account(db, name="compare to models")
    _parcel(db, "3006", placed="2026-08-01")
    _parcel(db, "3007", placed="2026-08-02")

    listing = unclaimed_gifts(db)

    assert [row["shopify_order_id"] for row in listing["gifts"]] == ["3007", "3006"]
    assert {row["same_number"] for row in listing["gifts"]} == {2}
    assert [model["name"] for model in listing["models"]] == ["Mahmoud"]
    assert listing["total"] == 2


def test_shopify_failing_costs_the_names_not_the_list(db):
    class Broken:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("Shopify is down")

    _model(db)
    _parcel(db, "3008")

    listing = unclaimed_gifts(db, Broken())

    assert listing["names_unavailable"] is True
    assert listing["gifts"][0]["phone"] == PARCELS


def test_the_names_come_from_shopify(db):
    class Shop:
        def execute(self, _document, variables):
            assert variables == {"ids": ["gid://shopify/Order/3009"]}
            return {
                "nodes": [
                    {
                        "legacyResourceId": "3009",
                        "shippingAddress": {"name": "Mahmoud M", "phone": "+20 010 3000 0882"},
                        "lineItems": {"nodes": [{"title": "HBA CLUB pants", "quantity": 1}]},
                    }
                ]
            }

    _model(db)
    _parcel(db, "3009")

    row = unclaimed_gifts(db, Shop())["gifts"][0]

    assert row["recipient_name"] == "Mahmoud M"
    assert row["items"] == ["1× HBA CLUB pants"]


# ── This is her ────────────────────────────────────────────────────────────


def test_assigning_gives_her_every_parcel_to_that_number(db):
    model = _model(db)
    _parcel(db, "3010")
    _parcel(db, "3011", codes=())  # same number, no code: still hers

    result = assign_gift(db, order_id="3010", affiliate_id=model.id, actor=None)

    assert result["orders"] == ["3010", "3011"]
    rows = list(db.scalars(select(ModelShipment).order_by(ModelShipment.shopify_order_id)))
    assert [(row.affiliate_id, row.match_reason) for row in rows] == [
        (model.id, ASSIGNED),
        (model.id, ASSIGNED),
    ]
    assert all(row.matched_at is not None for row in rows)
    assert _listed(db) == []


def test_assigning_queues_a_read_of_what_was_in_them(db):
    model = _model(db)
    _parcel(db, "3012")

    assign_gift(db, order_id="3012", affiliate_id=model.id, actor=None)

    assert {"order_id": "3012"} in _queued(db, JobKind.SYNC_LINE_ITEMS)


def test_the_next_parcel_to_that_number_is_hers_without_anybody(db):
    model = _model(db)
    _parcel(db, "3013")
    assign_gift(db, order_id="3013", affiliate_id=model.id, actor=None)

    later = _parcel(db, "3014")

    assert later.affiliate_id == model.id
    assert match_recipient(db, PARCELS)["affiliate_id"] == model.id


def test_a_number_on_another_models_profile_is_refused(db):
    """Stored before Sara's number arrived, as the real ones were."""
    model = _model(db)
    _parcel(db, "3015")
    sara = _model(db, name="Sara", email="sara@example.com", phone="01030000555")
    # Written directly, so that nothing re-matches the parcel on the way in:
    # this is the state a parcel stored before her number arrived is left in.
    db.execute(
        text("UPDATE affiliate_profile SET phone = :p WHERE id = :i"),
        {"p": PARCELS, "i": sara.id},
    )
    db.expire_all()

    with pytest.raises(ParcelRefused, match="Sara"):
        assign_gift(db, order_id="3015", affiliate_id=model.id, actor=None)


def test_a_number_two_models_were_given_attaches_to_neither(db):
    """A remembered number obeys the same rule as a profile phone."""
    first = _model(db)
    second = _model(db, name="Sara", email="sara@example.com", phone="01030000555")
    _parcel(db, "3016")
    assign_gift(db, order_id="3016", affiliate_id=first.id, actor=None)
    second.shipping_phone = PARCELS
    db.flush()

    outcome = match_recipient(db, PARCELS)

    assert outcome["affiliate_id"] is None
    assert outcome["candidates"] == sorted([first.id, second.id])


def test_an_archived_model_is_refused(db):
    model = _model(db)
    _parcel(db, "3017")
    archive_affiliate(db, model)

    with pytest.raises(ParcelRefused, match="archived"):
        assign_gift(db, order_id="3017", affiliate_id=model.id, actor=None)


def test_a_matched_parcel_cannot_be_moved(db):
    model = _model(db)
    _parcel(db, "3018", phone=PROFILE)

    with pytest.raises(ParcelRefused, match="already"):
        assign_gift(db, order_id="3018", affiliate_id=model.id, actor=None)


def test_assigning_is_audited_on_her(db):
    model = _model(db)
    _parcel(db, "3019")

    assign_gift(db, order_id="3019", affiliate_id=model.id, actor=None)

    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "parcel.assigned"))
    assert event.subject == f"affiliate:{model.id}"
    assert event.after_json == {"orders": ["3019"]}


# ── Not a model ────────────────────────────────────────────────────────────


def test_not_a_model_leaves_the_list_and_stays_unmatched(db):
    _model(db)
    _parcel(db, "3020")
    _parcel(db, "3021")

    dismiss_gift(db, order_id="3020", actor=None)

    assert _listed(db) == []
    rows = list(db.scalars(select(ModelShipment)))
    assert {(row.affiliate_id, row.match_reason) for row in rows} == {(None, NOT_A_MODEL)}


def test_a_rescan_keeps_the_answer(db):
    _model(db)
    _parcel(db, "3022")
    dismiss_gift(db, order_id="3022", actor=None)

    again = record_shipment(db, db.get(OrderIndex, "3022"), phone=PARCELS)

    assert again.match_reason == NOT_A_MODEL


def test_but_a_model_with_that_number_still_takes_it(db):
    model = _model(db)
    _parcel(db, "3023")
    dismiss_gift(db, order_id="3023", actor=None)

    model.shipping_phone = PARCELS
    db.flush()
    rematch_for(db, model)

    assert db.scalar(select(ModelShipment.affiliate_id)) == model.id


# ── Over HTTP ──────────────────────────────────────────────────────────────


def test_the_routes_need_a_signed_in_admin_and_work_for_one(fresh_database, monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app
    from app.shared.services.shopify import sync

    def no_shop():
        raise RuntimeError("not connected")

    monkeypatch.setattr(sync, "build_client", no_shop)

    with TestClient(app) as client:
        assert client.get("/api/operations/unclaimed-gifts").status_code == 401

        signed_in = client.post(
            "/api/auth/bootstrap",
            json={
                "email": "owner@example.com",
                "display_name": "Owner",
                "password": "quiet-harbour-lantern",
            },
        )
        client.headers["X-CSRF-Token"] = signed_in.json()["csrf"]

        with SessionLocal() as db:
            model = _model(db)
            _parcel(db, "3030")
            _parcel(db, "3031", phone=STRANGER)
            db.commit()
            model_id = model.id

        listing = client.get("/api/operations/unclaimed-gifts").json()
        assert sorted(row["shopify_order_id"] for row in listing["gifts"]) == ["3030", "3031"]

        path = "/api/operations/unclaimed-gifts"
        assigned = client.post(f"{path}/3030/assign", json={"affiliate_id": model_id})
        assert assigned.status_code == 200, assigned.text
        assert client.post(f"{path}/3030/assign", json={"affiliate_id": model_id}).status_code == 409
        assert client.post(f"{path}/3031/dismiss").status_code == 200
        assert client.post(f"{path}/9999/dismiss").status_code == 404

        assert client.get(path).json()["gifts"] == []
