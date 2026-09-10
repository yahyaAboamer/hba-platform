"""Which parcel went to which model.

W03, W04, W05. Every test here is about the difference between *unmatched*,
which this platform can show and act on, and *wrongly matched*, which nothing
downstream would ever question.
"""

import pytest
from sqlalchemy import select, text

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind, AffiliateProfile
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.models.shipments import Classification, ModelShipment
from app.services.affiliates import create_affiliate, create_house_account
from app.services.recipients import (
    AMBIGUOUS,
    NO_MATCH,
    NO_PHONE,
    UNUSABLE_PHONE,
    classify,
    match_recipient,
    normalise_phone,
    record_shipment,
    unmatched,
)

HERS = "01061234567"


def _model(db, name="Nour", email="nour@example.com", phone=HERS, shipping=None):
    account = UserAccount(
        email=email,
        password_hash=hash_password("quiet-harbour-lantern"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    affiliate = create_affiliate(
        db, user_account_id=account.id, name=name, phone=phone
    )
    if shipping is not None:
        affiliate.shipping_phone = shipping
    db.flush()
    return affiliate


def _order(db, order_id="2001", original_subtotal=0, month="2026-08"):
    db.execute(
        text(
            "INSERT INTO order_index (shopify_order_id, order_number, placed_at,"
            " business_month, discount_codes, subtotal_piastres, total_piastres,"
            " shipping_piastres, tax_piastres, currency,"
            " original_subtotal_piastres, original_total_piastres)"
            " VALUES (:i, :n, now(), :m, ARRAY[]::text[], 0, 0, 0, 0, 'EGP',"
            " :o, :o)"
        ),
        {"i": order_id, "n": f"#{order_id}", "m": month, "o": original_subtotal},
    )
    db.flush()
    return db.get(OrderIndex, order_id)


# ── Normalising a number ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "written",
    [
        "01061234567",
        "+20 106 123 4567",
        "0020-106-123-4567",
        "(010) 6123 4567",
        "  01061234567  ",
        "1061234567",
        "٠١٠٦١٢٣٤٥٦٧",
    ],
)
def test_the_same_number_written_seven_ways(written):
    """The first six are how people actually type it; the last is how it
    arrives from an Arabic keyboard."""
    assert normalise_phone(written) == HERS


@pytest.mark.parametrize(
    "unusable",
    [
        None,
        "",
        "   ",
        "0221234567",  # a Cairo landline
        "+44 7700 900123",  # not Egyptian
        "0106123456",  # one digit short
        "010612345678",  # one too many
        "not a phone",
    ],
)
def test_what_is_not_an_egyptian_mobile_becomes_nothing(unusable):
    """`None` rather than a best guess. Two unusable numbers normalising to
    the same wrong thing would match two different people to each other."""
    assert normalise_phone(unusable) is None


# ── Matching ───────────────────────────────────────────────────────────────


def test_a_parcel_reaches_the_model_whose_number_is_on_it(db):
    affiliate = _model(db)

    outcome = match_recipient(db, "+20 106 123 4567")

    assert outcome["affiliate_id"] == affiliate.id
    assert outcome["reason"] is None


def test_the_shipping_phone_wins_over_the_payout_phone(db):
    """They are different facts. One is where money goes, one is where a parcel
    goes, and a model who moved house has changed only the second."""
    affiliate = _model(db, phone="01111111111", shipping=HERS)

    assert match_recipient(db, HERS)["affiliate_id"] == affiliate.id


def test_an_unknown_number_is_unmatched_and_not_an_error(db):
    """Most of the shop's orders are customers. That is not a failure."""
    _model(db)

    outcome = match_recipient(db, "01099999999")

    assert outcome["affiliate_id"] is None
    assert outcome["reason"] == NO_MATCH


def test_two_models_on_one_number_is_refused_rather_than_guessed(db):
    """W03 asks for it to be reported. Picking one would put a parcel in the
    wrong woman's wardrobe and nothing downstream would question it."""
    _model(db, name="Nour", email="nour@example.com")
    _model(db, name="Layla", email="layla@example.com")

    outcome = match_recipient(db, HERS)

    assert outcome["affiliate_id"] is None
    assert outcome["reason"] == AMBIGUOUS
    assert len(outcome["candidates"]) == 2


def test_a_missing_number_and_an_unusable_one_are_different_states(db):
    """One means the order carried no phone; the other means it carried
    something that is not a mobile. Different problems, different fixes."""
    assert match_recipient(db, None)["reason"] == NO_PHONE
    assert match_recipient(db, "0221234567")["reason"] == UNUSABLE_PHONE


def test_a_house_account_is_never_a_recipient(db):
    """Nobody signs in as one and nothing is sent to one."""
    house = create_house_account(db, name="HBA house")
    house.phone = HERS
    db.flush()

    assert match_recipient(db, HERS)["reason"] == NO_MATCH


# ── Gift or purchase (W04) ─────────────────────────────────────────────────


def test_zero_original_net_is_a_gift(db):
    assert classify(0) == Classification.GIFT


def test_positive_original_net_is_a_purchase(db):
    assert classify(150_000) == Classification.PURCHASE


def test_unknown_stays_unknown_and_is_not_a_gift(db):
    """W04 in as many words. This decides whether something is hers, and a
    guess is a guess about somebody's property."""
    assert classify(None) == Classification.UNKNOWN


def test_a_cancelled_purchase_does_not_become_a_gift(db):
    """The failure W04 exists to prevent.

    Shopify zeroes an order's *current* totals on cancellation. Reading those
    would record a parcel she paid for as one HBA gave her — in her wardrobe,
    permanently.
    """
    affiliate = _model(db)
    order = _order(db, original_subtotal=150_000)
    # What a cancellation does to the live figures, and must not do to this.
    order.subtotal_piastres = 0
    order.total_piastres = 0
    db.flush()

    shipment = record_shipment(db, order, phone=HERS)

    assert shipment.affiliate_id == affiliate.id
    assert shipment.classification == Classification.PURCHASE


# ── Recording, twice ───────────────────────────────────────────────────────


def test_recording_the_same_order_twice_writes_one_row(db):
    """A webhook, a sweep and a backfill all reach this."""
    _model(db)
    order = _order(db)

    record_shipment(db, order, phone=HERS)
    record_shipment(db, order, phone=HERS)

    assert len(list(db.scalars(select(ModelShipment)))) == 1


def test_a_confirmed_match_survives_her_changing_her_number(db):
    """W03: preserve verified historical order links across phone changes.

    She moved and changed her phone. Nothing about that changes which parcel
    arrived at her door in March.
    """
    affiliate = _model(db)
    order = _order(db)
    record_shipment(db, order, phone=HERS)

    affiliate.shipping_phone = "01199999999"
    db.flush()
    again = record_shipment(db, order, phone=HERS)

    assert again.affiliate_id == affiliate.id


def test_an_unmatched_parcel_is_reconsidered_later(db):
    """W05: a model joining later can acquire links to earlier orders.

    The parcel arrived before anybody recorded her address. Once it is
    recorded, the next pass attaches it — which is the whole point of keeping
    the unmatched row rather than discarding it.
    """
    order = _order(db)
    first = record_shipment(db, order, phone=HERS)
    assert first.affiliate_id is None
    assert first.match_reason == NO_MATCH

    affiliate = _model(db)
    second = record_shipment(db, order, phone=HERS)

    assert second.affiliate_id == affiliate.id
    assert second.match_reason is None
    assert len(list(db.scalars(select(ModelShipment)))) == 1


def test_an_unmatched_row_records_why(db):
    order = _order(db)

    shipment = record_shipment(db, order, phone=None)

    assert shipment.affiliate_id is None
    assert shipment.match_reason == NO_PHONE
    assert shipment.matched_at is None


def test_the_staff_list_shows_only_what_is_worth_looking_at(db):
    """Most unmatched parcels are ordinary customer orders and always will be.

    Presenting every one as a backlog would invite somebody to clear a thousand
    rows that were never HBA's parcels — so a missing phone is recorded and not
    listed, while an ambiguity is both.
    """
    _model(db, name="Nour", email="nour@example.com")
    _model(db, name="Layla", email="layla@example.com")
    record_shipment(db, _order(db, "3001"), phone=None)
    record_shipment(db, _order(db, "3002"), phone=HERS)

    rows = unmatched(db)

    assert [row["reason"] for row in rows] == [AMBIGUOUS]


# ── The boundary ───────────────────────────────────────────────────────────


def test_the_recipient_token_is_nowhere_near_the_commission_index(db):
    """§10.2, structurally.

    `order_index` and `attributed_order` carry no personal data, and adding a
    recipient path must not be the thing that changes that. Reads columns
    rather than rows, so it fails when somebody adds a place to put a phone
    number rather than when somebody fills one in.
    """
    forbidden = {"recipient_token", "shipping_phone", "phone", "email", "customer_name"}

    for table in ("order_index", "attributed_order"):
        columns = {
            row[0]
            for row in db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_name = :t"
                ),
                {"t": table},
            )
        }
        assert not (columns & forbidden), (
            f"{table} gained a column for recipient data: "
            f"{sorted(columns & forbidden)}. The recipient path is "
            "`model_shipment` and nowhere else."
        )


