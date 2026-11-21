"""Production's Library under /api/prod/library (ADR 0087).

Every product with what HBA types about it: the details, notes, the owner's
COGS, and its design files, size charts and patterns; a new order for a Library
product starts from its details. Every name and figure here is invented.
"""

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.modules.production.orders.services import library as library_service
from app.shared.models.audit import AuditEvent
from app.shared.models.catalogue import Product, ProductVariant
from tests.conftest import alembic_head
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    PNG,
    _Bucket,
    _new,
    _person,
    bucket,
    owner,
    staff,
    viewer,
)

COGS = {
    "cogs_fabric_piastres": 16500,
    "cogs_manufacturing_piastres": 8500,
    "cogs_printing_piastres": 3000,
    "cogs_accessories_piastres": None,
    "cogs_packaging_piastres": 800,
}


@pytest.fixture()
def store(monkeypatch, bucket):
    """The order files' bucket, also behind the Library's files."""
    monkeypatch.setattr(library_service, "file_bucket", lambda: bucket)
    return bucket


def _catalogue() -> None:
    """Besides the seeded hoodie (111, active) and tee (222, archived): a draft
    with sizes out of order, and the hoodie's sizes."""
    with SessionLocal() as db:
        db.add(Product(shopify_product_id="333", title="Cropped jacket", status="draft", handle="cropped-jacket"))
        db.flush()
        for vid, pid, title, sku, position in (
            ("9001", "111", "S", "HD-S", 1),
            ("9003", "111", "L", "HD-L", 3),
            ("9002", "111", "M", "", 2),
            ("9010", "333", "XL", None, None),
            ("9011", "333", "M", "JK-M", 1),
        ):
            db.add(ProductVariant(shopify_variant_id=vid, shopify_product_id=pid, title=title, sku=sku, position=position))
        db.commit()


def _rows(client) -> dict[str, dict]:
    response = client.get("/api/prod/library")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()["products"]}


def _product(client, pid: str = "111") -> dict:
    response = client.get(f"/api/prod/library/{pid}")
    assert response.status_code == 200, response.text
    return response.json()["product"]


def _patch(client, body: dict, pid: str = "111"):
    return client.patch(f"/api/prod/library/{pid}", json=body)


def _audits(pid: str = "111") -> list[AuditEvent]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(AuditEvent).where(AuditEvent.subject == f"production:library:{pid}").order_by(AuditEvent.id)
            )
        )


