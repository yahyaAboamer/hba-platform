"""Production's Billing under /api/prod (ADR 0089).

A bill is a purchase on its supplier's account; Billing lists every one, with
the photos of its receipt, the total of those not voided and that total per
part. It is the owner's alone.

Every name and figure here is invented.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.modules.production.orders.models import ProdPurchase, ProdPurchasePhoto
from app.modules.production.orders.services import billing as billing_service
from app.shared.models.audit import AuditEvent
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    PNG,
    TODAY,
    _Bucket,
    _new,
    staff,
    viewer,
)
from tests.test_prod_suppliers import (  # noqa: F401  (fixtures)
    _buy,
    _make,
    manager,
    owner,
)

PDF = b"%PDF-1.4\n" + b"\x00" * 40


@pytest.fixture()
def bucket(monkeypatch):
    store = _Bucket()
    monkeypatch.setattr(billing_service, "file_bucket", lambda: store)
    monkeypatch.setattr("app.modules.production.orders.fabric_api.file_bucket", lambda: store)
    return store


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _bills(client, **params) -> dict:
    response = client.get("/api/prod/billing", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _pid(item: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(ProdPurchase.id).where(ProdPurchase.item == item).order_by(ProdPurchase.id.desc()))


def _setting(owner) -> dict:
    """Two suppliers, four bills over three days, one voided, one for an order
    and one filling fabric storage."""
    mill = _make(owner, "Knit mill")["id"]
    trims = _make(owner, "Trims house")["id"]
    oid = _new(owner)["id"]
    _buy(owner, mill, item="Fleece", quantity=100, unit_price_piastres=16000, bought_on=_day(-10),
         new_fabric={"name": "Heavy fleece"})  # 1,600,000 fabric
    _buy(owner, trims, item="Zips", quantity=500, unit="piece", unit_price_piastres=150, part="accessories",
         bought_on=_day(-5), order_id=oid)  # 75,000 accessories
    _buy(owner, trims, item="Bags", quantity=1000, unit="piece", unit_price_piastres=40, part="packaging",
         bought_on=_day(-1))  # 40,000 packaging
    _buy(owner, mill, item="Rib", quantity=10, unit="m", unit_price_piastres=2000, bought_on=_day(-1))  # 20,000
    rib = _pid("Rib")
    assert owner.post(f"/api/prod/purchases/{rib}/void", json={"reason": "Never came"}).status_code == 200
    return {"mill": mill, "trims": trims, "order": oid, "rib": rib}


def test_billing_lists_every_purchase_newest_first_with_its_totals(owner):
    s = _setting(owner)
    body = _bills(owner)
    assert [b["item"] for b in body["bills"]] == ["Rib", "Bags", "Zips", "Fleece"]
    assert body["total_piastres"] == 1_600_000 + 75_000 + 40_000
    assert body["by_part"] == {"fabric": 1_600_000, "printing": 0, "accessories": 75_000, "packaging": 40_000, "other": 0}
    assert body["suppliers"] == [{"id": s["mill"], "name": "Knit mill"}, {"id": s["trims"], "name": "Trims house"}]

    rib, bags, zips, fleece = body["bills"]
    assert (rib["voided"], rib["void_reason"], rib["total_piastres"]) == (True, "Never came", 20_000)
    assert zips["order"]["id"] == s["order"] and zips["order"]["code"].startswith("PO-")
    assert zips == {
        **zips,
        "supplier": {"id": s["trims"], "name": "Trims house"},
        "quantity": "500",
        "unit": "piece",
        "unit_price_piastres": 150,
        "total_piastres": 75_000,
        "part": "accessories",
        "bought_on": _day(-5),
        "expected_on": None,
        "received_on": None,
        "note": None,
        "voided": False,
        "void_reason": None,
        "fabric": None,
        "photos": [],
        "created_by": "Owner",
    }
    assert fleece["fabric"]["name"] == "Heavy fleece" and fleece["quantity"] == "100"
    assert bags["order"] is None


def test_billing_filters_by_day_supplier_and_part(owner):
    s = _setting(owner)
    assert [b["item"] for b in _bills(owner, **{"from": _day(-5), "to": _day(-1)})["bills"]] == ["Rib", "Bags", "Zips"]
    assert [b["item"] for b in _bills(owner, to=_day(-5))["bills"]] == ["Zips", "Fleece"]
    only = _bills(owner, supplier=s["mill"])
    assert [b["item"] for b in only["bills"]] == ["Rib", "Fleece"]
    assert only["total_piastres"] == 1_600_000
    # Every supplier with a purchase is still offered, whatever the filter.
    assert len(only["suppliers"]) == 2
    parts = _bills(owner, part="accessories")
    assert [b["item"] for b in parts["bills"]] == ["Zips"]
    assert parts["by_part"]["accessories"] == 75_000 and parts["by_part"]["fabric"] == 0
    assert _bills(owner, part="", supplier="")["total_piastres"] == 1_715_000

    response = owner.get("/api/prod/billing", params={"part": "gold"})
    assert response.status_code == 422
    response = owner.get("/api/prod/billing", params={"from": _day(-1), "to": _day(-5)})
    assert response.status_code == 422 and "Swap them" in response.json()["detail"]


def test_billing_is_the_owners_alone(owner, staff, viewer, manager):
    for client in (staff, viewer):
        assert client.get("/api/prod/billing").status_code == 403
    # The production manager holds all of Production, its money included (ADR 0086).
    assert manager.get("/api/prod/billing").status_code == 200


def test_a_bill_carries_photos_and_pdfs_of_its_receipt(owner, staff, bucket):
    _setting(owner)
    pid = _pid("Zips")
    url = f"/api/prod/purchases/{pid}/photos"
    first = owner.post(url, files={"file": ("bill.png", PNG, "image/png")})
    assert first.status_code == 201, first.text
    photo = first.json()["photo"]
    assert photo["mime_type"] == "image/png" and photo["url"] == f"/api/prod/bill-photos/{photo['id']}"
    second = owner.post(url, files={"file": ("bill.pdf", PDF, "application/pdf")}).json()["photo"]
    assert second["mime_type"] == "application/pdf"
    assert len(bucket.files) == 2 and all(key.startswith(f"production/bills/{pid}/") for key in bucket.files)

    bill = next(b for b in _bills(owner)["bills"] if b["id"] == pid)
    assert [p["id"] for p in bill["photos"]] == [second["id"], photo["id"]]

    served = owner.get(photo["url"])
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["content-disposition"] == "inline"
    assert served.headers["x-content-type-options"] == "nosniff"

    # The QC manager neither adds, sees nor removes a bill's photo.
    assert staff.post(url, files={"file": ("bill.png", PNG, "image/png")}).status_code == 403
    assert staff.get(photo["url"]).status_code == 403
    assert staff.delete(photo["url"]).status_code == 403

    assert owner.delete(photo["url"]).json() == {"deleted": photo["id"]}
    assert owner.get(photo["url"]).status_code == 404
    assert owner.delete(photo["url"]).status_code == 404
    bill = next(b for b in _bills(owner)["bills"] if b["id"] == pid)
    assert [p["id"] for p in bill["photos"]] == [second["id"]]
    with SessionLocal() as db:
        actions = list(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("production.bill_photo_%"))))
    assert sorted(actions) == ["production.bill_photo_added", "production.bill_photo_added", "production.bill_photo_removed"]


def test_a_bill_photo_is_refused_on_a_voided_bill_and_when_not_a_photo(owner, bucket):
    s = _setting(owner)
    url = f"/api/prod/purchases/{s['rib']}/photos"
    response = owner.post(url, files={"file": ("bill.png", PNG, "image/png")})
    assert response.status_code == 422 and response.json()["detail"] == "This bill was voided."
    good = f"/api/prod/purchases/{_pid('Bags')}/photos"
    assert owner.post(good, files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 422
    assert owner.post(good, files={"file": ("x.png", b"", "image/png")}).status_code == 422
    assert owner.post("/api/prod/purchases/999999/photos", files={"file": ("x.png", PNG, "image/png")}).status_code == 404
    assert owner.get("/api/prod/bill-photos/999999").status_code == 404
    assert bucket.files == {}
    with SessionLocal() as db:
        assert db.query(ProdPurchasePhoto).count() == 0
