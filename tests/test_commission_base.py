"""What is this order worth? §9.3 and ADR 0011.

Order `#29115` is the acceptance test, not an illustration. The customer paid
**E£1,157**, of which E£95 was shipping, so the base is **E£1,062**. Mid-exchange
Shopify reported three items totalling E£1,675 and the old dashboard calculated
on roughly E£1,557 — about **47% too much on a single order**.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.commission.base import (
    NEEDS_RETURN_DECISION,
    base_for_order,
    commission_base,
)

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

#: #29115, in piastres. E£1,157 paid, E£95 of it shipping, no tax.
PAID = 115_700
SHIPPING = 9_500
TAX = 0
EXPECTED_BASE = 106_200

#: What Shopify reports once E-stebdal has added the replacement without
#: removing the returned item: 3 items, E£1,675.
INFLATED_PAID = 167_500 + SHIPPING


# ── The worked example ─────────────────────────────────────────────────────────


def test_order_29115_is_worth_exactly_one_thousand_and_sixty_two_pounds():
    """1,157 − 95 = 1,062. The number this whole phase exists to get right."""
    assert commission_base(PAID, SHIPPING, TAX) == EXPECTED_BASE


def test_shipping_and_tax_belong_to_hba_not_the_model():
    assert commission_base(100_000, 9_500, 4_000) == 86_500


def test_the_discount_is_already_in_the_figure():
    """A E£1,000 jacket on a 10% code arrives inside a total of E£900. Nothing
    here needs the code's percentage, and using one would be a bug - it records
    what HBA expects, not what the customer paid.
    """
    assert commission_base(90_000, 0, 0) == 90_000


def test_a_base_can_never_go_negative():
    """A refund larger than the order would otherwise produce one, and a
    negative base subtracts from everything else she earned that month.
    """
    assert commission_base(5_000, 9_500, 0) == 0


def test_an_order_that_is_all_shipping_is_worth_nothing():
    assert commission_base(9_500, 9_500, 0) == 0


# ── The freeze ─────────────────────────────────────────────────────────────────


def test_the_base_follows_shopify_while_nothing_has_come_back():
    """A genuine edit before the parcel ships should be reflected."""
    decision = base_for_order(
        total_piastres=PAID, shipping_piastres=SHIPPING, tax_piastres=TAX
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.is_frozen is False
    assert decision.is_decided is True


def test_a_return_opening_freezes_the_base_at_what_it_was():
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=True,
        stored_base_piastres=EXPECTED_BASE,
        now=NOW,
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.frozen_at == NOW


def test_the_exchange_inflation_cannot_reach_a_frozen_base():
    """The defect this module exists to prevent. Shopify now says E£1,675 of
    goods; the frozen base still says E£1,062. Reading the live figure would
    calculate 47% too much.
    """
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=True,
        stored_base_piastres=EXPECTED_BASE,
        base_frozen_at=NOW - timedelta(days=2),
        now=NOW,
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.piastres != commission_base(INFLATED_PAID, SHIPPING, TAX)


def test_freezing_does_not_move_the_moment_it_happened():
    """When it froze answers "before or after the exchange opened?", which a
    later timestamp would destroy.
    """
    froze = NOW - timedelta(days=3)
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=True,
        stored_base_piastres=EXPECTED_BASE,
        base_frozen_at=froze,
        now=NOW,
    )

    assert decision.frozen_at == froze


def test_the_base_stays_frozen_after_the_return_finishes():
    """Unfreezing on completion would let the post-exchange subtotal back in.
    The order resolves; the number does not un-freeze.
    """
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=False,
        stored_base_piastres=EXPECTED_BASE,
        base_frozen_at=NOW - timedelta(days=5),
        now=NOW,
    )

    assert decision.piastres == EXPECTED_BASE
    assert decision.is_frozen is True


def test_an_order_first_seen_mid_exchange_freezes_at_what_it_shows():
    """No previous value to hold on to. The figure is whatever Shopify says at
    that moment, which for a historical import of an order already mid-exchange
    is the inflated one. Recorded in docs/limits.md - it cannot be recovered
    from data the platform never saw.
    """
    decision = base_for_order(
        total_piastres=INFLATED_PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=True,
        stored_base_piastres=None,
        now=NOW,
    )

    assert decision.piastres == commission_base(INFLATED_PAID, SHIPPING, TAX)
    assert decision.is_frozen is True


# ── Held rather than guessed ───────────────────────────────────────────────────


def test_a_resolved_return_is_held_because_it_might_be_an_exchange():
    """They resolve to opposite outcomes - an exchange finalises at the full
    base (ADR 0024), a plain return reduces it - and E-stebdal opens an
    identical Shopify return for both. Shopify refused `Order.returns`, so the
    platform says it cannot decide rather than picking one.
    """
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=False,
        stored_base_piastres=EXPECTED_BASE,
        base_frozen_at=NOW - timedelta(days=4),
        now=NOW,
    )

    assert decision.is_decided is False
    assert decision.needs_decision == NEEDS_RETURN_DECISION


def test_an_unresolved_return_is_not_held_because_it_pays_nothing_yet():
    """Still being decided means the order is `pending` (§9.4), so no figure
    pays anybody. Holding it as well would report a problem that does not
    exist.
    """
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=True,
        stored_base_piastres=EXPECTED_BASE,
        now=NOW,
    )

    assert decision.is_decided is True


def test_an_ordinary_order_is_never_held():
    """Returns are about one order in eight. The other seven must not acquire a
    blocker they have no reason for.
    """
    decision = base_for_order(
        total_piastres=PAID, shipping_piastres=SHIPPING, tax_piastres=TAX
    )

    assert decision.is_decided is True
    assert decision.needs_decision is None


@pytest.mark.parametrize(
    "unresolved,expected_hold", [(True, False), (False, True)]
)
def test_only_a_finished_return_needs_a_decision(unresolved, expected_hold):
    decision = base_for_order(
        total_piastres=PAID,
        shipping_piastres=SHIPPING,
        tax_piastres=TAX,
        return_activity=True,
        return_unresolved=unresolved,
        stored_base_piastres=EXPECTED_BASE,
        now=NOW,
    )

    assert (decision.needs_decision is not None) is expected_hold
