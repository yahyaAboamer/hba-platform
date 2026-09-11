"""What HBA has sent a model, and where each thing got to.

W06, W08, W10, D05.

The test that matters most is `test_resending_only_the_pants_leaves_the_tshirt_alone`.
W06 states that case in as many words, and it is the one a parcel-shaped design
gets wrong: the unit is a **product and a model**, not a parcel.
"""

import pytest
from sqlalchemy import text

from app.core.passwords import hash_password
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.shipments import Classification, ModelShipment
from app.services.affiliates import create_affiliate
from app.services.wardrobe import (
    FAILED,
    PROCESSING,
    RECEIVED,
    holds_product,
    roster_for,
    wardrobe_for,
)

TSHIRT = "8891111111111"
PANTS = "8892222222222"


def _model(db, name="Nour", email="nour@example.com"):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(db, user_account_id=account.id, name=name)
    db.flush()
    return affiliate


def _product(db, product_id, title):
    db.execute(
        text(
            "INSERT INTO product (shopify_product_id, title, status, image_url,"
            " synced_at) VALUES (:i, :t, 'active', :u, now())"
        ),
        {"i": product_id, "t": title, "u": f"https://cdn/{product_id}.jpg"},
    )
    db.flush()


def _parcel(
    db,
    affiliate,
    order_id,
    products,
    *,
    delivery="delivered",
    placed="2026-08-01",
    classification=Classification.GIFT,
    original=0,
):
    """One order, matched to her, containing the products named."""
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency, delivery_state,"
            " original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, :p, '2026-08', ARRAY[]::text[], 0, 0, 0, 0, 'EGP',"
            " :d, :o, :o)"
        ),
        {
            "i": order_id,
            "n": f"#{order_id}",
            "p": f"{placed}T10:00:00+00:00",
            "d": delivery,
            "o": original,
        },
    )
    for index, (product_id, title, size) in enumerate(products):
        db.execute(
            text(
                "INSERT INTO order_line_item (shopify_line_item_id,"
                " shopify_order_id, shopify_product_id, title, variant_title,"
                " quantity, discounted_total_piastres, original_total_piastres,"
                " synced_at) VALUES (:l, :o, :p, :t, :v, 1, 0, 0, now())"
            ),
            {
                "l": f"{order_id}-{index}",
                "o": order_id,
                "p": product_id,
                "t": title,
                "v": size,
            },
        )
    db.add(
        ModelShipment(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            recipient_token="01061234567",
            matched_at=db.scalar(text("SELECT now()")),
            classification=classification,
            original_net_piastres=original,
        )
    )
    db.flush()


# ── W06: the unit is a product and a model ─────────────────────────────────


def test_resending_only_the_pants_leaves_the_tshirt_alone(db):
    """W06, stated in the rule in as many words.

    A parcel with both fails. HBA resends the pants only, and it arrives. The
    T-shirt was never resent — it must stay failed, because a parcel-shaped
    design would mark the whole second shipment delivered and quietly say she
    has a T-shirt she does not have.
    """
    affiliate = _model(db)
    _product(db, TSHIRT, "White tee")
    _product(db, PANTS, "Wide-leg trousers")

    _parcel(
        db,
        affiliate,
        "5001",
        [(TSHIRT, "White tee", "M"), (PANTS, "Wide-leg trousers", "M")],
        delivery="failed",
        placed="2026-08-01",
    )
    _parcel(
        db,
        affiliate,
        "5002",
        [(PANTS, "Wide-leg trousers", "M")],
        delivery="delivered",
        placed="2026-08-14",
    )

    wardrobe = wardrobe_for(db, affiliate.id)

    assert [row["title"] for row in wardrobe["received"]] == ["Wide-leg trousers"]
    assert [row["title"] for row in wardrobe["failed"]] == ["White tee"]


