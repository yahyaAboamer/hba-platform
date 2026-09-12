"""The catalogue route, called.

**Written after a 500 reached staging.** The catalogue gained two columns —
model coverage and the feature request — and a third field that did not exist:
`Product.sku`. A SKU belongs to a *variant*, not to a product, so the attribute
raised and every request to this route returned *Internal Server Error*.

Nothing caught it, because **nothing in the suite had ever called
`GET /api/products`**. The service functions behind it were tested, the route
was reachable, the types checked and the build passed — and none of that
exercises the payload the screen actually receives. This file does.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}

PANTS = "gid://shopify/Product/1"
TOP = "gid://shopify/Product/2"


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _product(product_id: str, title: str, status: str = "active") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO product (shopify_product_id, title, status,"
                " synced_at) VALUES (:i, :t, :s, now())"
            ),
            {"i": product_id, "t": title, "s": status},
        )


def test_the_catalogue_answers_at_all(client):
    """The regression this file exists for.

    A route that raises returns the same 500 whether the cause is a typo or a
    dead database, and the screen shows *Unexpected token 'I'* — the browser
    failing to parse the word *Internal*. That is what the owner saw.
    """
    _product(PANTS, "Wide-leg trousers")

    response = client.get("/api/products")

    assert response.status_code == 200, response.text


def test_every_row_carries_what_the_catalogue_draws(client):
    """The columns of the approved table, each present by name.

    Asserted on the payload rather than on the screen: this is the contract
    between them, and it is the half that was broken.
    """
    _product(PANTS, "Wide-leg trousers")

    row = client.get("/api/products").json()["products"][0]

    for field in (
        "shopify_product_id",
        "title",
        "status",
        "image_url",
        "sizes",
        "models_with_it",
        "featured",
    ):
        assert field in row, f"the catalogue draws {field}"


def test_a_product_carries_no_sku_of_its_own(client):
    """**The bug, held open.**

    A SKU belongs to a variant. A garment has one per size, so a product-level
    SKU is either absent or a fact about one size wearing the product's name.
    The catalogue shows the size count instead, and this makes sure nobody
    reintroduces the field by reading it off the model again.
    """
    _product(PANTS, "Wide-leg trousers")

    row = client.get("/api/products").json()["products"][0]

    assert "sku" not in row


def test_coverage_and_feature_default_to_nothing_rather_than_missing(client):
    """A product nobody has and nobody has asked about still draws a row.

    `0` and `None` are the two answers the screen turns into *Nobody yet* and
    *—*; a key that is absent altogether would render as `undefined`.
    """
    _product(PANTS, "Wide-leg trousers")

    row = client.get("/api/products").json()["products"][0]

    assert row["models_with_it"] == 0
    assert row["featured"] is None


def test_archived_products_are_left_out_unless_asked_for(client):
    _product(PANTS, "Wide-leg trousers")
    _product(TOP, "Cropped top", status="archived")

    active = client.get("/api/products").json()
    everything = client.get("/api/products?all_products=true").json()

    assert [row["title"] for row in active["products"]] == ["Wide-leg trousers"]
    assert len(everything["products"]) == 2


def test_a_model_may_not_read_the_catalogue(client):
    """The roster, the coverage and what HBA is promoting are staff facts."""
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))

    assert client.get("/api/products").status_code == 403
