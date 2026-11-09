"""Products kept current: a webhook per edit, a daily read, and a button.

The owner asked on 9 November 2026 for new and edited Shopify products to
reach the dashboard without anybody remembering to re-read the catalogue.
"""

import hashlib
import hmac
import base64
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.businesstime import utcnow
from app.db import engine
from app.main import app
from app.shared.models.catalogue import Product
from app.shared.models.integration import BackgroundJob
from app.shared.services.jobs import JobKind, JobStatus, enqueue
from app.shared.services.schedule import SCHEDULE
from app.shared.services.shopify.catalogue import (
    catalogue_refreshing,
    refresh_catalogue_now,
    sync_one_product,
)

SECRET = "product-webhook-secret"
BOOTSTRAP = {"email": "owner@example.com", "display_name": "Owner", "password": "quiet-harbour-lantern"}


def _node(product_id="8891234567890", title="HBA CLUB pants"):
    return {
        "id": f"gid://shopify/Product/{product_id}",
        "legacyResourceId": product_id,
        "title": title,
        "handle": "hba-club-pants",
        "status": "ACTIVE",
        "updatedAt": "2026-11-09T10:00:00Z",
        "featuredMedia": None,
        "variants": {"nodes": [{
            "id": "gid://shopify/ProductVariant/1", "legacyResourceId": "1",
            "title": "M", "sku": "PANTS-M", "position": 1,
        }]},
    }


class OneProduct:
    def __init__(self, node):
        self.node = node
        self.asked = []

    def require_scope(self, scope):
        pass

    def execute(self, document, variables=None):
        self.asked.append(variables)
        return {"product": self.node}


# ── One product ───────────────────────────────────────────────────────────────


def test_an_edited_product_is_written_over_what_was_there(db):
    sync_one_product(db, OneProduct(_node(title="Old name")), "8891234567890")
    client = OneProduct(_node(title="New name"))

    assert sync_one_product(db, client, "8891234567890") is True
    assert client.asked == [{"id": "gid://shopify/Product/8891234567890"}]
    assert db.get(Product, "8891234567890").title == "New name"


def test_a_product_shopify_no_longer_has_is_left_alone(db):
    sync_one_product(db, OneProduct(_node()), "8891234567890")

    assert sync_one_product(db, OneProduct(None), "8891234567890") is False
    assert db.get(Product, "8891234567890") is not None


# ── The webhook ───────────────────────────────────────────────────────────────


@pytest.fixture()
def hook(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_webhook_secret", SECRET)
    monkeypatch.setattr("app.config.settings.worker_enabled", False)
    with TestClient(app) as test_client:
        yield test_client


def _post(client, payload, topic, event_id):
    body = json.dumps(payload).encode()
    signature = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()
    return client.post("/api/webhooks/shopify", content=body, headers={
        "Content-Type": "application/json", "X-Shopify-Hmac-Sha256": signature,
        "X-Shopify-Topic": topic, "X-Shopify-Webhook-Id": event_id,
    })


def _jobs():
    with engine.connect() as connection:
        return connection.execute(text("SELECT kind, payload FROM background_job ORDER BY id")).all()


@pytest.mark.parametrize("topic", ["products/create", "products/update"])
def test_a_product_webhook_queues_a_read_of_that_product(hook, topic):
    assert _post(hook, {"id": 8891234567890, "title": "x"}, topic, "evt-1").status_code == 200

    [(kind, payload)] = _jobs()
    assert kind == JobKind.SYNC_PRODUCT
    assert payload["product_id"] == "8891234567890"


def test_several_saves_of_one_product_are_one_read(hook):
    for n in range(3):
        _post(hook, {"id": 8891234567890}, "products/update", f"evt-{n}")

    assert len(_jobs()) == 1


def test_a_product_webhook_is_never_read_as_an_order(hook):
    _post(hook, {"id": 8891234567890}, "products/update", "evt-1")

    assert all(kind != JobKind.SYNC_ORDER for kind, _ in _jobs())


# ── Daily, and now ────────────────────────────────────────────────────────────


def test_the_whole_catalogue_is_read_daily():
    interval, _payload = SCHEDULE[JobKind.SYNC_CATALOGUE]
    assert interval == timedelta(days=1)


def test_refresh_now_brings_tomorrows_daily_read_forward(db):
    enqueue(db, JobKind.SYNC_CATALOGUE, {}, run_after=utcnow() + timedelta(days=1),
            dedupe_key=JobKind.SYNC_CATALOGUE)
    db.flush()
    assert catalogue_refreshing(db) is False

    state, job = refresh_catalogue_now(db)

    assert state == "queued"
    assert job.run_after <= utcnow()
    assert catalogue_refreshing(db) is True
    assert len(list(db.scalars(select(BackgroundJob)))) == 1


def test_refresh_now_queues_a_read_when_none_is_waiting(db):
    state, job = refresh_catalogue_now(db)

    assert state == "queued" and job.kind == JobKind.SYNC_CATALOGUE


def test_refresh_now_joins_a_read_already_running(db):
    _state, job = refresh_catalogue_now(db)
    job.status = JobStatus.RUNNING
    db.flush()

    assert refresh_catalogue_now(db)[0] == "running"


# ── The routes ────────────────────────────────────────────────────────────────


@pytest.fixture()
def owner(fresh_database, monkeypatch):
    monkeypatch.setattr("app.config.settings.worker_enabled", False)
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def test_the_refresh_button_queues_a_read_and_the_list_says_so(owner):
    assert owner.get("/api/products").json()["refreshing"] is False

    assert owner.post("/api/products/refresh").json() == {"status": "queued"}

    assert owner.get("/api/products").json()["refreshing"] is True


def test_the_settings_sync_still_works_while_the_daily_read_waits(owner):
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO background_job (kind, payload, dedupe_key, run_after, status)"
            " VALUES (:k, '{}', :k, now() + interval '1 day', 'pending')"
        ), {"k": JobKind.SYNC_CATALOGUE})

    assert owner.post("/api/operations/sync-catalogue", json={}).status_code == 200
