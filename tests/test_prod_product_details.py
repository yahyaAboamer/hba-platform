"""The product on a production order (build plan 2026-11-19, section 1 and 4).

The details (colour code, fabric, print / embroidery type and width), who
supplies the product, its pattern files and size charts, the owner's COGS, and
the style picker's draft products. Every name and figure here is invented.
"""

from urllib.parse import quote

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.shared.models.audit import AuditEvent
from app.shared.models.catalogue import Product
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    PNG,
    _all_the_way,
    _cut,
    _new,
    _no_money,
    _ok,
    _person,
    _to_cutting,
    bucket,
    owner,
    staff,
    viewer,
)

DETAILS = {
    "colour_code": "Pantone 19-0303",
    "fabric_type": "Cotton fleece 320 gsm",
    "decoration_type": "DTF print",
    "decoration_width_cm": 12.54,
}


def _summaries(order_id: int) -> list[str]:
    with SessionLocal() as db:
        return [
            (e.after_json or {}).get("summary") or ""
            for e in db.scalars(
                select(AuditEvent).where(AuditEvent.subject == f"production:order:{order_id}").order_by(AuditEvent.id)
            )
        ]


# ── The details ───────────────────────────────────────────────────────────────


def test_a_new_order_has_an_empty_product_card(owner, viewer):
    order = _new(owner)
    assert order["product"] == {
        "colour_code": None,
        "fabric_type": None,
        "decoration_type": None,
        "decoration_width_cm": None,
        "suppliers": [{"id": "fac", "name": "Main factory", "roles": ["Factory"]}],
        "pattern_files": [],
        "size_charts": [],
    }
    assert viewer.get(f"/api/prod/orders/{order['id']}").json()["order"]["product"] == order["product"]


def test_the_details_are_saved_on_create_and_on_edit_and_cleared_when_blank(owner, staff):
    made = _new(owner, colour_code="  #2F3A2F ", decoration_width_cm="7")
    assert made["product"]["colour_code"] == "#2F3A2F" and made["product"]["decoration_width_cm"] == "7.0"

    oid = made["id"]
    assert staff.patch(f"/api/prod/orders/{oid}", json=DETAILS).status_code == 403
    edited = _ok(owner.patch(f"/api/prod/orders/{oid}", json=DETAILS))["product"]
    assert edited["colour_code"] == "Pantone 19-0303"
    assert edited["fabric_type"] == "Cotton fleece 320 gsm"
    assert edited["decoration_type"] == "DTF print"
    assert edited["decoration_width_cm"] == "12.5"  # one decimal
    assert "colour code, fabric type, print / embroidery type and print / embroidery width" in _summaries(oid)[-1]

    # The same again changes nothing and writes no history.
    before = len(_summaries(oid))
    _ok(owner.patch(f"/api/prod/orders/{oid}", json=DETAILS))
    assert len(_summaries(oid)) == before

    cleared = _ok(
        owner.patch(
            f"/api/prod/orders/{oid}",
            json={"colour_code": "   ", "fabric_type": None, "decoration_type": "", "decoration_width_cm": None},
        )
    )["product"]
    assert [cleared[k] for k in DETAILS] == [None, None, None, None]
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT colour_code, fabric_type, decoration_type, decoration_width_cm FROM prod_order WHERE id = :id"),
            {"id": oid},
        ).one()
    assert tuple(row) == (None, None, None, None)


@pytest.mark.parametrize(
    "body, words",
    [
        ({"decoration_width_cm": 0}, "more than 0"),
        ({"decoration_width_cm": -3}, "more than 0"),
        ({"decoration_width_cm": 1000}, "999.9"),
        ({"decoration_width_cm": 0.04}, "more than 0"),
        ({"colour_code": "x" * 41}, "40 characters"),
        ({"fabric_type": "x" * 121}, "120 characters"),
    ],
)
def test_a_detail_is_refused_in_words(owner, body, words):
    oid = _new(owner)["id"]
    refused = owner.patch(f"/api/prod/orders/{oid}", json=body)
    assert refused.status_code == 422 and words in refused.json()["detail"], refused.text


def test_the_details_are_kept_once_the_order_is_closed_or_cancelled(owner):
    oid = _new(owner, **DETAILS)["id"]
    _ok(owner.post(f"/api/prod/orders/{oid}/cancel", json={"reason": "Style dropped"}))
    refused = owner.patch(f"/api/prod/orders/{oid}", json={"fabric_type": "Jersey"})
    assert refused.status_code == 409
    assert owner.get(f"/api/prod/orders/{oid}").json()["order"]["product"]["fabric_type"] == "Cotton fleece 320 gsm"


# ── Who supplies it ───────────────────────────────────────────────────────────


