"""Why Mazen's wardrobe was empty, and the four things that now prevent it.

Staging, 28 September. Six zero-priced parcels carried Mazen's phone on their
shipping address, and his Wardrobe tab showed nothing:

1. They were stored unmatched on 10 September, the only time matching ever ran,
   and Mazen was added on the 26th. Nothing re-checked stored parcels when a
   model joined (`rematch_for`).
2. Each was labelled *unknown* when stored, because the order prices had not
   been read yet, and the wardrobe read the label (`_is_gift`).
3. The sweep and the import never matched at all (`_match_recent`, the import's
   queued scan).
4. Nothing re-read an order stuck by a rule since corrected (`RESYNC_IN_FLIGHT`).
"""

import json

from sqlalchemy import text

from app.core.passwords import hash_password
from app.models.identity import UserAccount
from app.models.shipments import Classification, ModelShipment
from app.services.affiliates import (
    archive_affiliate,
    create_affiliate,
    update_shipping_address,
)
from app.services.jobs import JobKind
from app.services.recipients import (
    AMBIGUOUS,
    match_recipient,
    orders_missing_line_items,
    rematch_for,
)
from app.services.wardrobe import wardrobe_for

# The shape of a real Egyptian mobile; not anybody's.
MAZENS = "01100000441"


def _account(db, email):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=email.split("@")[0],
    )
    db.add(account)
    db.flush()
    return account


def _model(db, name="Mazen", email="mazen@example.com", phone=None):
    return create_affiliate(
        db, user_account_id=_account(db, email).id, name=name, phone=phone
    )


def _order(db, order_id, *, original=0, delivery="delivered", placed="2026-08-15"):
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency, delivery_state,"
            " fulfillment_status, original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, :p, '2026-08', ARRAY[]::text[], 0, 0, 0, 0, 'EGP',"
            " :d, 'fulfilled', :o, :o)"
        ),
        {
            "i": order_id,
            "n": f"#{order_id}",
            "p": f"{placed}T10:00:00+00:00",
            "d": delivery,
            "o": original,
        },
    )
    db.flush()


def _line(db, order_id, line_id, title, *, after_delivery=False, product="8890000000001"):
    db.execute(
        text(
            "INSERT INTO order_line_item (shopify_line_item_id, shopify_order_id,"
            " shopify_product_id, title, variant_title, quantity,"
            " discounted_total_piastres, original_total_piastres, after_delivery,"
            " selected_options, synced_at)"
            " VALUES (:l, :o, :p, :t, 'M', 1, 0, 0, :a, CAST('[]' AS jsonb), now())"
        ),
        {"l": line_id, "o": order_id, "p": product, "t": title, "a": after_delivery},
    )
    db.flush()


def _waiting_parcel(db, order_id, token=MAZENS):
    """Stored on 10 September: matched to nobody, labelled before prices were read."""
    db.add(
        ModelShipment(
            shopify_order_id=order_id,
            affiliate_id=None,
            recipient_token=token,
            match_reason="no_match",
            classification=Classification.UNKNOWN,
        )
    )
    db.flush()


def _parcel(db, order_id, affiliate, classification=Classification.UNKNOWN):
    db.add(
        ModelShipment(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            recipient_token=MAZENS,
            matched_at=db.scalar(text("SELECT now()")),
            classification=classification,
        )
    )
    db.flush()


def _queued(db, kind):
    return [
        json.loads(row[0]) if isinstance(row[0], str) else row[0]
        for row in db.execute(
            text("SELECT payload FROM background_job WHERE kind = :k"), {"k": kind}
        )
    ]


# ── A model joining later picks up her parcels (W05) ─────────────────────────


def test_adding_mazen_attaches_the_parcels_already_sent_to_his_phone(db):
    for order_id in ("16910", "28994"):
        _order(db, order_id)
        _waiting_parcel(db, order_id)

    mazen = _model(db, phone="+20 11 00000441")

    rows = db.query(ModelShipment).order_by(ModelShipment.shopify_order_id).all()
    assert [row.affiliate_id for row in rows] == [mazen.id, mazen.id]
    assert all(row.match_reason is None and row.matched_at for row in rows)
    # And what was inside each is read, for the wardrobe.
    queued = sorted(p["order_id"] for p in _queued(db, JobKind.SYNC_LINE_ITEMS))
    assert queued == ["16910", "28994"]


def test_entering_her_shipping_phone_later_attaches_them_too(db):
    _order(db, "28994")
    _waiting_parcel(db, "28994")
    mazen = _model(db)
    assert db.query(ModelShipment).one().affiliate_id is None

    update_shipping_address(
        db, mazen, {"shipping_phone": MAZENS}, actor_is_staff=True
    )

    assert db.query(ModelShipment).one().affiliate_id == mazen.id


def test_a_phone_two_models_share_attaches_to_neither(db):
    """The test models on staging all carry the owner's number. A parcel to it
    is recorded as ambiguous - never given to whichever was checked first."""
    one = _model(db, name="Test one", email="one@example.com", phone="01000000036")
    _model(db, name="Test two", email="two@example.com", phone="01000000036")
    _order(db, "30141")
    _waiting_parcel(db, "30141", token="01000000036")

    assert rematch_for(db, one) == 0
    row = db.query(ModelShipment).one()
    assert row.affiliate_id is None
    assert row.match_reason == AMBIGUOUS


