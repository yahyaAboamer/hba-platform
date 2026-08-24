"""The operational view.

Spec section 10.5: failed jobs are visible in the interface, not buried in
logs. The maintainer should learn about a sync failure from the platform, not
from a confused affiliate.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.services.jobs import JobKind

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}


@pytest.fixture()
def anonymous(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client(fresh_database):
    """Signed in as the administrator."""
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    """Change the signed-in account's role without touching its session."""
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _add_order(order_id: str, code: str, *, month: str = "2026-08") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency) "
                "VALUES (:i, :n, now(), :m, ARRAY[:c], 0, 0, 0, 0, 'EGP')"
            ),
            {"i": order_id, "n": f"#{order_id}", "m": month, "c": code},
        )


def _register_code(code: str, start_month: str, end_month: str | None = None) -> int:
    """Give a code an owner, the way the affiliate API does.

    Creates the account and profile inline: this file tests the operational
    view, not the registry, and going through the HTTP layer here would make
    these tests fail for reasons that have nothing to do with what they check.
    """
    from app.core.passwords import hash_password

    with engine.begin() as connection:
        account_id = connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status) "
                "VALUES (:e, :p, 'active') RETURNING id"
            ),
            {"e": f"{code.lower()}@example.com", "p": hash_password("a-long-password")},
        ).scalar()
        affiliate_id = connection.execute(
            text(
                "INSERT INTO affiliate_profile (user_account_id, name, status) "
                "VALUES (:u, :n, 'active') RETURNING id"
            ),
            {"u": account_id, "n": code},
        ).scalar()
        connection.execute(
            text(
                "INSERT INTO discount_code_period "
                "(affiliate_id, code, start_month, end_month) "
                "VALUES (:a, :c, :s, :e)"
            ),
            {"a": affiliate_id, "c": code.upper(), "s": start_month, "e": end_month},
        )
    return affiliate_id


def _codes_reported(client) -> dict[str, int]:
    body = client.get("/api/operations/unregistered-codes").json()
    return {row["code"]: row["order_count"] for row in body["codes"]}


def _add_failed_job(kind: str = "shopify_sync_order", error: str = "Shopify timed out"):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO background_job (kind, payload, status, attempts, "
                "last_error, finished_at) "
                "VALUES (:k, '{\"order_id\": \"5123456789\"}'::jsonb, 'failed', 5, "
                ":e, now())"
            ),
            {"k": kind, "e": error},
        )


# ── Nothing here is public ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/api/operations/sync", "/api/operations/failed-jobs",
     "/api/operations/unregistered-codes"],
)
def test_operational_views_require_authentication(anonymous, path):
    assert anonymous.get(path).status_code == 401


def test_verifying_a_code_requires_authentication(anonymous):
    response = anonymous.post("/api/operations/verify-code", json={"code": "X"})
    assert response.status_code in (401, 403)


def test_starting_an_import_requires_authentication(anonymous):
    response = anonymous.post("/api/operations/start-import", json={})
    assert response.status_code in (401, 403)


def test_an_affiliate_cannot_see_operational_state(client):
    """Affiliates hold no permissions at all. Failed jobs name order ids and
    every discount code in the shop - none of it theirs to see.
    """
    _demote_to("affiliate")
    assert client.get("/api/operations/sync").status_code == 403
    assert client.get("/api/operations/failed-jobs").status_code == 403
    assert client.get("/api/operations/unregistered-codes").status_code == 403


def test_only_an_administrator_may_start_an_import(client):
    """It runs an export over the shop's whole history, and Shopify allows one
    at a time. Not something a manager should be able to set off.
    """
    _demote_to("affiliate_manager")
    response = client.post("/api/operations/start-import", json={})
    assert response.status_code == 403


def test_a_manager_may_still_read_the_operational_view(client):
    """Guards the tests above: they must be failing on the permission, not on
    a broken endpoint that would 403 for everyone.
    """
    _demote_to("affiliate_manager")
    assert client.get("/api/operations/sync").status_code == 200


