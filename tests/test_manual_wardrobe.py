"""A piece a model has with no order behind it (ADR 0061).

Models sometimes collect a piece from the warehouse. No Shopify order records
it, so her wardrobe and the product's coverage said she never had it. Staff
now assign it by hand on the product.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.passwords import hash_password
from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.models.shipments import ManualWardrobeItem, ModelShipment
from app.services.affiliates import create_affiliate, create_house_account
from app.services.wardrobe import (
    AssignmentRefused,
    assign_by_hand,
    coverage_for,
    holds_product,
    remove_by_hand,
    roster_for,
    wardrobe_for,
)

PANTS = "8890000000001"


def _model(db, name="Nour", email="nour@example.com"):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name, phone=None)


def _product(db, product_id=PANTS, title="HBA CLUB pants"):
    db.execute(
        text(
            "INSERT INTO product (shopify_product_id, title, status, synced_at)"
            " VALUES (:i, :t, 'active', now())"
        ),
        {"i": product_id, "t": title},
    )
    db.flush()


def _gift(db, affiliate, order_id, *, delivery, product=PANTS):
    """A zero-priced parcel matched to her, carrying one line of `product`."""
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency, delivery_state,"
            " original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, now(), '2026-08', ARRAY[]::text[], 0, 0, 0, 0, 'EGP',"
            " :d, 0, 0)"
        ),
        {"i": order_id, "n": f"#{order_id}", "d": delivery},
    )
    db.execute(
        text(
            "INSERT INTO order_line_item (shopify_line_item_id, shopify_order_id,"
            " shopify_product_id, title, variant_title, quantity,"
            " ordered_quantity, discounted_total_piastres, original_total_piastres,"
            " after_delivery, selected_options, synced_at)"
            " VALUES (:l, :o, :p, 'HBA CLUB pants', 'M', 1, 1, 0, 0, false,"
            " CAST('[]' AS jsonb), now())"
        ),
        {"l": f"L{order_id}", "o": order_id, "p": product},
    )
    db.add(
        ModelShipment(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            matched_at=db.scalar(text("SELECT now()")),
            classification="gift",
        )
    )
    db.flush()


def test_a_piece_assigned_by_hand_is_received_in_her_wardrobe(db):
    _product(db)
    nour = _model(db)

    assert assign_by_hand(db, PANTS, [nour.id], size="L") == [nour.id]

    received = wardrobe_for(db, nour.id)["received"]
    assert [(row["title"], row["size"], row["manual"]) for row in received] == [
        ("HBA CLUB pants", "L", True)
    ]
    assert received[0]["shopify_order_id"] is None
    assert holds_product(db, nour.id, PANTS)


def test_it_counts_in_the_products_coverage_and_roster(db):
    _product(db)
    nour = _model(db)
    sara = _model(db, name="Sara", email="sara@example.com")
    _gift(db, sara, "4001", delivery="delivered")

    assign_by_hand(db, PANTS, [nour.id, sara.id])

    # Sara has it both ways; she is still one model.
    assert coverage_for(db, [PANTS]) == {PANTS: 2}
    roster = roster_for(db, PANTS)
    by_name = {row["name"]: row for row in roster["received"]}
    assert set(by_name) == {"Nour", "Sara"}
    assert by_name["Nour"]["manual"] is True
    assert by_name["Nour"]["shopify_order_id"] is None
    # A parcel already says Sara received it, so the parcel is what is shown.
    assert by_name["Sara"]["order_number"] == "#4001"
    assert roster["not_sent"] == []


def test_a_hand_assignment_outranks_a_failed_parcel_which_stays_as_history(db):
    _product(db)
    nour = _model(db)
    _gift(db, nour, "4002", delivery="failed")

    assign_by_hand(db, PANTS, [nour.id])

    wardrobe = wardrobe_for(db, nour.id)
    assert wardrobe["failed"] == []
    assert wardrobe["received"][0]["history"][0]["state"] == "failed"
    assert [row["name"] for row in roster_for(db, PANTS)["received"]] == ["Nour"]


def test_assigning_twice_adds_nothing(db):
    _product(db)
    nour = _model(db)
    assign_by_hand(db, PANTS, [nour.id])

    assert assign_by_hand(db, PANTS, [nour.id]) == []
    assert db.scalar(select(func.count()).select_from(ManualWardrobeItem)) == 1


def test_a_house_account_or_nobody_is_refused(db):
    _product(db)
    house = create_house_account(db, name="compare to models")

    with pytest.raises(AssignmentRefused):
        assign_by_hand(db, PANTS, [house.id])
    with pytest.raises(AssignmentRefused):
        assign_by_hand(db, PANTS, [])


def test_removing_it_takes_it_out_and_leaves_parcels_alone(db):
    _product(db)
    nour = _model(db)
    sara = _model(db, name="Sara", email="sara@example.com")
    _gift(db, sara, "4003", delivery="delivered")
    assign_by_hand(db, PANTS, [nour.id, sara.id])

    assert remove_by_hand(db, PANTS, nour.id)
    assert remove_by_hand(db, PANTS, sara.id)
    assert not remove_by_hand(db, PANTS, nour.id)

    assert wardrobe_for(db, nour.id)["received"] == []
    assert len(wardrobe_for(db, sara.id)["received"]) == 1
    assert coverage_for(db, [PANTS]) == {PANTS: 1}


def test_both_are_audited_on_her(db):
    _product(db)
    nour = _model(db)

    assign_by_hand(db, PANTS, [nour.id], size="M")
    remove_by_hand(db, PANTS, nour.id)

    actions = [
        (event.action, event.subject)
        for event in db.scalars(
            select(AuditEvent)
            .where(AuditEvent.action.like("affiliate.wardrobe_%"))
            .order_by(AuditEvent.id)
        )
    ]
    assert actions == [
        ("affiliate.wardrobe_added", f"affiliate:{nour.id}"),
        ("affiliate.wardrobe_removed", f"affiliate:{nour.id}"),
    ]


# ── Over HTTP ──────────────────────────────────────────────────────────────


def test_the_product_routes_assign_and_take_back(fresh_database):
    from app.db import SessionLocal
    from app.main import app

    with TestClient(app) as client:
        path = f"/api/products/{PANTS}/manual-assignments"
        assert client.post(path, json={"affiliate_ids": [1]}).status_code in (401, 403)

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
            _product(db)
            nour = _model(db)
            db.commit()
            nour_id = nour.id

        added = client.post(path, json={"affiliate_ids": [nour_id], "size": "L"})
        assert added.status_code == 200, added.text
        assert [row["name"] for row in added.json()["roster"]["received"]] == ["Nour"]

        detail = client.get(f"/api/products/{PANTS}").json()
        assert detail["roster"]["received"][0]["manual"] is True
        assert client.get("/api/products").json()["products"][0]["models_with_it"] == 1

        missing = client.post("/api/products/404/manual-assignments", json={"affiliate_ids": [nour_id]})
        assert missing.status_code == 404
        assert client.post(path, json={"affiliate_ids": []}).status_code == 422

        taken = client.delete(f"{path}/{nour_id}")
        assert taken.status_code == 200
        assert taken.json()["roster"]["received"] == []
        assert client.delete(f"{path}/{nour_id}").status_code == 404