def test_a_confirmed_match_is_never_moved(db):
    _order(db, "28994")
    first = _model(db, phone=MAZENS)
    _parcel(db, "28994", first)
    second = _model(db, name="Someone", email="s@example.com")
    second.phone = MAZENS

    assert rematch_for(db, second) == 0
    assert db.query(ModelShipment).one().affiliate_id == first.id


def test_an_archived_model_takes_no_new_parcels(db):
    """Otherwise her lingering number turns a parcel to its new owner into an
    ambiguity nobody can clear."""
    left = _model(db, name="Left", email="left@example.com", phone=MAZENS)
    archive_affiliate(db, left)
    now = _model(db, phone=MAZENS)

    assert match_recipient(db, MAZENS)["affiliate_id"] == now.id


# ── The wardrobe decides a gift from the order, when it reads ────────────────


def test_a_zero_priced_parcel_labelled_unknown_is_still_a_gift(db):
    """Mazen's six: labelled unknown on 10 September, zero-priced in fact."""
    _order(db, "28994", original=0)
    _line(db, "28994", "1", "HBA CLUB 09 CUTOFF JERSEY")
    mazen = _model(db, phone=MAZENS)
    _parcel(db, "28994", mazen, Classification.UNKNOWN)

    received = wardrobe_for(db, mazen.id)["received"]
    assert [row["title"] for row in received] == ["HBA CLUB 09 CUTOFF JERSEY"]


def test_a_paid_parcel_labelled_gift_is_still_not_in_it(db):
    """D05, read from the price rather than the label, in both directions."""
    _order(db, "29699", original=199680)
    _line(db, "29699", "1", "Bought with her own money")
    mazen = _model(db, phone=MAZENS)
    _parcel(db, "29699", mazen, Classification.GIFT)

    assert wardrobe_for(db, mazen.id)["received"] == []


def test_an_exchange_item_is_not_what_hba_sent(db):
    _order(db, "22369", original=0)
    _line(db, "22369", "1", "Brown OG HBA CLUB Pump Cover", product="8890000000001")
    _line(db, "22369", "2", "Swapped in later", after_delivery=True, product="8890000000002")
    mazen = _model(db, phone=MAZENS)
    _parcel(db, "22369", mazen)

    titles = [row["title"] for row in wardrobe_for(db, mazen.id)["received"]]
    assert titles == ["Brown OG HBA CLUB Pump Cover"]


# ── Her parcels' products are read, not only her sales' ──────────────────────


def test_a_matched_parcel_with_no_products_is_filled(db):
    _order(db, "28994")
    mazen = _model(db, phone=MAZENS)
    _parcel(db, "28994", mazen)
    _order(db, "30000")  # a customer's: nobody's parcel, nobody's sale

    assert orders_missing_line_items(db) == ["28994"]


def test_lines_read_before_exchanges_were_asked_about_are_read_again(db):
    _order(db, "28994")
    mazen = _model(db, phone=MAZENS)
    _parcel(db, "28994", mazen)
    _line(db, "28994", "1", "Jersey", after_delivery=None)

    assert orders_missing_line_items(db) == ["28994"]
    db.execute(text("UPDATE order_line_item SET after_delivery = false"))
    assert orders_missing_line_items(db) == []


# ── The sweep matches, and cannot be broken by matching ──────────────────────


def test_the_sweep_matches_its_window(db, monkeypatch):
    from app.services import reconcile

    calls = []
    monkeypatch.setattr(reconcile, "reconcile_recent", lambda db, client, since_hours: 0)
    monkeypatch.setattr(
        "app.services.recipients.scan_recipients",
        lambda db, client, **kw: calls.append(kw) or {"seen": 0, "matched": 0},
    )
    monkeypatch.setattr("app.services.shopify.sync.build_client", lambda: object())

    reconcile._handle_reconcile(db, {"since_hours": 48})

    assert calls and calls[0]["field"] == "updated_at"


def test_a_matching_failure_does_not_fail_the_sweep(db, monkeypatch):
    from app.services import reconcile

    def refused(db, client, **kw):
        raise RuntimeError("shippingAddress is protected customer data")

    monkeypatch.setattr(reconcile, "reconcile_recent", lambda db, client, since_hours: 0)
    monkeypatch.setattr("app.services.recipients.scan_recipients", refused)
    monkeypatch.setattr("app.services.shopify.sync.build_client", lambda: object())

    reconcile._handle_reconcile(db, {"since_hours": 48})  # does not raise


# ── Stuck orders are read again ───────────────────────────────────────────────


def test_every_undelivered_order_is_queued_for_a_fresh_read(db):
    from app.services.reconcile import _handle_resync_in_flight

    _order(db, "22369", delivery="in_flight")
    _order(db, "26091", delivery=None)
    _order(db, "29000", delivery="delivered")
    _order(db, "23619", delivery="failed")

    _handle_resync_in_flight(db, {})

    queued = sorted(p["order_id"] for p in _queued(db, JobKind.SYNC_ORDER))
    assert queued == ["22369", "26091"]


def test_the_resync_is_scheduled_and_handled():
    import app.main  # noqa: F401 - registers the handlers, as the app does
    from app.services.schedule import SCHEDULE
    from app.worker import HANDLERS

    assert JobKind.RESYNC_IN_FLIGHT in SCHEDULE
    assert JobKind.RESYNC_IN_FLIGHT in HANDLERS