# ── Sync status ────────────────────────────────────────────────────────────────


def test_sync_status_reports_counts(client):
    body = client.get("/api/operations/sync").json()
    assert body["orders_indexed"] == 0
    assert body["jobs"] == {"pending": 0, "running": 0, "succeeded": 0, "failed": 0}


def test_sync_status_counts_indexed_orders(client):
    _add_order("1", "HBA10")
    _add_order("2", "HBA10")
    body = client.get("/api/operations/sync").json()
    assert body["orders_indexed"] == 2
    assert body["last_order_synced_at"] is not None


def test_sync_status_reports_whether_shopify_is_configured(client):
    body = client.get("/api/operations/sync").json()
    assert "shopify_configured" in body
    assert "webhooks_configured" in body


def test_sync_status_reports_the_recurring_schedule(client):
    """Recurring work is queued by the worker itself, so if the worker stops it
    stops too - with no error, because nothing failed. This is what makes that
    visible rather than silent (docs/limits.md).
    """
    body = client.get("/api/operations/sync").json()
    assert JobKind.RECONCILE in body["recurring"]
    assert body["recurring"][JobKind.RECONCILE]["scheduled"] is False


def test_a_scheduled_sweep_shows_as_scheduled(client):
    from app.db import SessionLocal
    from app.services.schedule import ensure_scheduled

    with SessionLocal() as session:
        ensure_scheduled(session)
        session.commit()

    body = client.get("/api/operations/sync").json()
    reconcile = body["recurring"][JobKind.RECONCILE]
    assert reconcile["scheduled"] is True
    assert reconcile["next_due_at"] is not None


# ── Failed jobs ────────────────────────────────────────────────────────────────


def test_failed_jobs_are_listed(client):
    _add_failed_job()
    body = client.get("/api/operations/failed-jobs").json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["last_error"] == "Shopify timed out"
    assert body["jobs"][0]["attempts"] == 5


def test_a_failed_job_shows_what_it_was_trying_to_do(client):
    """Without the payload, "shopify_sync_order failed" names no order and
    nobody can act on it.
    """
    _add_failed_job()
    job = client.get("/api/operations/failed-jobs").json()["jobs"][0]
    assert job["payload"]["order_id"] == "5123456789"


def test_succeeded_jobs_are_not_listed_as_failures(client):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO background_job (kind, payload, status, finished_at) "
                "VALUES ('shopify_sync_order', '{}'::jsonb, 'succeeded', now())"
            )
        )
    assert client.get("/api/operations/failed-jobs").json()["jobs"] == []


def test_no_failures_is_an_empty_list_not_an_error(client):
    assert client.get("/api/operations/failed-jobs").json() == {"jobs": []}


# ── Codes in use ───────────────────────────────────────────────────────────────


def test_unregistered_codes_are_surfaced(client):
    """A code live in Shopify but owned by nobody means missing attribution."""
    _add_order("1", "SARA10")
    _add_order("2", "SARA10")
    _add_order("3", "HBA10")

    body = client.get("/api/operations/unregistered-codes").json()
    counts = {row["code"]: row["order_count"] for row in body["codes"]}
    assert counts == {"SARA10": 2, "HBA10": 1}


def test_codes_are_ordered_by_how_much_is_at_stake(client):
    for order_id in range(1, 4):
        _add_order(str(order_id), "BUSY")
    _add_order("9", "QUIET")

    codes = client.get("/api/operations/unregistered-codes").json()["codes"]
    assert [row["code"] for row in codes] == ["BUSY", "QUIET"]


def test_an_order_with_no_code_contributes_nothing(client):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, subtotal_piastres, total_piastres, shipping_piastres, "
                "tax_piastres, currency) "
                "VALUES ('7', '#7', now(), '2026-08', 0, 0, 0, 0, 'EGP')"
            )
        )
    assert client.get("/api/operations/unregistered-codes").json()["codes"] == []


