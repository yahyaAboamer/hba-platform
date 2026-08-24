"""Whose sale is this order?

Spec section 9.2, and the heart of Phase 3. Everything before this was storage;
this is the rule that turns an order into somebody's money in Phase 4.

    exactly one registered code  ->  attributed
    zero registered codes        ->  unattributed, indexed only
    two or more                  ->  HELD, a human decides

The third is a cheap safety net, not the conflict subsystem the old application
carried. The order waits rather than silently paying the wrong person or paying
twice.
"""

import pytest
from sqlalchemy import text

from app.core.passwords import hash_password
from app.models.affiliates import AccountKind
from app.models.identity import UserAccount
from app.models.orders import OrderIndex
from app.services.affiliates import create_affiliate
from app.services.attribution import AttributionOutcome, resolve, resolve_order
from app.services.codes import register_code


def _affiliate(db, name="Nour", kind=AccountKind.MODEL):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name, account_kind=kind)


def _order(db, order_id="1", codes=(), month="2026-04"):
    row = OrderIndex(
        shopify_order_id=order_id,
        order_number=f"#{order_id}",
        placed_at=f"{month}-15T12:00:00+00:00",
        business_month=month,
        discount_codes=list(codes),
        subtotal_piastres=100_000,
        total_piastres=110_000,
        shipping_piastres=10_000,
        tax_piastres=0,
        currency="EGP",
    )
    db.add(row)
    db.flush()
    return row


# ── The three outcomes ─────────────────────────────────────────────────────────


