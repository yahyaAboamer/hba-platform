"""Asking Shopify what it will tell us about delivery, returns and refunds.

Phase 4 Task 2. Three ADRs depend on fields this platform has never requested -
0011 freezes the base when a return begins, 0012 pays on delivery, 0023 says
that comes from Shopify rather than Bosta - and GraphQL rejects a whole document
when one field is wrong. Adding a mistaken field to the query that indexes every
order would stop order ingestion outright.

So this asks first, on its own query, and reports what Shopify accepted.
"""

import json

import httpx
import pytest

from app.services.shopify.client import ShopifyClient
from app.services.shopify.facts import (
    DELIVERED_STATUSES,
    MAX_SAMPLE,
    NOT_DELIVERIES,
    PROBES,
    SUMMARISERS,
    delivery_verdict,
    probe_order_facts,
    run_probe,
)

FIELD_ERROR = {
    "errors": [
        {
            "message": "Field 'deliveredAt' doesn't exist on type 'Fulfillment'",
            "extensions": {"code": "undefinedField"},
        }
    ]
}


def _client(handler):
    return ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        api_version="2026-07",
        transport=httpx.MockTransport(handler),
    )


def _shop(accepts, nodes_for):
    """A fake shop that rejects any field expression not in ``accepts``."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        document = json.loads(request.read().decode())["query"]
        seen.append(document)
        for expression in accepts:
            if expression in document:
                return httpx.Response(
                    200, json={"data": {"orders": {"nodes": nodes_for(expression)}}}
                )
        return httpx.Response(200, json=FIELD_ERROR)

    return _client(handler), seen


def _delivered_node(order_id="1", *, status="DELIVERED", delivered_at="2026-04-20T10:00:00Z"):
    return {
        "legacyResourceId": order_id,
        "fulfillments": [
            {
                "displayStatus": status,
                "status": "SUCCESS",
                "deliveredAt": delivered_at,
                "inTransitAt": "2026-04-18T09:00:00Z",
                "updatedAt": "2026-04-20T10:00:00Z",
            }
        ],
    }


def _delivery_probe():
    return next(probe for probe in PROBES if probe.name == "delivery")


# ── Trying several shapes ──────────────────────────────────────────────────────


def test_the_first_shape_that_compiles_wins(db):
    """Shopify moves fields between list and connection form across API
    versions. Trying each and reporting the winner turns a round-trip of
    guessing into one answer.
    """
    probe = _delivery_probe()
    second = probe.candidates[1]
    client, seen = _shop([second], lambda _: [_delivered_node(status="IN_TRANSIT")])

    result = run_probe(client, probe, sample_size=5)

    assert result.available is True
    assert result.field_expression == second
    assert len(seen) == 2, "it should have stopped at the first shape that worked"


def test_every_rejection_is_kept_not_just_the_last(db):
    """Four messages together say why far better than one. The rejection text
    is what names the missing field or the missing scope.
    """
    probe = _delivery_probe()
    client, _ = _shop([], lambda _: [])

    result = run_probe(client, probe, sample_size=5)

    assert result.available is False
    assert len(result.rejected) == len(probe.candidates)
    assert "deliveredAt" in result.rejected[0]["shopify_said"]
    assert result.error


def test_the_delivery_sample_is_narrowed_to_orders_that_shipped(db):
    """Asking whether delivery is ever reported over orders placed yesterday
    would show no deliveries and prove nothing.
    """
    probe = _delivery_probe()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.read().decode()))
        return httpx.Response(200, json={"data": {"orders": {"nodes": []}}})

    run_probe(_client(handler), probe, sample_size=5)

    assert captured["variables"]["query"] == "fulfillment_status:fulfilled"


# ── The verdict, which is what the maintainer came for ─────────────────────────


def test_delivery_reported_says_the_phase_can_proceed(db):
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop([first], lambda _: [_delivered_node("1"), _delivered_node("2")])

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "present"


def test_no_shipped_order_ever_delivered_says_stop(db):
    """The failure this endpoint exists to catch. Every order would stay
    pending for ever, every month would calculate to zero, and it would look
    exactly like a month with no sales.
    """
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop(
        [first],
        lambda _: [
            _delivered_node("1", status="IN_TRANSIT", delivered_at=None),
            _delivered_node("2", status="OUT_FOR_DELIVERY", delivered_at=None),
        ],
    )

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "absent"
    assert "no affiliate would ever be paid" in verdict["explanation"]
    assert "business decision" in verdict["explanation"]


def test_a_failed_delivery_is_not_a_delivery(db):
    """NOT_DELIVERED contains the word. Reading it as a delivery would pay
    commission on precisely the parcels the customer refused - the loss
    ADR 0012 was written to prevent.
    """
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop(
        [first], lambda _: [_delivered_node("1", status="NOT_DELIVERED", delivered_at=None)]
    )

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "absent"


def test_an_empty_sample_is_not_evidence_of_anything(db):
    """No fulfilled orders means nothing to judge from. Reporting that as
    'absent' would raise a false alarm on a shop that simply has not shipped
    yet.
    """
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop([first], lambda _: [])

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "unreadable"
    assert "not evidence" in verdict["explanation"]


def test_shopify_refusing_the_fields_concludes_nothing(db):
    probe = _delivery_probe()
    client, _ = _shop([], lambda _: [])

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "unreadable"


# ── Counting what came back ────────────────────────────────────────────────────


def test_delivery_statuses_are_counted_by_name(db):
    summary = SUMMARISERS["delivery"](
        [
            _delivered_node("1"),
            _delivered_node("2"),
            _delivered_node("3", status="IN_TRANSIT", delivered_at=None),
        ]
    )

    assert summary["fulfilment_display_statuses"]["DELIVERED"] == 2
    assert summary["fulfilment_display_statuses"]["IN_TRANSIT"] == 1
    assert summary["orders_with_a_fulfilment"] == 3
    assert summary["fulfilments_carrying_a_delivered_timestamp"] == 2


def test_an_order_with_no_fulfilment_is_counted_as_such(db):
    summary = SUMMARISERS["delivery"]([{"legacyResourceId": "1", "fulfillments": []}])

    assert summary["orders_with_a_fulfilment"] == 0
    assert summary["fulfilment_display_statuses"] == {}


def test_return_statuses_are_counted(db):
    summary = SUMMARISERS["return_status"](
        [
            {"returnStatus": "NO_RETURN"},
            {"returnStatus": "IN_PROGRESS"},
            {"returnStatus": None},
        ]
    )

    assert summary["return_statuses"]["NO_RETURN"] == 1
    assert summary["return_statuses"]["IN_PROGRESS"] == 1
    assert summary["return_statuses"]["(null)"] == 1


def test_refunds_are_read_from_either_shape(db):
    """A plain list and a connection both have to work, because which one
    Shopify uses is exactly what the probe is trying to establish.
    """
    as_list = SUMMARISERS["refund_total"](
        [{"refunds": [{"totalRefundedSet": {"shopMoney": {"amount": "550.00"}}}]}]
    )
    as_connection = SUMMARISERS["refund_total"](
        [
            {
                "refunds": {
                    "nodes": [{"totalRefundedSet": {"shopMoney": {"amount": "550.00"}}}]
                }
            }
        ]
    )

    assert as_list == as_connection
    assert as_list["total_refunded_piastres_in_sample"] == 55_000
    assert as_list["orders_with_at_least_one_refund"] == 1


def test_refunded_merchandise_is_counted_separately_from_the_total(db):
    """§9.3 reduces the base by refunded **merchandise**, not by refunded
    shipping or tax. Conflating them would over-reduce and underpay.
    """
    summary = SUMMARISERS["refund_merchandise"](
        [
            {
                "refunds": [
                    {
                        "refundLineItems": {
                            "nodes": [
                                {"subtotalSet": {"shopMoney": {"amount": "600.00"}}}
                            ]
                        }
                    }
                ]
            }
        ]
    )

    assert summary["refunded_merchandise_piastres_in_sample"] == 60_000
    assert summary["orders_with_refunded_line_items"] == 1


# ── The whole report ───────────────────────────────────────────────────────────


def test_the_report_answers_every_open_question(db):
    """One call, four facts, and a verdict. Each has a plain-language question
    so the answer can be checked by somebody who did not write it.
    """
    client, _ = _shop(
        [probe.candidates[0] for probe in PROBES],
        lambda expression: [_delivered_node("1")] if "fulfillments" in expression else [],
    )

    report = probe_order_facts(client, sample_size=5)

    assert {fact["name"] for fact in report["facts"]} == {
        probe.name for probe in PROBES
    }
    assert all(fact["question"] for fact in report["facts"])
    assert report["delivery"]["signal"] == "present"


def test_one_unreadable_fact_does_not_blind_the_others(db):
    """Each fact is probed on its own query, so a missing return scope still
    leaves the delivery answer readable.
    """
    delivery = _delivery_probe().candidates[0]
    client, _ = _shop([delivery], lambda _: [_delivered_node("1")])

    report = probe_order_facts(client, sample_size=5)
    facts = {fact["name"]: fact for fact in report["facts"]}

    assert facts["delivery"]["available"] is True
    assert facts["return_status"]["available"] is False
    assert facts["return_status"]["rejected"], "the reason should be reported"
    assert report["delivery"]["signal"] == "present"


@pytest.mark.parametrize("requested,expected", [(0, 1), (-5, 1), (10_000, MAX_SAMPLE)])
def test_the_sample_size_is_clamped(db, requested, expected):
    """A caller asking for ten thousand orders with nested fulfilments and
    refunds on every node would be throttled rather than answered.
    """
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode()))
        return httpx.Response(200, json={"data": {"orders": {"nodes": []}}})

    report = probe_order_facts(_client(handler), sample_size=requested)

    assert report["sample_size"] == expected
    assert captured[0]["variables"]["first"] == expected


def test_every_probe_has_a_summariser(db):
    """A probe with no summariser raises KeyError the first time it succeeds -
    against the live shop, in front of the maintainer.
    """
    assert {probe.name for probe in PROBES} == set(SUMMARISERS)


@pytest.mark.parametrize("status", sorted(NOT_DELIVERIES))
def test_a_status_that_merely_contains_the_word_is_not_a_delivery(db, status):
    """A parcel on the van, a failed attempt, and an outright refusal all
    contain "deliver". The obvious substring test reads every one of them as
    money earned - which is how commission gets paid on goods the customer
    never received. Caught here rather than in production.
    """
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop(
        [first], lambda _: [_delivered_node("1", status=status, delivered_at=None)]
    )

    verdict = delivery_verdict([run_probe(client, probe, sample_size=5)])

    assert verdict["signal"] == "absent", f"{status} was read as a delivery"


def test_delivered_and_not_delivered_do_not_overlap(db):
    """If a status ever appeared in both sets, which one won would depend on
    the order the code happened to check them in.
    """
    assert not (DELIVERED_STATUSES & NOT_DELIVERIES)


def test_collected_in_person_counts_as_delivered(db):
    """PICKED_UP means the customer has the goods. Withholding her commission
    because the courier called it something else would be wrong.
    """
    probe = _delivery_probe()
    first = probe.candidates[0]
    client, _ = _shop(
        [first], lambda _: [_delivered_node("1", status="PICKED_UP", delivered_at=None)]
    )

    assert delivery_verdict([run_probe(client, probe, sample_size=5)])["signal"] == "present"


# ── Telling an exchange from a return ──────────────────────────────────────────
#
# The one question order-facts could not already answer. E-stebdal opens an
# identical Shopify return for both, and they are paid differently: an exchange
# leaves the model's commission untouched, a return reduces it by the goods that
# came back. Everything below asks whether Shopify knows the difference.


def _return(status="OPEN", exchange_items=0, return_items=1):
    return {
        "id": "gid://shopify/Return/1",
        "status": status,
        "totalQuantity": return_items,
        "exchangeLineItems": {"nodes": [{"id": str(n)} for n in range(exchange_items)]},
        "returnLineItems": {"nodes": [{"id": str(n)} for n in range(return_items)]},
    }


def _exchange_probe():
    return next(probe for probe in PROBES if probe.name == "exchange_vs_return")


def test_a_replacement_going_out_marks_an_exchange(db):
    """The discriminator, if Shopify supplies it: an exchange sends something
    back to the customer, a plain return does not.
    """
    summary = SUMMARISERS["exchange_vs_return"](
        [
            {"returns": {"nodes": [_return(exchange_items=1)]}},
            {"returns": {"nodes": [_return(exchange_items=0)]}},
        ]
    )

    assert summary["shopify_reports_exchange_line_items"] is True
    assert summary["returns_that_sent_a_replacement"] == 1
    assert summary["returns_that_sent_nothing_back"] == 1


def test_a_shopify_without_exchange_line_items_says_so(db):
    """If the field is missing the answer is "Shopify cannot tell us", which is
    a different answer from "no exchanges happened" and must not be reported as
    one - a human would have to decide every return instead.
    """
    summary = SUMMARISERS["exchange_vs_return"](
        [{"returns": {"nodes": [{"id": "1", "status": "OPEN"}]}}]
    )

    assert summary["shopify_reports_exchange_line_items"] is False
    assert summary["returns_that_sent_a_replacement"] == 0
    assert summary["orders_with_a_return"] == 1


def test_returns_are_read_from_either_shape(db):
    as_connection = SUMMARISERS["exchange_vs_return"](
        [{"returns": {"nodes": [_return(exchange_items=2)]}}]
    )
    as_list = SUMMARISERS["exchange_vs_return"]([{"returns": [_return(exchange_items=2)]}])
    assert as_connection == as_list


def test_an_order_with_no_returns_counts_as_none(db):
    summary = SUMMARISERS["exchange_vs_return"]([{"returns": {"nodes": []}}, {}])
    assert summary["orders_with_a_return"] == 0


def test_the_probe_falls_back_when_returns_are_unreadable(db):
    """`Order.returns` may sit behind read_returns rather than read_orders. The
    narrowest shape still answers "do returns exist at all", which is worth
    having even when the exchange field is refused.
    """
    probe = _exchange_probe()
    narrowest = probe.candidates[-1]
    client, seen = _shop([narrowest], lambda _: [{"returns": {"nodes": [{"id": "1", "status": "OPEN"}]}}])

    result = run_probe(client, probe, sample_size=5)

    assert result.available is True
    assert result.field_expression == narrowest
    assert len(seen) == len(probe.candidates)
    assert result.summary["shopify_reports_exchange_line_items"] is False