def _no_amount(payload, where: str = "") -> None:
    """No key that holds an amount of money, at any depth."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert "piastres" not in key and key != "cogs" or isinstance(value, bool), f"money at {where}.{key}"
            _no_amount(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            _no_amount(item, f"{where}[{index}]")


# ── The list ──────────────────────────────────────────────────────────────────


def test_the_list_is_every_product_with_its_sizes_skus_flags_and_orders(owner, viewer, store):
    _catalogue()
    _new(owner)
    _new(owner)
    assert _patch(owner, {"colour_code": "#2F3A2F"}).status_code == 200
    upload = owner.post("/api/prod/library/111/files", files={"file": ("a.png", PNG, "image/png")}, data={"kind": "design"})
    assert upload.status_code == 201, upload.text

    response = viewer.get("/api/prod/library")
    assert response.status_code == 200
    products = response.json()["products"]
    assert [row["id"] for row in products] == ["333", "111", "222"]  # by title
    rows = {row["id"]: row for row in products}
    assert {pid: row["status"] for pid, row in rows.items()} == {"111": "active", "222": "archived", "333": "draft"}

    hoodie = rows["111"]
    assert hoodie == {
        "id": "111",
        "title": "Oversized hoodie",
        "status": "active",
        "image_url": None,
        "sizes": ["S", "M", "L"],
        "skus": ["HD-S", "HD-L"],
        "colour_code": "#2F3A2F",
        "fabric_type": None,
        "filled": {"details": True, "cogs": False, "design": True, "size_chart": False},
        "orders": 2,
    }
    assert rows["333"]["sizes"] == ["M", "XL"] and rows["333"]["skus"] == ["JK-M"]
    assert rows["222"] == {
        "id": "222", "title": "Retired tee", "status": "archived", "image_url": None, "sizes": [], "skus": [],
        "colour_code": None, "fabric_type": None,
        "filled": {"details": False, "cogs": False, "design": False, "size_chart": False}, "orders": 0,
    }

    assert _patch(owner, {"cogs_fabric_piastres": 100}).status_code == 200
    owner_rows = _rows(owner)
    assert owner_rows["111"]["filled"]["cogs"] is True
    _no_amount(owner_rows)  # no amount, even for the owner


def test_signed_out_and_other_departments_cannot_read_the_library(owner):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as stranger:
        assert stranger.get("/api/prod/library").status_code == 401
    inbox = _person("cs@example.com", "customer_service")
    assert inbox.get("/api/prod/library").status_code == 403
    assert inbox.get("/api/prod/library/111").status_code == 403


# ── One product ───────────────────────────────────────────────────────────────


def test_a_product_with_nothing_typed_yet(owner, viewer, staff):
    _catalogue()
    product = _product(owner, "333")
    assert product["id"] == "333" and product["title"] == "Cropped jacket" and product["handle"] == "cropped-jacket"
    assert product["status"] == "draft" and product["image_url"] is None and product["synced_at"]
    assert product["variants"] == [
        {"id": "9011", "title": "M", "sku": "JK-M"},
        {"id": "9010", "title": "XL", "sku": None},
    ]
    assert product["details"] == {
        "colour_code": None, "fabric_type": None, "decoration_type": None, "decoration_width_cm": None, "notes": None,
    }
    assert product["cogs"] == {
        "fabric_piastres": None, "manufacturing_piastres": None, "printing_piastres": None,
        "accessories_piastres": None, "packaging_piastres": None, "total_piastres": None,
    }
    assert product["files"] == {"design": [], "size_chart": [], "pattern": []}
    assert product["orders"] == []
    assert product["updated_at"] is None and product["updated_by"] is None
    assert list(product) == [
        "id", "title", "handle", "status", "image_url", "synced_at", "variants", "details", "cogs", "files",
        "orders", "updated_at", "updated_by",
    ]

    for client in (staff, viewer):
        seen = _product(client, "333")
        assert "cogs" not in seen
        assert {k: v for k, v in product.items() if k != "cogs"} == seen


def test_an_unknown_product_is_404(owner, store):
    assert owner.get("/api/prod/library/999").status_code == 404
    refused = _patch(owner, {"colour_code": "x"}, "999")
    assert refused.status_code == 404 and refused.json()["detail"] == "There is no such product."
    upload = owner.post("/api/prod/library/999/files", files={"file": ("a.png", PNG, "image/png")}, data={"kind": "design"})
    assert upload.status_code == 404
    assert owner.get("/api/prod/library-files/12345").status_code == 404
    assert owner.delete("/api/prod/library-files/12345").status_code == 404


def test_the_orders_of_a_product_newest_first_with_no_money(owner, viewer):
    first = _new(owner, colour="Black")
    second = _new(owner, colour="Olive", planned={"M": 10, "L": 5})
    assert owner.post(f"/api/prod/orders/{first['id']}/cancel", json={"reason": "Style dropped"}).status_code == 200
    _new(owner, shopify_product_id="222")

    orders = _product(viewer)["orders"]
    assert orders == [
        {
            "id": second["id"], "code": second["code"], "colour": "Olive", "status": "open",
            "planned_total": 15, "target_date": second["target_date"],
        },
        {
            "id": first["id"], "code": first["code"], "colour": "Black", "status": "cancelled",
            "planned_total": 1000, "target_date": first["target_date"],
        },
    ]
    _no_amount(_product(viewer))


# ── Changing it (the owner's) ─────────────────────────────────────────────────


def test_the_owner_saves_the_details_and_cogs_and_the_record_is_made_on_the_first_save(owner):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_library_item")).scalar_one() == 0

    response = _patch(
        owner,
        {
            "colour_code": "  Pantone   19-0303 ",
            "fabric_type": "Cotton fleece 320 gsm",
            "decoration_type": "DTF print",
            "decoration_width_cm": 12.54,
            "notes": "Wash cold.\nNo tumble dry.",
            **COGS,
        },
    )
    assert response.status_code == 200, response.text
    product = response.json()["product"]
    assert product["details"] == {
        "colour_code": "Pantone 19-0303",
        "fabric_type": "Cotton fleece 320 gsm",
        "decoration_type": "DTF print",
        "decoration_width_cm": "12.5",
        "notes": "Wash cold.\nNo tumble dry.",
    }
    assert product["cogs"] == {
        "fabric_piastres": 16500, "manufacturing_piastres": 8500, "printing_piastres": 3000,
        "accessories_piastres": None, "packaging_piastres": 800, "total_piastres": 28800,
    }
    assert product["updated_by"] == "Owner" and product["updated_at"]

    # Only what is sent changes; blank and null clear.
    product = _patch(owner, {"fabric_type": "   ", "cogs_printing_piastres": None, "decoration_width_cm": "7"}).json()["product"]
    assert product["details"]["fabric_type"] is None
    assert product["details"]["colour_code"] == "Pantone 19-0303"
    assert product["details"]["decoration_width_cm"] == "7.0"
    assert product["cogs"]["printing_piastres"] is None and product["cogs"]["total_piastres"] == 25800
    assert product["cogs"]["fabric_piastres"] == 16500

    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT colour_code, fabric_type, cogs_fabric_piastres FROM prod_library_item WHERE shopify_product_id = '111'")
        ).one()
    assert tuple(row) == ("Pantone 19-0303", None, 16500)


def test_a_save_that_sets_nothing_makes_no_record_and_no_history(owner):
    assert _patch(owner, {}).status_code == 200
    assert _patch(owner, {"colour_code": "", "cogs_fabric_piastres": None}).status_code == 200
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_library_item")).scalar_one() == 0
    assert _audits() == []

    _patch(owner, {"colour_code": "Black"})
    assert len(_audits()) == 1
    _patch(owner, {"colour_code": "Black"})  # the same again: nothing changed
    assert len(_audits()) == 1


def test_the_history_says_what_changed_and_never_a_figure_of_money(owner):
    _patch(owner, {"colour_code": "Black", "cogs_fabric_piastres": 16500, "cogs_packaging_piastres": 800})
    _patch(owner, {"colour_code": "Olive", "decoration_width_cm": 9})
    first, second = _audits()
    assert first.action == "production.library_updated" and first.department == "production"
    assert first.after_json["product"] == "Oversized hoodie"
    assert first.after_json["summary"] == (
        "Changed the colour code and COGS (fabric and special packaging) of Oversized hoodie in the Library"
    )
    assert first.after_json["cogs_parts"] == ["fabric", "packaging"]
    assert "16500" not in str(first.after_json) and "800" not in str(first.after_json)
    assert "16500" not in str(first.before_json)
    assert second.before_json == {"colour_code": "Black", "decoration_width_cm": None}
    assert second.after_json["colour_code"] == "Olive" and second.after_json["decoration_width_cm"] == "9.0"


@pytest.mark.parametrize(
    "body, words",
    [
        ({"decoration_width_cm": 0}, "more than 0"),
        ({"decoration_width_cm": -3}, "more than 0"),
        ({"decoration_width_cm": 1000}, "999.9"),
        ({"colour_code": "x" * 41}, "40 characters"),
        ({"fabric_type": "x" * 121}, "120 characters"),
        ({"decoration_type": "x" * 121}, "120 characters"),
        ({"notes": "x" * 4001}, "4,000 characters"),
        ({"cogs_fabric_piastres": -1}, "0 or more"),
        ({"cogs_packaging_piastres": 10_000_001}, "too large"),
    ],
)
def test_a_change_is_refused_in_words(owner, body, words):
    refused = _patch(owner, body)
    assert refused.status_code == 422 and words in refused.json()["detail"], refused.text
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_library_item")).scalar_one() == 0


def test_an_unknown_field_is_refused(owner):
    for body in ({"title": "Renamed"}, {"cogs_total_piastres": 5}, {"image_url": "x"}):
        assert _patch(owner, body).status_code == 422


def test_only_the_owner_changes_it(owner, staff, viewer):
    assert _patch(staff, {"colour_code": "Black"}).status_code == 403
    assert _patch(staff, {"cogs_fabric_piastres": 1}).status_code == 403
    assert _patch(viewer, {"colour_code": "Black"}).status_code == 403
    assert _audits() == []


# ── Files ─────────────────────────────────────────────────────────────────────


def test_design_size_chart_and_pattern_files(owner, staff, viewer, store):
    url = "/api/prod/library/111/files"
    ai = b"%!PS-Adobe-3.0 AI design"
    design = staff.post(url, files={"file": ("logo.ai", ai, "application/postscript")}, data={"kind": "design"})
    assert design.status_code == 201, design.text
    design = design.json()["file"]
    assert design["name"] == "logo.ai" and design["mime_type"] == "application/octet-stream"
    assert design["size_bytes"] == len(ai) and design["uploaded_by"] == "QC Manager"
    assert design["url"] == f"/api/prod/library-files/{design['id']}"
    assert set(design) == {"id", "name", "mime_type", "size_bytes", "created_at", "uploaded_by", "url"}

    photo = staff.post(url, files={"file": ("front.png", PNG, "image/png")}, data={"kind": "design"}).json()["file"]
    chart = owner.post(url, files={"file": ("sizes.pdf", b"%PDF-1.7 ...", "application/pdf")}, data={"kind": "size_chart"})
    assert chart.status_code == 201 and chart.json()["file"]["mime_type"] == "application/pdf"
    pattern = staff.post(url, files={"file": ("p.dxf", b"0\nSECTION\n", "application/dxf")}, data={"kind": "pattern"})
    assert pattern.status_code == 201

    keys = list(store.files)
    assert len(keys) == 4 and all(key.startswith("production/library/111/") for key in keys)

    files = _product(viewer)["files"]
    assert [f["id"] for f in files["design"]] == [photo["id"], design["id"]]  # newest first
    assert [f["id"] for f in files["size_chart"]] == [chart.json()["file"]["id"]]
    assert [f["id"] for f in files["pattern"]] == [pattern.json()["file"]["id"]]
    assert _rows(viewer)["111"]["filled"] == {"details": False, "cogs": False, "design": True, "size_chart": True}

    # Downloads: a photo or PDF inline, anything else an attachment.
    served = viewer.get(design["url"])
    assert served.status_code == 200 and served.content == ai
    assert served.headers["content-disposition"].startswith('attachment; filename="logo.ai"')
    assert served.headers["x-content-type-options"] == "nosniff"
    assert viewer.get(photo["url"]).headers["content-disposition"] == "inline"
    assert viewer.get(chart.json()["file"]["url"]).headers["content-disposition"] == "inline"

    # The viewer may not add or remove; staff may remove.
    assert viewer.post(url, files={"file": ("x.png", PNG, "image/png")}, data={"kind": "design"}).status_code == 403
    assert viewer.delete(design["url"]).status_code == 403
    removed = staff.delete(design["url"])
    assert removed.status_code == 200 and removed.json() == {"deleted": design["id"]}
    assert [f["id"] for f in _product(viewer)["files"]["design"]] == [photo["id"]]
    assert viewer.get(design["url"]).status_code == 404
    assert staff.delete(design["url"]).status_code == 404

    actions = [(e.action, e.after_json["summary"]) for e in _audits()]
    assert ("production.library_file_added", "Added logo.ai as the design file of Oversized hoodie") in actions
    assert ("production.library_file_removed", "Removed logo.ai from Oversized hoodie") in actions


def test_a_file_needs_a_kind_and_a_size_chart_must_be_a_photo_or_pdf(owner, staff, store):
    url = "/api/prod/library/111/files"
    for data in ({}, {"kind": "nonsense"}, {"kind": ""}):
        refused = staff.post(url, files={"file": ("x.png", PNG, "image/png")}, data=data)
        assert refused.status_code == 422 and "design, a size chart or a pattern" in refused.json()["detail"]
    refused = staff.post(url, files={"file": ("s.xlsx", b"PK\x03\x04 sheet", "application/zip")}, data={"kind": "size_chart"})
    assert refused.status_code == 422 and refused.json()["detail"] == "Use a JPG, PNG, WebP or GIF photo, or a PDF."
    empty = staff.post(url, files={"file": ("e.png", b"", "image/png")}, data={"kind": "design"})
    assert empty.status_code == 422 and empty.json()["detail"] == "Choose a file to upload."
    assert store.files == {}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_library_file")).scalar_one() == 0


def test_a_file_over_20_mb_is_refused(owner, store, monkeypatch):
    monkeypatch.setattr(library_service, "MAX_BYTES", 10)
    refused = owner.post(
        "/api/prod/library/111/files", files={"file": ("big.png", PNG, "image/png")}, data={"kind": "design"}
    )
    assert refused.status_code == 422 and "20 MB" in refused.json()["detail"]
    assert store.files == {}


# ── A new order starts from the Library ───────────────────────────────────────


def test_a_new_order_takes_the_library_details_it_leaves_out(owner):
    _patch(
        owner,
        {
            "colour_code": "Pantone 19-0303",
            "fabric_type": "Cotton fleece 320 gsm",
            "decoration_type": "DTF print",
            "decoration_width_cm": 12.5,
            **COGS,
        },
    )
    order = _new(owner)
    assert order["product"]["colour_code"] == "Pantone 19-0303"
    assert order["product"]["fabric_type"] == "Cotton fleece 320 gsm"
    assert order["product"]["decoration_type"] == "DTF print"
    assert order["product"]["decoration_width_cm"] == "12.5"

    explicit = _new(owner, colour_code="#000000", decoration_width_cm=3, fabric_type="")
    assert explicit["product"]["colour_code"] == "#000000"
    assert explicit["product"]["decoration_width_cm"] == "3.0"
    assert explicit["product"]["fabric_type"] == "Cotton fleece 320 gsm"  # blank is left out
    assert explicit["product"]["decoration_type"] == "DTF print"

    # The order's details are its own: changing the Library leaves it alone.
    _patch(owner, {"colour_code": "Olive"})
    assert owner.get(f"/api/prod/orders/{order['id']}").json()["order"]["product"]["colour_code"] == "Pantone 19-0303"


def test_a_new_order_does_not_take_the_library_cogs(owner):
    _patch(owner, {"cogs_fabric_piastres": 99_999})
    order = _new(owner, target_fabric_piastres=0)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT target_fabric_piastres FROM prod_order WHERE id = :id"), {"id": order["id"]}
        ).scalar_one() == 0


def test_a_new_order_without_a_library_record_is_as_before(owner):
    _patch(owner, {"colour_code": "Olive"}, pid="222")  # another product's record
    order = _new(owner)
    assert [order["product"][k] for k in ("colour_code", "fabric_type", "decoration_type", "decoration_width_cm")] == [
        None, None, None, None,
    ]
    plain = _new(owner, shopify_product_id=None)
    assert plain["product"]["colour_code"] is None


# ── The migration ─────────────────────────────────────────────────────────────


def _version() -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_the_migration_goes_down_and_up_cleanly_when_empty(fresh_database):
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    try:
        command.downgrade(config, "f1c2d3e40039")
        assert _version() == "f1c2d3e40039"
        with engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('prod_library_item')")).scalar_one() is None
            assert connection.execute(text("SELECT to_regclass('prod_library_file')")).scalar_one() is None
    finally:
        command.upgrade(config, "head")
    assert _version() == alembic_head()


def test_the_downgrade_refuses_while_a_library_record_exists(owner):
    from alembic import command
    from alembic.config import Config

    assert _patch(owner, {"colour_code": "Black"}).status_code == 200
    with pytest.raises(RuntimeError, match="Library record"):
        command.downgrade(Config("alembic.ini"), "f1c2d3e40039")
    assert _version() == alembic_head()