def test_one_registered_code_attributes_the_order(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    result = resolve(db, ["NOUR10"], "2026-04")
    assert result.outcome == AttributionOutcome.ATTRIBUTED
    assert result.affiliate_id == nour.id
    assert result.matched_codes == ["NOUR10"]


def test_no_registered_codes_leaves_the_order_unattributed(db):
    result = resolve(db, ["FREESHIP"], "2026-04")
    assert result.outcome == AttributionOutcome.UNATTRIBUTED
    assert result.affiliate_id is None
    assert result.matched_codes == []


def test_an_order_with_no_codes_at_all_is_unattributed(db):
    result = resolve(db, [], "2026-04")
    assert result.outcome == AttributionOutcome.UNATTRIBUTED
    assert result.affiliate_id is None


def test_two_registered_codes_put_the_order_on_hold(db):
    """Never guess. Paying the wrong affiliate is worse than paying late."""
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-01")
    register_code(db, sara, "SARA10", "2026-01")
    db.flush()

    result = resolve(db, ["NOUR10", "SARA10"], "2026-04")
    assert result.outcome == AttributionOutcome.HELD
    assert result.affiliate_id is None


def test_a_held_order_names_every_code_that_caused_the_hold(db):
    """A human has to decide, and cannot without knowing what conflicted."""
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-01")
    register_code(db, sara, "SARA10", "2026-01")
    db.flush()

    result = resolve(db, ["FREESHIP", "SARA10", "NOUR10"], "2026-04")
    assert sorted(result.matched_codes) == ["NOUR10", "SARA10"]


def test_three_registered_codes_also_hold(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    amira = _affiliate(db, "Amira")
    for affiliate, code in ((nour, "NOUR10"), (sara, "SARA10"), (amira, "AMIRA10")):
        register_code(db, affiliate, code, "2026-01")
    db.flush()

    result = resolve(db, ["NOUR10", "SARA10", "AMIRA10"], "2026-04")
    assert result.outcome == AttributionOutcome.HELD


# ── Non-model codes are ignored entirely ───────────────────────────────────────


def test_unregistered_codes_alongside_a_model_code_are_ignored(db):
    """FREESHIP + NOUR10 is one registered code, not two.

    §9.2 permits any number of additional non-model codes - free shipping,
    seasonal promos. Only registered codes count toward the one/zero/many test.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    result = resolve(db, ["FREESHIP", "NOUR10", "SUMMER25"], "2026-04")
    assert result.outcome == AttributionOutcome.ATTRIBUTED
    assert result.affiliate_id == nour.id
    assert result.matched_codes == ["NOUR10"]


def test_many_unregistered_codes_and_no_model_code_is_unattributed(db):
    result = resolve(db, ["FREESHIP", "SUMMER25", "WELCOME"], "2026-04")
    assert result.outcome == AttributionOutcome.UNATTRIBUTED


# ── The order's own month, never today's ───────────────────────────────────────


def test_attribution_uses_the_orders_month_not_todays(db):
    """An order placed in April is attributed by April's ownership.

    Using today's would make last April's payroll change every time a code
    moved - months already approved and paid would silently re-attribute.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-01", "2026-06")
    register_code(db, sara, "NOUR10", "2026-07")
    db.flush()

    assert resolve(db, ["NOUR10"], "2026-04").affiliate_id == nour.id
    assert resolve(db, ["NOUR10"], "2026-09").affiliate_id == sara.id


def test_a_code_registered_later_does_not_attribute_earlier_orders(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-06")
    db.flush()

    assert resolve(db, ["NOUR10"], "2026-04").outcome == (
        AttributionOutcome.UNATTRIBUTED
    )
    assert resolve(db, ["NOUR10"], "2026-06").outcome == AttributionOutcome.ATTRIBUTED


def test_a_closed_code_does_not_attribute_later_orders(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01", "2026-06")
    db.flush()

    assert resolve(db, ["NOUR10"], "2026-06").outcome == AttributionOutcome.ATTRIBUTED
    assert resolve(db, ["NOUR10"], "2026-07").outcome == (
        AttributionOutcome.UNATTRIBUTED
    )


def test_two_codes_that_never_overlap_in_time_do_not_hold(db):
    """Nour held NOUR10 until June, Sara holds SARA10 from July. An April order
    carrying both matches only one, because only one was registered in April.
    """
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-01", "2026-06")
    register_code(db, sara, "SARA10", "2026-07")
    db.flush()

    result = resolve(db, ["NOUR10", "SARA10"], "2026-04")
    assert result.outcome == AttributionOutcome.ATTRIBUTED
    assert result.affiliate_id == nour.id


# ── Case ───────────────────────────────────────────────────────────────────────


def test_case_differences_do_not_prevent_attribution(db):
    """Shopify is upper-cased on the way in, but a lowercase code arriving from
    anywhere else must still match rather than silently attributing nothing.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ["nour10"], "2026-04").affiliate_id == nour.id
    assert resolve(db, ["NoUr10"], "2026-04").affiliate_id == nour.id


def test_whitespace_does_not_prevent_attribution(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ["  NOUR10  "], "2026-04").affiliate_id == nour.id


def test_the_same_code_twice_on_one_order_is_one_code(db):
    """Shopify should not send a duplicate, but a duplicate must not read as
    two codes and put a perfectly ordinary order on hold.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    result = resolve(db, ["NOUR10", "nour10"], "2026-04")
    assert result.outcome == AttributionOutcome.ATTRIBUTED
    assert result.matched_codes == ["NOUR10"]


def test_an_empty_string_among_the_codes_is_ignored(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ["", "NOUR10", "   "], "2026-04").affiliate_id == nour.id


# ── House accounts ─────────────────────────────────────────────────────────────


def test_a_house_code_attributes_to_the_house_account(db):
    """It is a real code used by real customers. Phase 4 excludes it from
    payable totals; excluding it *here* would report the order as
    unattributed, which is a different and wrong answer.
    """
    house = _affiliate(db, "House", kind=AccountKind.HOUSE)
    register_code(db, house, "HBA10", "2026-01")
    db.flush()

    result = resolve(db, ["HBA10"], "2026-04")
    assert result.outcome == AttributionOutcome.ATTRIBUTED
    assert result.affiliate_id == house.id
    assert result.is_payable is False


def test_a_model_code_is_payable(db):
    """Guards the test above, which would pass if nothing were ever payable."""
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ["NOUR10"], "2026-04").is_payable is True


def test_a_house_code_and_a_model_code_together_still_hold(db):
    """The house account is not a lesser kind of owner. Two owners is two
    owners, and a human decides which.
    """
    house = _affiliate(db, "House", kind=AccountKind.HOUSE)
    nour = _affiliate(db, "Nour")
    register_code(db, house, "HBA10", "2026-01")
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ["HBA10", "NOUR10"], "2026-04").outcome == (
        AttributionOutcome.HELD
    )


def test_an_unattributed_result_has_no_payable_answer(db):
    result = resolve(db, ["FREESHIP"], "2026-04")
    assert result.is_payable is None


# ── Resolving from an order row ────────────────────────────────────────────────


def test_an_order_row_resolves_by_its_own_business_month(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    register_code(db, nour, "NOUR10", "2026-01", "2026-06")
    register_code(db, sara, "NOUR10", "2026-07")
    db.flush()

    april = _order(db, "1", ["NOUR10"], month="2026-04")
    september = _order(db, "2", ["NOUR10"], month="2026-09")

    assert resolve_order(db, april).affiliate_id == nour.id
    assert resolve_order(db, september).affiliate_id == sara.id


def test_an_order_with_no_codes_resolves_unattributed(db):
    order = _order(db, "1", [])
    assert resolve_order(db, order).outcome == AttributionOutcome.UNATTRIBUTED


# ── It decides; it does not record ─────────────────────────────────────────────


def test_resolution_writes_nothing(db):
    """Recording attribution is Phase 4's job, with the table that stores it
    and the rule that an order's affiliate is immutable once set.

    Building the decision separately means it can be tested exhaustively
    before any money depends on it.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()
    order = _order(db, "1", ["NOUR10"])

    def snapshot():
        return (
            db.query(OrderIndex).count(),
            db.execute(text("SELECT count(*) FROM audit_event")).scalar(),
            db.execute(text("SELECT count(*) FROM discount_code_period")).scalar(),
        )

    before = snapshot()
    resolve_order(db, order)
    assert snapshot() == before


def test_resolving_twice_gives_the_same_answer(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    first = resolve(db, ["NOUR10"], "2026-04")
    second = resolve(db, ["NOUR10"], "2026-04")
    assert first == second


# ── Input validation ───────────────────────────────────────────────────────────


def test_a_malformed_month_is_refused(db):
    with pytest.raises(ValueError, match="YYYY-MM"):
        resolve(db, ["NOUR10"], "April")


def test_codes_may_be_any_iterable(db):
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    db.flush()

    assert resolve(db, ("NOUR10",), "2026-04").affiliate_id == nour.id
    assert resolve(db, {"NOUR10"}, "2026-04").affiliate_id == nour.id


# ── Two codes, one owner ───────────────────────────────────────────────────────


def test_two_codes_belonging_to_the_same_affiliate_still_hold(db):
    """Deliberate, and worth naming rather than leaving implied.

    §9.2 says an order is attributed when it carries *exactly one* registered
    code. Two codes owned by the same person is unambiguous - there is no wrong
    person to pay - so attributing would be defensible.

    It holds anyway. An order carrying two model codes is not something the
    ordinary flow produces, and the cost of the two mistakes is not
    symmetrical: holding an order a human then waves through costs a minute,
    while attributing something we did not expect to see costs money and is
    discovered late, if at all.

    Cheap to change if it ever becomes a nuisance - one condition, and this
    test says so.
    """
    nour = _affiliate(db)
    register_code(db, nour, "NOUR10", "2026-01")
    register_code(db, nour, "NOUR20", "2026-01")
    db.flush()

    result = resolve(db, ["NOUR10", "NOUR20"], "2026-04")
    assert result.outcome == AttributionOutcome.HELD
    assert sorted(result.matched_codes) == ["NOUR10", "NOUR20"]