# ── Her address (D11) ──────────────────────────────────────────────────────


def test_a_phone_that_cannot_normalise_is_refused_when_it_is_saved(db):
    """The last point where somebody can still fix it.

    It is the token W03 matches on. A number that cannot normalise is a parcel
    that can never be attached to her, and the failure would otherwise surface
    weeks later as an empty wardrobe.
    """
    from app.services.affiliates import update_shipping_address

    affiliate = _model(db)

    with pytest.raises(ValueError, match="Egyptian mobile"):
        update_shipping_address(
            db, affiliate, {"shipping_phone": "0221234567"}, actor_is_staff=True
        )


def test_only_the_fields_supplied_are_touched(db):
    """A form that edits one line must not blank the rest."""
    from app.services.affiliates import update_shipping_address

    affiliate = _model(db)
    update_shipping_address(
        db,
        affiliate,
        {"shipping_line1": "12 Road 9, Maadi", "shipping_city": "Cairo"},
        actor_is_staff=True,
    )
    db.flush()

    update_shipping_address(
        db, affiliate, {"shipping_city": "Giza"}, actor_is_staff=True
    )
    db.flush()

    assert affiliate.shipping_line1 == "12 Road 9, Maadi"
    assert affiliate.shipping_city == "Giza"


def test_an_empty_string_clears_a_line(db):
    """A second address line that no longer applies should be removable."""
    from app.services.affiliates import update_shipping_address

    affiliate = _model(db)
    update_shipping_address(
        db, affiliate, {"shipping_line2": "Flat 3"}, actor_is_staff=True
    )
    db.flush()

    update_shipping_address(
        db, affiliate, {"shipping_line2": ""}, actor_is_staff=True
    )
    db.flush()

    assert affiliate.shipping_line2 is None