def test_the_earlier_shipment_stays_readable_underneath(db):
    """W06: preserving earlier history. The failed attempt is still evidence
    that HBA tried, which is what a model asks about."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed", placed="2026-08-01")
    _parcel(db, affiliate, "5002", [(PANTS, "Wide-leg trousers", "M")],
            delivery="delivered", placed="2026-08-14")

    received = wardrobe_for(db, affiliate.id)["received"]

    assert received[0]["shopify_order_id"] == "5002"
    assert [row["shopify_order_id"] for row in received[0]["history"]] == ["5001"]


def test_the_latest_shipment_is_by_date_not_by_row_id(db):
    """A backfill inserts history out of order. Row id would make the oldest
    parcel look like the newest, and mark a delivered item failed."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    # Inserted newest first, so row id and calendar disagree.
    _parcel(db, affiliate, "6002", [(PANTS, "Wide-leg trousers", "M")],
            delivery="delivered", placed="2026-08-20")
    _parcel(db, affiliate, "6001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed", placed="2026-08-01")

    wardrobe = wardrobe_for(db, affiliate.id)

    assert [row["title"] for row in wardrobe["received"]] == ["Wide-leg trousers"]
    assert wardrobe["failed"] == []


# ── W08: what shows, and how ───────────────────────────────────────────────


def test_a_travelling_parcel_is_not_owned_yet(db):
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")],
            delivery=None)

    wardrobe = wardrobe_for(db, affiliate.id)

    assert wardrobe["received"] == []
    assert [row["title"] for row in wardrobe["processing"]] == ["Wide-leg trousers"]


def test_a_failed_product_is_shown_and_not_owned(db):
    """W08: it must not look owned, and it must not vanish. A model who was
    told something was sent has to be able to see what happened to it."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed")

    wardrobe = wardrobe_for(db, affiliate.id)

    assert wardrobe["received"] == []
    assert len(wardrobe["failed"]) == 1


def test_an_entry_carries_its_size_and_picture(db):
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "L")])

    row = wardrobe_for(db, affiliate.id)["received"][0]

    assert row["size"] == "L"
    assert row["image_url"] == f"https://cdn/{PANTS}.jpg"


def test_a_deleted_product_is_still_hers(db):
    """W01: keep historical wardrobe items accessible if no longer sold.

    The line item carries its own title and size, so the entry is complete
    without a catalogue row — it simply has no picture.
    """
    affiliate = _model(db)
    # No `_product` row at all: deleted from Shopify.
    _parcel(db, affiliate, "5001", [(PANTS, "Discontinued dress", "S")])

    row = wardrobe_for(db, affiliate.id)["received"][0]

    assert row["title"] == "Discontinued dress"
    assert row["size"] == "S"
    assert row["image_url"] is None


# ── D05: only what HBA sent ────────────────────────────────────────────────


def test_something_she_bought_is_not_in_her_wardrobe(db):
    """D05, 10 September 2026: *anything that she bought, then it's not shown
    in the wardrobe. We only return the products from the orders that have
    zero price.*"""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(
        db,
        affiliate,
        "5001",
        [(PANTS, "Wide-leg trousers", "M")],
        classification=Classification.PURCHASE,
        original=150_000,
    )

    wardrobe = wardrobe_for(db, affiliate.id)

    assert wardrobe["received"] == []
    assert wardrobe["processing"] == []
    assert wardrobe["failed"] == []


def test_an_unknown_price_is_not_treated_as_a_gift(db):
    """Unknown is not zero. Telling a model she owns something the platform
    cannot show HBA gave her is the error worth avoiding (W04)."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(
        db,
        affiliate,
        "5001",
        [(PANTS, "Wide-leg trousers", "M")],
        classification=Classification.UNKNOWN,
        original=None,
    )

    assert wardrobe_for(db, affiliate.id)["received"] == []


def test_one_models_parcel_is_not_in_anothers_wardrobe(db):
    nour = _model(db, name="Nour", email="nour@example.com")
    layla = _model(db, name="Layla", email="layla@example.com")
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, nour, "5001", [(PANTS, "Wide-leg trousers", "M")])

    assert len(wardrobe_for(db, nour.id)["received"]) == 1
    assert wardrobe_for(db, layla.id)["received"] == []