def test_the_suppliers_are_the_factory_the_print_house_and_every_purchase_not_voided(owner, viewer):
    order = _new(owner, printing="outside", print_supplier_id="prt")
    oid = order["id"]
    delta = owner.post("/api/prod/suppliers", json={"name": "Delta Fabrics"}).json()["supplier"]["id"]
    zinc = owner.post("/api/prod/suppliers", json={"name": "Zinc Trims"}).json()["supplier"]["id"]

    def buy(supplier: str, part: str, item: str) -> int:
        response = owner.post(
            f"/api/prod/suppliers/{supplier}/purchases",
            json={"item": item, "quantity": 10, "unit": "piece", "unit_price_piastres": 500, "part": part, "order_id": oid},
        )
        assert response.status_code == 201, response.text
        return response.json()["purchase_id"]

    buy(delta, "fabric", "Fleece")
    buy("prt", "accessories", "Labels")
    buy("prt", "printing", "Back print")  # a repeat role is not told twice
    buy("fac", "packaging", "Bags")
    voided = buy(zinc, "accessories", "Zips")
    assert owner.post(f"/api/prod/purchases/{voided}/void", json={"reason": "Typed in wrongly"}).status_code == 200

    suppliers = viewer.get(f"/api/prod/orders/{oid}").json()["order"]["product"]["suppliers"]
    assert suppliers == [
        {"id": "fac", "name": "Main factory", "roles": ["Factory", "Packaging"]},
        {"id": delta, "name": "Delta Fabrics", "roles": ["Fabric"]},
        {"id": "prt", "name": "Print house A", "roles": ["Printing", "Accessories"]},
    ]


# ── Pattern files and size charts ─────────────────────────────────────────────


def test_a_pattern_may_be_any_file_and_is_only_ever_downloaded(owner, staff, viewer, bucket):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/files"
    name = "نموذج front's; v2.dxf"  # a browser sends a double quote as %22, so none here
    dxf = b"0\nSECTION\n2\nHEADER\n"
    saved = staff.post(url, files={"file": (name, dxf, "application/dxf")}, data={"kind": "pattern"})
    assert saved.status_code == 201, saved.text
    pattern = saved.json()["file"]
    assert pattern["kind"] == "pattern" and pattern["mime_type"] == "application/octet-stream"
    assert pattern["name"] == name

    served = viewer.get(pattern["url"])
    assert served.status_code == 200 and served.content == dxf
    disposition = served.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="')
    assert disposition.endswith("filename*=UTF-8''" + quote(name, safe=""))
    fallback = disposition.split('filename="')[1].split('"')[0]
    assert fallback and all(ch.isascii() and ch not in '"\\;' for ch in fallback)
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["content-type"].startswith("application/octet-stream")

    # A photo pattern stays inline; a PDF size chart too.
    photo = staff.post(url, files={"file": ("front.png", PNG, "image/png")}, data={"kind": "pattern"}).json()["file"]
    assert viewer.get(photo["url"]).headers["content-disposition"] == "inline"
    chart = staff.post(url, files={"file": ("sizes.pdf", b"%PDF-1.7 ...", "application/pdf")}, data={"kind": "size_chart"})
    assert chart.status_code == 201 and chart.json()["file"]["kind"] == "size_chart"
    assert viewer.get(chart.json()["file"]["url"]).headers["content-disposition"] == "inline"
    # An ordinary file has no kind, and an unknown kind is an ordinary file.
    plain = staff.post(url, files={"file": ("x.png", PNG, "image/png")}, data={"kind": "nonsense"}).json()["file"]
    assert plain["kind"] is None

    product = viewer.get(f"/api/prod/orders/{oid}").json()["order"]["product"]
    assert [f["id"] for f in product["pattern_files"]] == [photo["id"], pattern["id"]]  # newest first
    assert [f["id"] for f in product["size_charts"]] == [chart.json()["file"]["id"]]
    assert {f["kind"] for f in viewer.get(url).json()["files"]} == {"pattern", "size_chart", None}
    assert any("as the pattern file" in s for s in _summaries(oid))

    # Removed: off the card.
    assert staff.delete(pattern["url"]).status_code == 200
    assert [f["id"] for f in viewer.get(f"/api/prod/orders/{oid}").json()["order"]["product"]["pattern_files"]] == [photo["id"]]


def test_a_size_chart_or_ordinary_file_must_be_a_photo_or_pdf(owner, staff, bucket):
    oid = _new(owner)["id"]
    url = f"/api/prod/orders/{oid}/files"
    for data in ({"kind": "size_chart"}, {}):
        refused = staff.post(url, files={"file": ("sizes.xlsx", b"PK\x03\x04 sheet", "application/zip")}, data=data)
        assert refused.status_code == 422 and "photo" in refused.json()["detail"]
    assert bucket.files == {}
    assert staff.post(url, files={"file": ("p.dxf", b"", "application/dxf")}, data={"kind": "pattern"}).status_code == 422


# ── COGS (the owner's) ────────────────────────────────────────────────────────