# ── Starting the historical import ─────────────────────────────────────────────


def test_starting_an_import_queues_the_job(client):
    response = client.post("/api/operations/start-import", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT kind, payload FROM background_job")
        ).one()
    assert row[0] == JobKind.BULK_IMPORT
    assert row[1]["since"] == "2026-01-01"


def test_the_import_start_date_can_be_chosen(client):
    client.post("/api/operations/start-import", json={"since": "2026-03-01"})
    with engine.connect() as connection:
        payload = connection.execute(text("SELECT payload FROM background_job")).scalar()
    assert payload["since"] == "2026-03-01"


@pytest.mark.parametrize("bad", ["yesterday", "2026-13-01", "01-01-2026", ""])
def test_a_nonsense_start_date_is_refused(client, bad):
    response = client.post("/api/operations/start-import", json={"since": bad})
    assert response.status_code == 422


def test_a_second_import_is_refused_while_one_is_running(client):
    """Shopify runs one bulk operation per shop. Two would fight, and the
    second would fail in a way that looks like a platform bug.
    """
    assert client.post("/api/operations/start-import", json={}).status_code == 200
    second = client.post("/api/operations/start-import", json={})
    assert second.status_code == 409
    assert "already in progress" in second.json()["detail"]

    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM background_job")
        ).scalar()
    assert count == 1


def test_an_import_can_be_started_again_once_the_last_one_finished(client):
    client.post("/api/operations/start-import", json={})
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE background_job SET status = 'succeeded', finished_at = now()")
        )

    assert client.post("/api/operations/start-import", json={}).status_code == 200


# ── Verifying a code ───────────────────────────────────────────────────────────


def _stub_shopify(monkeypatch, node=None, error=None):
    """Point the endpoint at a fake Shopify rather than the real shop."""
    import httpx

    from app.services.shopify.client import ShopifyClient

    def handler(request: httpx.Request) -> httpx.Response:
        if error is not None:
            return httpx.Response(200, json={"errors": [error]})
        return httpx.Response(200, json={"data": {"codeDiscountNodeByCode": node}})

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr("app.services.shopify.sync.build_client", lambda: client)


ACTIVE_CODE = {
    "codeDiscount": {
        "__typename": "DiscountCodeBasic",
        "title": "NOUR10",
        "status": "ACTIVE",
        "asyncUsageCount": 47,
        "customerGets": {
            "value": {"__typename": "DiscountPercentage", "percentage": 0.1}
        },
    }
}