# ── W02: the product's roster ──────────────────────────────────────────────


def test_the_roster_groups_every_model_including_those_never_sent_it(db):
    """W02. The question the screen answers is *who could I ask*, so a model
    who never received it is part of the answer rather than absent from it."""
    got = _model(db, name="Aya", email="aya@example.com")
    travelling = _model(db, name="Basma", email="basma@example.com")
    failed = _model(db, name="Cala", email="cala@example.com")
    never = _model(db, name="Dina", email="dina@example.com")
    _product(db, PANTS, "Wide-leg trousers")

    _parcel(db, got, "7001", [(PANTS, "Wide-leg trousers", "M")], delivery="delivered")
    _parcel(db, travelling, "7002", [(PANTS, "Wide-leg trousers", "M")], delivery=None)
    _parcel(db, failed, "7003", [(PANTS, "Wide-leg trousers", "M")], delivery="failed")

    roster = roster_for(db, PANTS)

    assert [row["name"] for row in roster["received"]] == ["Aya"]
    assert [row["name"] for row in roster["processing"]] == ["Basma"]
    assert [row["name"] for row in roster["needs_checking"]] == ["Cala"]
    assert [row["name"] for row in roster["not_sent"]] == ["Dina"]
    assert never.id


def test_the_roster_is_alphabetical_inside_a_group(db):
    """W02: names alphabetical inside groups."""
    for name in ("Zeina", "Aya", "Mona"):
        _model(db, name=name, email=f"{name.lower()}@example.com")
    _product(db, PANTS, "Wide-leg trousers")

    roster = roster_for(db, PANTS)

    assert [row["name"] for row in roster["not_sent"]] == ["Aya", "Mona", "Zeina"]


# ── W10: who may be asked to feature it ────────────────────────────────────


def test_received_and_processing_both_count_as_holding_it(db):
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")], delivery=None)

    assert holds_product(db, affiliate.id, PANTS) is True


def test_a_failed_delivery_does_not_count(db):
    """A parcel that did not arrive is not something she can post about."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed")

    assert holds_product(db, affiliate.id, PANTS) is False


def test_a_replacement_makes_her_eligible_again(db):
    """W10: eligibility changes with current shipment state, so it reads the
    wardrobe rather than a stored flag — and nobody has to re-run anything."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "5001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed", placed="2026-08-01")
    assert holds_product(db, affiliate.id, PANTS) is False

    _parcel(db, affiliate, "5002", [(PANTS, "Wide-leg trousers", "M")],
            delivery=None, placed="2026-08-14")

    assert holds_product(db, affiliate.id, PANTS) is True


def test_something_she_bought_does_not_make_her_eligible(db):
    """D05 has one consequence here and it needs no second rule: no wardrobe
    entry, no eligibility."""
    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(
        db,
        affiliate,
        "5001",
        [(PANTS, "Wide-leg trousers", "M")],
        classification=Classification.PURCHASE,
        original=150_000,
    )

    assert holds_product(db, affiliate.id, PANTS) is False


# ── W09/W10: the feature request ───────────────────────────────────────────


def _request(db, product_id, message="Wear it with the trousers.", visible=True):
    from app.services.wardrobe import set_feature_request

    set_feature_request(db, product_id, message=message, visible=visible)
    db.flush()


def test_a_request_reaches_only_a_model_who_has_the_product(db):
    """W10: the audience is an intersection, evaluated on the server.

    Filtering in the browser would still hand every request to every model
    through the API, which is the difference between hiding something and not
    sending it.
    """
    from app.services.wardrobe import eligible_requests

    has = _model(db, name="Aya", email="aya@example.com")
    hasnt = _model(db, name="Dina", email="dina@example.com")
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, has, "8001", [(PANTS, "Wide-leg trousers", "M")])
    _request(db, PANTS)

    assert len(eligible_requests(db, has.id)) == 1
    assert eligible_requests(db, hasnt.id) == []