def test_cogs_is_the_piece_cost_over_planned_then_cut_then_passed(owner):
    # Per piece: 16,500 + 8,500 + 3,000 + 1,200 + 800 = 30,000 piastres.
    order = _new(owner)
    assert order["cost"]["cogs"] == {
        "per_piece_piastres": 30000, "pieces": 1000, "pieces_basis": "planned", "total_piastres": 30_000_000,
    }
    oid = order["id"]
    _to_cutting(owner, oid)
    cut = _cut(owner, oid)
    assert cut["cost"]["cogs"] == {
        "per_piece_piastres": 30000, "pieces": 972, "pieces_basis": "cut", "total_piastres": 29_160_000,
    }
    # An actual typed counts instead of its target.
    typed = _ok(owner.patch(f"/api/prod/orders/{oid}", json={"actual_fabric_piastres": 17500}))
    assert typed["cost"]["cogs"]["per_piece_piastres"] == 31000
    assert typed["cost"]["cogs"]["total_piastres"] == 31000 * 972

    done = _all_the_way(owner)
    assert done["cost"]["cogs"] == {
        "per_piece_piastres": 30000, "pieces": 926, "pieces_basis": "passed", "total_piastres": 27_780_000,
    }


@pytest.mark.parametrize("role", ["production_viewer", "production_staff"])
def test_nobody_without_the_owner_permission_sees_cogs_or_money_in_the_product(owner, role, bucket):
    order = _all_the_way(owner)
    oid = order["id"]
    _ok(owner.patch(f"/api/prod/orders/{oid}", json=DETAILS))
    owner.post(
        "/api/prod/suppliers/prt/purchases",
        json={"item": "Labels", "quantity": 3, "unit": "piece", "unit_price_piastres": 700, "part": "accessories", "order_id": oid},
    )
    owner.post(f"/api/prod/orders/{oid}/files", files={"file": ("p.dxf", b"DXF", "x")}, data={"kind": "pattern"})
    assert "cogs" in owner.get(f"/api/prod/orders/{oid}").json()["order"]["cost"]

    person = _person(f"{role}@example.com", role)
    response = person.get(f"/api/prod/orders/{oid}")
    seen = response.json()["order"]
    assert seen["product"]["suppliers"] == [
        {"id": "fac", "name": "Main factory", "roles": ["Factory"]},
        {"id": "prt", "name": "Print house A", "roles": ["Accessories"]},
    ]
    assert seen["product"]["pattern_files"] and "cost" not in seen
    _no_money(seen["product"], "product")
    _no_money(response.json(), "order")
    assert "piastres" not in response.text and "cogs" not in response.text


# ── The style picker (section 4) ──────────────────────────────────────────────


def test_the_style_picker_offers_active_and_draft_products_with_their_picture(owner, viewer):
    with SessionLocal() as db:
        db.add(Product(shopify_product_id="333", title="Arctic parka", status="draft", image_url="https://cdn.example.com/p.jpg"))
        db.add(Product(shopify_product_id="444", title="Zipped fleece", status="active"))
        db.commit()
    products = viewer.get("/api/prod/choices").json()["products"]
    assert products == [
        {"id": "333", "title": "Arctic parka", "status": "draft", "image_url": "https://cdn.example.com/p.jpg"},
        {"id": "111", "title": "Oversized hoodie", "status": "active", "image_url": None},
        {"id": "444", "title": "Zipped fleece", "status": "active", "image_url": None},
    ]
    assert "222" not in {p["id"] for p in products}  # archived

    # An order may be made, and changed, with a draft product.
    order = _new(owner, shopify_product_id="333")
    assert order["shopify_product_id"] == "333"
    assert _ok(owner.patch(f"/api/prod/orders/{order['id']}", json={"shopify_product_id": "111"}))["shopify_product_id"] == "111"
    assert _ok(owner.patch(f"/api/prod/orders/{order['id']}", json={"shopify_product_id": "333"}))["shopify_product_id"] == "333"
    assert owner.patch(f"/api/prod/orders/{order['id']}", json={"shopify_product_id": "999"}).status_code == 422


# ── The migration ─────────────────────────────────────────────────────────────


def _version() -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_the_migration_goes_down_and_up_cleanly_when_empty(fresh_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    try:
        command.downgrade(config, "e5b9a3d70038")
        assert _version() == "e5b9a3d70038"
        with engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('prod_task_update')")).scalar_one() is None
            assert connection.execute(text("SELECT to_regclass('uq_prod_supplier_receipt_live')")).scalar_one() is not None
    finally:
        command.upgrade(config, "head")
    assert _version() == "f1c2d3e40039"
    with engine.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('prod_task_update')")).scalar_one() is not None
        assert connection.execute(text("SELECT to_regclass('uq_prod_supplier_receipt_live')")).scalar_one() is None


def test_the_downgrade_refuses_while_a_product_detail_exists(owner):
    from alembic import command
    from alembic.config import Config

    _new(owner, fabric_type="Jersey")
    with pytest.raises(RuntimeError, match="product details"):
        command.downgrade(Config("alembic.ini"), "e5b9a3d70038")
    assert _version() == "f1c2d3e40039"