def test_verifying_an_existing_code_returns_its_details(client, monkeypatch):
    _stub_shopify(monkeypatch, node=ACTIVE_CODE)
    response = client.post("/api/operations/verify-code", json={"code": "nour10"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["exists"] is True
    assert body["code"] == "NOUR10"
    assert body["discount_bp"] == 1000


def test_verifying_a_missing_code_is_a_normal_answer(client, monkeypatch):
    """Not a 404. The caller asked a question and got an answer."""
    _stub_shopify(monkeypatch, node=None)
    response = client.post("/api/operations/verify-code", json={"code": "NOUR1O"})

    assert response.status_code == 200
    assert response.json()["exists"] is False


def test_an_ungranted_scope_says_so_instead_of_blaming_the_network(
    client, monkeypatch
):
    """The failure this platform will actually hit first.

    Without read_discounts every lookup is denied. Reporting that as "could not
    reach Shopify" would send someone debugging connectivity when the fix is
    one checkbox in the app configuration.
    """
    _stub_shopify(
        monkeypatch,
        error={
            "message": "Access denied for codeDiscountNodeByCode",
            "extensions": {"code": "ACCESS_DENIED"},
        },
    )
    response = client.post("/api/operations/verify-code", json={"code": "NOUR10"})

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "read_discounts" in detail
    assert "Dev Dashboard" in detail


def test_an_unconfigured_shopify_is_reported_as_unavailable(client, monkeypatch):
    from app.services.shopify.client import ShopifyNotConfigured

    def unconfigured():
        raise ShopifyNotConfigured("Shopify is not configured: set SHOPIFY_SHOP_DOMAIN")

    monkeypatch.setattr("app.services.shopify.sync.build_client", unconfigured)
    response = client.post("/api/operations/verify-code", json={"code": "X"})

    assert response.status_code == 503
    assert "SHOPIFY_SHOP_DOMAIN" in response.json()["detail"]


def test_a_shopify_outage_is_reported_as_a_gateway_failure(client, monkeypatch):
    _stub_shopify(monkeypatch, error={"message": "something broke"})
    response = client.post("/api/operations/verify-code", json={"code": "X"})

    assert response.status_code == 502
    assert "Could not reach Shopify" in response.json()["detail"]


def test_an_empty_code_is_refused_before_reaching_shopify(client, monkeypatch):
    called = []
    monkeypatch.setattr(
        "app.services.shopify.sync.build_client",
        lambda: called.append(1),
    )
    assert client.post("/api/operations/verify-code", json={"code": ""}).status_code == 422
    assert called == []


def test_no_response_mentions_a_commission(client, monkeypatch):
    """The discount is not the commission (spec 10.4), and the API must not
    imply otherwise to whatever renders it.
    """
    _stub_shopify(monkeypatch, node=ACTIVE_CODE)
    body = client.post("/api/operations/verify-code", json={"code": "NOUR10"}).json()
    assert "commission" not in " ".join(body).lower()


# ── What Shopify actually grants ───────────────────────────────────────────────


def _stub_client(monkeypatch, granted: set[str]):
    """A client reporting exactly the scopes Shopify would have returned."""
    import httpx

    from app.services.shopify.client import ShopifyClient

    client = ShopifyClient(
        shop_domain="s.myshopify.com",
        access_token="t",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": {}})),
    )
    client._granted_scopes = set(granted)
    monkeypatch.setattr("app.services.shopify.sync.build_client", lambda: client)
    return client


def test_scopes_reports_what_is_granted_and_what_is_missing(client, monkeypatch):
    """The question "is read_discounts actually granted?" has to be answerable
    with a fact rather than by trying something and reading the error.
    """
    _stub_client(monkeypatch, {"read_orders", "read_all_orders"})
    body = client.get("/api/operations/shopify-scopes").json()

    assert body["granted"] == ["read_all_orders", "read_orders"]
    assert body["missing"] == ["read_discounts"]
    assert "read_discounts" in body["required"]
    assert body["reported_by_shopify"] is True


def test_scopes_reports_nothing_missing_once_everything_is_granted(client, monkeypatch):
    _stub_client(monkeypatch, {"read_orders", "read_all_orders", "read_discounts"})
    body = client.get("/api/operations/shopify-scopes").json()

    assert body["missing"] == []


def test_an_unknown_scope_list_is_not_reported_as_everything_missing(
    client, monkeypatch
):
    """A static token carries no scope list. Saying "all missing" would send
    someone re-granting scopes that were never the problem.
    """
    _stub_client(monkeypatch, set())
    body = client.get("/api/operations/shopify-scopes").json()

    assert body["granted"] == []
    assert body["missing"] == []
    assert body["reported_by_shopify"] is False


def test_only_an_administrator_may_read_the_scopes(client, monkeypatch):
    """It forces a token exchange against Shopify."""
    _stub_client(monkeypatch, {"read_orders"})
    _demote_to("affiliate_manager")
    assert client.get("/api/operations/shopify-scopes").status_code == 403


def test_scopes_requires_authentication(anonymous):
    assert anonymous.get("/api/operations/shopify-scopes").status_code == 401


def test_scopes_reports_an_unconfigured_shopify_clearly(client, monkeypatch):
    from app.services.shopify.client import ShopifyNotConfigured

    def unconfigured():
        raise ShopifyNotConfigured("Shopify is not configured: set SHOPIFY_SHOP_DOMAIN")

    monkeypatch.setattr("app.services.shopify.sync.build_client", unconfigured)
    assert client.get("/api/operations/shopify-scopes").status_code == 503


# ── Unregistered means unregistered (Phase 3 Task 8) ───────────────────────────


def test_a_registered_code_is_no_longer_reported_as_unregistered(client):
    """The endpoint's name finally matches what it returns.

    Until an affiliate could own a code, this listed every code seen. Now a
    code owned for the month an order was placed is registered, and drops out.
    """
    _add_order("1", "SARA10", month="2026-08")
    _add_order("2", "HBA10", month="2026-08")
    assert _codes_reported(client) == {"SARA10": 1, "HBA10": 1}

    _register_code("SARA10", "2026-01")
    assert _codes_reported(client) == {"HBA10": 1}


def test_a_code_registered_for_a_later_month_is_still_unregistered_earlier(client):
    """Ownership is dated. Registering NOUR10 from September does not make
    April's NOUR10 orders owned - those sales still belong to nobody.
    """
    _add_order("1", "NOUR10", month="2026-04")
    _add_order("2", "NOUR10", month="2026-09")

    _register_code("NOUR10", "2026-09")

    assert _codes_reported(client) == {"NOUR10": 1}


def test_the_report_names_the_months_that_are_unowned(client):
    """So somebody registering the code knows which month to start it from."""
    _add_order("1", "NOUR10", month="2026-04")
    _add_order("2", "NOUR10", month="2026-05")
    _add_order("3", "NOUR10", month="2026-09")
    _register_code("NOUR10", "2026-09")

    row = client.get("/api/operations/unregistered-codes").json()["codes"][0]
    assert row["code"] == "NOUR10"
    assert row["unowned_months"] == ["2026-04", "2026-05"]


def test_a_code_owned_for_every_month_it_appears_in_is_absent(client):
    _add_order("1", "NOUR10", month="2026-04")
    _add_order("2", "NOUR10", month="2026-05")
    _register_code("NOUR10", "2026-01")

    assert _codes_reported(client) == {}


def test_a_closed_code_period_leaves_later_orders_unregistered(client):
    """An affiliate left in June; her code kept being used in August. Those
    sales belong to nobody, and that is exactly what this report is for.
    """
    _add_order("1", "NOUR10", month="2026-05")
    _add_order("2", "NOUR10", month="2026-08")
    _register_code("NOUR10", "2026-01", "2026-06")

    assert _codes_reported(client) == {"NOUR10": 1}


def test_case_does_not_defeat_the_subtraction(client):
    """Codes are stored upper-case; an order carrying a lowercase one must
    still count as owned, or a registered code would be reported as orphaned.
    """
    _add_order("1", "nour10", month="2026-08")
    _register_code("NOUR10", "2026-01")

    assert _codes_reported(client) == {}


def test_the_house_code_is_reported_when_nobody_owns_it(client):
    """HBA10 is a real code taking real money. Unowned, its sales attribute to
    nobody, and that is worth seeing even though it is never payable.
    """
    _add_order("1", "HBA10", month="2026-08")
    assert _codes_reported(client) == {"HBA10": 1}


def test_ordering_still_puts_the_costliest_first(client):
    for order_id in range(1, 4):
        _add_order(str(order_id), "BUSY", month="2026-08")
    _add_order("9", "QUIET", month="2026-08")
    _register_code("OWNED", "2026-01")
    _add_order("10", "OWNED", month="2026-08")

    codes = client.get("/api/operations/unregistered-codes").json()["codes"]
    assert [row["code"] for row in codes] == ["BUSY", "QUIET"]