def test_a_hidden_request_reaches_nobody(db):
    from app.services.wardrobe import eligible_requests

    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(db, affiliate, "8001", [(PANTS, "Wide-leg trousers", "M")])
    _request(db, PANTS, visible=False)

    assert eligible_requests(db, affiliate.id) == []


def test_a_failed_only_model_drops_out_and_a_replacement_puts_her_back(db):
    """W10 states both halves: eligibility changes with current shipment state.

    Nothing is stored, so nobody has to re-run anything when a parcel moves.
    """
    from app.services.wardrobe import eligible_requests

    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _request(db, PANTS)
    _parcel(db, affiliate, "8001", [(PANTS, "Wide-leg trousers", "M")],
            delivery="failed", placed="2026-08-01")

    assert eligible_requests(db, affiliate.id) == []

    _parcel(db, affiliate, "8002", [(PANTS, "Wide-leg trousers", "M")],
            delivery=None, placed="2026-08-14")

    assert len(eligible_requests(db, affiliate.id)) == 1


def test_hiding_a_request_keeps_its_wording_and_removing_does_not(db):
    """W09 lists three verbs and two of them are not the same.

    A request being paused is not one that was withdrawn, and collapsing them
    would lose a paragraph somebody wrote.
    """
    from app.services.wardrobe import (
        feature_request_for,
        remove_feature_request,
        set_feature_request,
    )

    _product(db, PANTS, "Wide-leg trousers")
    _request(db, PANTS, message="Wear it to the shoot.")

    set_feature_request(db, PANTS, visible=False)
    db.flush()
    assert feature_request_for(db, PANTS)["message"] == "Wear it to the shoot."

    remove_feature_request(db, PANTS)
    db.flush()
    assert feature_request_for(db, PANTS) is None


def test_a_request_may_be_written_with_nothing_to_say(db):
    """**Reversed by D12, 12 September 2026.**

    This test used to assert the opposite - that a blank message was refused.
    The approved design shows a featured product as a card with the product's
    picture and treats the note as optional, and the owner confirmed it: a
    product can be featured on its picture alone.

    Kept rather than deleted, pointing the other way, so the change is visible
    to anybody who wonders whether the old rule was lost by accident.
    """
    from app.services.wardrobe import set_feature_request

    _product(db, PANTS, "Wide-leg trousers")

    request = set_feature_request(db, PANTS, message="   ", visible=True)

    assert request.message is None
    assert request.visible is True


def test_something_she_bought_does_not_make_a_request_visible_to_her(db):
    """D05's one consequence here, and it needs no second rule."""
    from app.services.wardrobe import eligible_requests

    affiliate = _model(db)
    _product(db, PANTS, "Wide-leg trousers")
    _parcel(
        db,
        affiliate,
        "8001",
        [(PANTS, "Wide-leg trousers", "M")],
        classification=Classification.PURCHASE,
        original=150_000,
    )
    _request(db, PANTS)

    assert eligible_requests(db, affiliate.id) == []


# ── Making the screens load ────────────────────────────────────────────────
#
# The wardrobe and the roster were built as loops: one query per parcel for its
# lines, then one per line for its product. That is invisible on a seeded
# database with three orders and is the reason the Products screen was slow on
# a real catalogue - which is the worst way for a performance bug to behave,
# because it only appears in front of somebody.


def test_a_shopify_image_is_asked_for_at_the_size_it_is_drawn(db):
    """A product photograph is commonly 2000px. Sixty of those is tens of
    megabytes to draw a page of thumbnails, and Shopify resizes on request."""
    from app.services.wardrobe import THUMBNAIL_WIDTH, thumbnail

    assert thumbnail("https://cdn.shopify.com/s/files/1/x.jpg") == (
        f"https://cdn.shopify.com/s/files/1/x.jpg?width={THUMBNAIL_WIDTH}"
    )


