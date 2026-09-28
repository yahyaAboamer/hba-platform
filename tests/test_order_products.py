"""What was in her orders, and the size of each thing (ADR 0050).

Staging, 27 September: 6,943 attributed orders and not one line item, because
only the webhook path ever asked Shopify for them - and HBA's catalogue names
its size option 32 different ways, so a variant title alone cannot say which
value is the size. This file holds both fixes.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.attributed_orders import AttributedOrder, CommissionState
from app.models.catalogue import OrderLineItem
from app.models.compensation import CompensationType
from app.models.identity import UserAccount
from app.models.integration import BackgroundJob
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.codes import register_code
from app.services.commission.attribute import attribute_order
from app.services.compensation import set_terms
from app.services.jobs import JobKind
from app.services.portal import describe_variant, my_orders
from app.services.recipients import _handle_fill_line_items, orders_missing_line_items

AUGUST = "2026-08"


def _model(db, name="Nour"):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, account_kind=AccountKind.MODEL
    )
    register_code(db, affiliate, f"{name.upper()}10", "2026-01")
    set_terms(
        db,
        affiliate,
        start_month="2026-01",
        compensation_type=CompensationType.COMMISSION,
        commission_rate_bp=1000,
    )
    db.flush()
    return affiliate


def _indexed(db, affiliate, order_id, *, day=4):
    order = OrderIndex(
        shopify_order_id=order_id,
        order_number=f"#{order_id}",
        placed_at=datetime(2026, 8, day, 12, tzinfo=timezone.utc),
        business_month=AUGUST,
        discount_codes=[f"{affiliate.name.upper()}10"],
        subtotal_piastres=100_000,
        total_piastres=100_000,
        shipping_piastres=0,
        tax_piastres=0,
        currency="EGP",
    )
    db.add(order)
    db.flush()
    return order


def _attributed(db, affiliate, order_id, *, day=4):
    _indexed(db, affiliate, order_id, day=day)
    db.add(
        AttributedOrder(
            shopify_order_id=order_id,
            affiliate_id=affiliate.id,
            business_month=AUGUST,
            commission_base_piastres=100_000,
            commission_state=CommissionState.PENDING,
        )
    )
    db.flush()


def _line(
    db,
    order_id,
    line_id,
    *,
    options,
    title="HBA Washed PANTS",
    variant="M",
    quantity=1,
    after_delivery=False,
):
    db.add(
        OrderLineItem(
            shopify_line_item_id=line_id,
            shopify_order_id=order_id,
            title=title,
            variant_title=variant,
            selected_options=options,
            # Read after ADR 0051 asked whether it was an exchange item; None
            # is a line read before the question existed.
            after_delivery=after_delivery,
            quantity=quantity,
            discounted_total_piastres=125_000,
            original_total_piastres=125_000,
        )
    )
    db.flush()


def _reads(db):
    return [
        job.payload["order_id"]
        for job in db.scalars(
            select(BackgroundJob).where(BackgroundJob.kind == JobKind.SYNC_LINE_ITEMS)
        )
    ]


# -- Every way in asks for the products ----------------------------------------


def test_an_order_becoming_hers_asks_shopify_what_was_in_it(db):
    """Here and not only in the webhook: the history import, the reconciliation
    sweep and a code's backfill all attribute through this one function."""
    nour = _model(db)
    order = _indexed(db, nour, "5001")

    assert attribute_order(db, order) is not None

    assert _reads(db) == ["5001"]


def test_attributing_the_same_order_again_does_not_read_it_twice(db):
    nour = _model(db)
    order = _indexed(db, nour, "5001")

    attribute_order(db, order)
    attribute_order(db, order)

    assert _reads(db) == ["5001"]


def test_an_order_belonging_to_nobody_is_not_read(db):
    """Indexed only - an ordinary customer's order. Reading its lines would
    spend the shop's rate limit on a screen nobody sees."""
    nour = _model(db)
    order = _indexed(db, nour, "5001")
    order.discount_codes = ["SUMMER20"]
    db.flush()

    attribute_order(db, order)

    assert _reads(db) == []


# -- The sweep fills what was never read ---------------------------------------


def test_the_sweep_finds_orders_never_read_and_leaves_read_ones_alone(db):
    nour = _model(db)
    _attributed(db, nour, "6001", day=1)  # no lines at all
    _attributed(db, nour, "6002", day=2)  # lines read before options were
    _line(db, "6002", "L2", options=None)
    _attributed(db, nour, "6003", day=3)  # read; the variant had been deleted
    _line(db, "6003", "L3", options=[])
    _attributed(db, nour, "6004", day=4)  # read, with its options
    _line(db, "6004", "L4", options=[{"name": "Size", "value": "M"}])
    _attributed(db, nour, "6005", day=5)  # read before exchanges were asked about
    _line(db, "6005", "L5", options=[{"name": "Size", "value": "M"}], after_delivery=None)

    # Newest first: the month she is looking at fills first.
    assert orders_missing_line_items(db) == ["6005", "6002", "6001"]


def test_the_sweep_queues_each_order_once_however_often_it_runs(db):
    nour = _model(db)
    _attributed(db, nour, "6001")

    _handle_fill_line_items(db, {})
    _handle_fill_line_items(db, {})

    assert _reads(db) == ["6001"]


def test_the_sweep_is_bounded(db):
    nour = _model(db)
    for day in range(1, 6):
        _attributed(db, nour, f"70{day}", day=day)

    _handle_fill_line_items(db, {"limit": 2})

    assert sorted(_reads(db)) == ["704", "705"]


# -- Which value is the size ---------------------------------------------------


def test_the_size_is_whichever_option_is_named_like_one():
    """Staging's real option names, 27 September."""
    for name in ("Size", "size", "Sizs", "T-shirt Size", "BLACK HBA CLUB PUMP COVER (Size)"):
        assert describe_variant([{"name": name, "value": "XL"}], "XL") == {
            "size": "XL",
            "options": [],
        }


def test_a_colour_follows_the_size_and_is_never_called_one():
    assert describe_variant(
        [{"name": "Pants size", "value": "M"}, {"name": "Color", "value": "Black"}],
        "M / Black",
    ) == {"size": "M", "options": ["Black"]}
    assert describe_variant([{"name": "Color", "value": "For him"}], "For him") == {
        "size": None,
        "options": ["For him"],
    }


def test_without_options_the_title_is_shown_and_nothing_is_called_a_size():
    """Never read with options, or the variant has been deleted: "Black" alone
    is a colour, and the title does not say which part is which."""
    assert describe_variant(None, "M / Black") == {"size": None, "options": ["M", "Black"]}
    assert describe_variant([], "XL") == {"size": None, "options": ["XL"]}
    assert describe_variant(None, "Default Title") == {"size": None, "options": []}
    assert describe_variant(None, None) == {"size": None, "options": []}


def test_her_orders_say_the_size_of_each_thing(db):
    nour = _model(db)
    _attributed(db, nour, "8001")
    _line(
        db, "8001", "L1",
        title="BLACK HBA CLUB PUMP COVER", variant="XL", quantity=2,
        options=[{"name": "BLACK HBA CLUB PUMP COVER (Size)", "value": "XL"}],
    )

    [line] = my_orders(db, nour, AUGUST)[0]["contents"]

    assert line["title"] == "BLACK HBA CLUB PUMP COVER"
    assert (line["size"], line["options"], line["quantity"]) == ("XL", [], 2)