def test_the_audit_says_which_side_changed_it_and_not_what_to(db):
    """"Who changed the address a parcel then went to" is a question that gets
    asked exactly once, urgently. The values live on the profile; the trail
    only has to say which fields moved and who moved them."""
    from app.services.affiliates import update_shipping_address

    affiliate = _model(db)
    update_shipping_address(
        db,
        affiliate,
        {"shipping_line1": "12 Road 9, Maadi"},
        actor_is_staff=True,
    )
    db.flush()

    rows = list(
        db.execute(
            text(
                "SELECT action, after_json::text FROM audit_event"
                " WHERE action = 'affiliate.shipping_address_updated'"
            )
        )
    )
    assert rows, "the change was not recorded at all"
    assert '"by": "staff"' in rows[0][1]
    assert "Maadi" not in rows[0][1]


# ── Reading what was in the parcel ─────────────────────────────────────────
#
# Until this existed, a matched parcel had nothing in it and every wardrobe was
# empty however much had been sent.


class _RecipientClient:
    """Answers the recipient query, and records what was asked."""

    def __init__(self, phone=None):
        self.phone = phone
        self.asked = []

    def require_scope(self, scope):
        pass

    def execute(self, document, variables=None):
        self.asked.append(variables)
        return {
            "order": {
                "id": (variables or {}).get("id"),
                "legacyResourceId": str((variables or {}).get("id", "")).split("/")[-1],
                "shippingAddress": {"phone": self.phone},
            }
        }


def _queued(db, kind):
    return [
        row[0]
        for row in db.execute(
            text("SELECT payload::text FROM background_job WHERE kind = :k"),
            {"k": kind},
        )
    ]


def test_a_matched_parcel_queues_a_read_of_what_was_in_it(db):
    """The piece that turns an empty wardrobe into a real one."""
    from app.services.jobs import JobKind
    from app.services.recipients import match_one_order

    _model(db)
    order = _order(db, "4001")

    match_one_order(db, _RecipientClient(phone=HERS), order)
    db.flush()

    assert _queued(db, JobKind.SYNC_LINE_ITEMS)


def test_an_unmatched_parcel_queues_nothing(db):
    """**Only matched ones.** Reading every line of every order in the shop to
    build twenty wardrobes is the wrong trade, and the great majority of the
    shop's orders are customers."""
    from app.services.jobs import JobKind
    from app.services.recipients import match_one_order

    _model(db)
    order = _order(db, "4002")

    match_one_order(db, _RecipientClient(phone="01099999999"), order)
    db.flush()

    assert _queued(db, JobKind.SYNC_LINE_ITEMS) == []


def test_matching_one_order_twice_queues_one_read(db):
    """A webhook, a sweep and a backfill all reach this."""
    from app.services.jobs import JobKind
    from app.services.recipients import match_one_order

    _model(db)
    order = _order(db, "4003")
    client = _RecipientClient(phone=HERS)

    match_one_order(db, client, order)
    db.flush()
    match_one_order(db, client, order)
    db.flush()

    assert len(_queued(db, JobKind.SYNC_LINE_ITEMS)) == 1


def test_a_live_order_is_matched_after_it_is_indexed(db, monkeypatch):
    """W05's live half.

    Queued **after** the index is written, and as its own job: matching needs a
    protected Shopify field, and a denial of that field must never be able to
    stop an order being indexed.
    """
    from app.services.jobs import JobKind
    from app.services.shopify import sync

    order = _order(db, "4004")
    monkeypatch.setattr(sync, "sync_one_order", lambda db_, order_id: order)

    sync._handle_sync_order(db, {"order_id": "4004"})
    db.flush()

    assert _queued(db, JobKind.MATCH_ORDER)


def test_an_order_shopify_no_longer_has_queues_no_match(db, monkeypatch):
    """`sync_one_order` returns None for an order deleted between the webhook
    firing and the job running. Not an error, and not something to match."""
    from app.services.jobs import JobKind
    from app.services.shopify import sync

    monkeypatch.setattr(sync, "sync_one_order", lambda db_, order_id: None)

    sync._handle_sync_order(db, {"order_id": "4005"})
    db.flush()

    assert _queued(db, JobKind.MATCH_ORDER) == []