def test_an_image_that_already_has_a_width_is_left_alone(db):
    from app.services.wardrobe import thumbnail

    already = "https://cdn.shopify.com/s/files/1/x.jpg?width=800"
    assert thumbnail(already) == already


def test_a_url_with_a_query_keeps_it(db):
    from app.services.wardrobe import THUMBNAIL_WIDTH, thumbnail

    assert thumbnail("https://cdn.shopify.com/x.jpg?v=2") == (
        f"https://cdn.shopify.com/x.jpg?v=2&width={THUMBNAIL_WIDTH}"
    )


def test_a_foreign_host_is_never_rewritten(db):
    """Guessing at another host's resizing scheme produces a broken image
    rather than a smaller one."""
    from app.services.wardrobe import thumbnail

    other = "https://images.example.com/x.jpg"
    assert thumbnail(other) == other
    assert thumbnail(None) is None


def test_a_wardrobe_costs_the_same_number_of_queries_however_big_it_is(db):
    """The guard against the loop coming back.

    Counts statements rather than timing anything: a timing test on a laptop
    proves nothing, and the failure being guarded is a *shape*, not a speed.
    """
    from sqlalchemy import event

    affiliate = _model(db)
    for index in range(6):
        product_id = f"99{index}"
        _product(db, product_id, f"Thing {index}")
        _parcel(
            db,
            affiliate,
            f"9{index:03d}",
            [(product_id, f"Thing {index}", "M")],
            placed=f"2026-08-{index + 1:02d}",
        )

    seen: list[str] = []

    def count(conn, cursor, statement, *rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        wardrobe_for(db, affiliate.id)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)

    # One for the lines, one for the products. Six parcels must not cost
    # thirteen queries, and sixty must not cost a hundred and twenty-one.
    assert len(seen) <= 3, "\n".join(seen)


def test_a_roster_costs_the_same_number_of_queries_however_many_parcels(db):
    """The same guard on the other screen.

    `roster_for` asked "does this parcel contain this product" once per parcel.
    On a shop with a year of orders that is the query count that made the
    Products screen slow, and it is invisible on a seeded database.
    """
    from sqlalchemy import event

    _product(db, PANTS, "Wide-leg trousers")
    for index in range(6):
        model = _model(db, name=f"Model {index}", email=f"m{index}@example.com")
        _parcel(
            db,
            model,
            f"9{index:03d}",
            [(PANTS, "Wide-leg trousers", "M")],
            placed=f"2026-08-{index + 1:02d}",
        )

    seen: list[str] = []

    def count(conn, cursor, statement, *rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        roster_for(db, PANTS)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)

    # One for the matched lines, one for the models. Not one per parcel.
    assert len(seen) <= 3, "\n".join(seen)


# -- D12: a featured product needs no message --------------------------------


def test_a_product_can_be_featured_on_its_picture_alone(db):
    """**D12, 12 September 2026.**

    The approved design shows a featured product as a card with the product's
    picture; the note is what you add when there is something extra to say.
    Requiring one meant featuring ten products for a campaign was ten
    identical sentences nobody reads.
    """
    from app.services.wardrobe import set_feature_request

    request = set_feature_request(db, "gid://shopify/Product/1", visible=True)

    assert request.message is None
    assert request.visible is True


def test_a_note_can_be_taken_back(db):
    """Blank and absent collapse to nothing, on purpose.

    Refusing an empty string would mean a sentence typed once could never be
    removed - the same trap as the old refusal, from the other side.
    """
    from app.services.wardrobe import set_feature_request

    set_feature_request(db, "gid://shopify/Product/1", visible=True, message="Before Thursday")
    cleared = set_feature_request(db, "gid://shopify/Product/1", visible=True, message="   ")

    assert cleared.message is None


def test_a_note_is_kept_when_one_is_written(db):
    """Optional is not ignored."""
    from app.services.wardrobe import set_feature_request

    request = set_feature_request(
        db, "gid://shopify/Product/1", visible=True, message="  Mention the shade  "
    )

    assert request.message == "Mention the shade"
