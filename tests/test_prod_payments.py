"""Production's Payments (build plan 2026-11-19, section 3): every payment to
every supplier, filtered by date, each with several photos. **Money: the
owner's alone.** Every name and figure here is invented."""

import pytest
from sqlalchemy import select, text

from app.db import SessionLocal, engine
from app.modules.production.orders.services import suppliers as supplier_service
from app.shared.models.audit import AuditEvent
from tests.test_prod_orders import (  # noqa: F401  (fixtures)
    PNG,
    TODAY,
    _Bucket,
    _day,
    _person,
    owner,
    staff,
    viewer,
)

PDF = b"%PDF-1.7 ..."
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 30


@pytest.fixture()
def bucket(monkeypatch):
    store = _Bucket()
    monkeypatch.setattr(supplier_service, "file_bucket", lambda: store)
    monkeypatch.setattr("app.modules.production.orders.suppliers_api.file_bucket", lambda: store)
    return store


def _pay(client, supplier: str, amount: int, paid_on: str, **over) -> int:
    body = {"amount_piastres": amount, "method": "cash", "kind": "weekly", "paid_on": paid_on, **over}
    response = client.post(f"/api/prod/suppliers/{supplier}/payments", json=body)
    assert response.status_code == 201, response.text
    return response.json()["entry_id"]


def _payments(client, query: str = "") -> dict:
    response = client.get("/api/prod/payments" + query)
    assert response.status_code == 200, response.text
    return response.json()


def _photo(client, entry: int, content: bytes = PNG, name: str = "slip.png"):
    return client.post(f"/api/prod/entries/{entry}/photos", files={"file": (name, content, "image/png")})


def _supplier_summaries(supplier: str) -> list[str]:
    with SessionLocal() as db:
        return [
            (e.after_json or {}).get("summary")
            for e in db.scalars(
                select(AuditEvent).where(AuditEvent.subject == f"production:supplier:{supplier}").order_by(AuditEvent.id)
            )
        ]


# ── The list ──────────────────────────────────────────────────────────────────


def test_the_list_is_newest_first_with_reversed_ones_marked_and_left_out_of_the_total(owner):
    a = _pay(owner, "fac", 50_000, _day(-2), note="Week 46", method="bank_transfer")
    b = _pay(owner, "prt", 30_000, _day(-10), kind="deposit")
    c = _pay(owner, "fac", 20_000, _day(0), kind="final", method="instapay")
    assert owner.post(f"/api/prod/entries/{c}/reverse", json={"reason": "Typed in wrongly"}).status_code == 200

    listed = _payments(owner)
    assert listed["from"] is None and listed["to"] is None
    assert [p["id"] for p in listed["payments"]] == [c, a, b]  # the reversal line itself is not listed
    assert listed["total_piastres"] == 80_000
    first = listed["payments"][1]
    assert first == {
        "id": a,
        "supplier": {"id": "fac", "name": "Main factory"},
        "amount_piastres": 50_000,
        "paid_on": _day(-2),
        "method": "bank_transfer",
        "method_label": "Bank transfer",
        "kind": "weekly",
        "kind_label": "Weekly payment",
        "note": "Week 46",
        "reversed": False,
        "created_by": "Owner",
        "photos": [],
    }
    assert listed["payments"][0]["reversed"] is True and listed["payments"][2]["kind_label"] == "Deposit"
    assert {"id": "fac", "name": "Main factory"} in listed["suppliers"]
    assert {"id": "prt", "name": "Print house A"} in listed["suppliers"]


def test_the_list_is_filtered_by_date_inclusive_and_by_supplier(owner):
    a = _pay(owner, "fac", 50_000, _day(-2))
    b = _pay(owner, "prt", 30_000, _day(-10))
    c = _pay(owner, "fac", 20_000, _day(-5))

    ranged = _payments(owner, f"?from={_day(-5)}&to={_day(-2)}")
    assert ranged["from"] == _day(-5) and ranged["to"] == _day(-2)
    assert [p["id"] for p in ranged["payments"]] == [a, c] and ranged["total_piastres"] == 70_000
    assert [p["id"] for p in _payments(owner, f"?from={_day(-4)}")["payments"]] == [a]
    assert [p["id"] for p in _payments(owner, f"?to={_day(-6)}")["payments"]] == [b]
    by_supplier = _payments(owner, "?supplier=prt")
    assert [p["id"] for p in by_supplier["payments"]] == [b] and by_supplier["total_piastres"] == 30_000
    empty = _payments(owner, f"?from={_day(1)}")
    assert empty["payments"] == [] and empty["total_piastres"] == 0

    refused = owner.get(f"/api/prod/payments?from={_day(0)}&to={_day(-1)}")
    assert refused.status_code == 422 and "after the To date" in refused.json()["detail"]
    assert owner.get("/api/prod/payments?from=yesterday").status_code == 422


# ── Photos ────────────────────────────────────────────────────────────────────


def test_a_payment_holds_several_photos_added_served_and_removed_one_by_one(owner, bucket):
    entry = _pay(owner, "fac", 50_000, _day(-1))
    first = _photo(owner, entry)
    assert first.status_code == 201, first.text
    assert len(first.json()["payment"]["photos"]) == 1
    second = _photo(owner, entry, PDF, "slip.pdf").json()["payment"]
    photos = second["photos"]
    assert [p["mime_type"] for p in photos] == ["image/png", "application/pdf"]
    assert photos[1] == {
        "id": photos[1]["id"], "mime_type": "application/pdf", "size_bytes": len(PDF),
        "created_at": photos[1]["created_at"], "url": f"/api/prod/receipts/{photos[1]['id']}",
    }
    assert [p["id"] for p in _payments(owner)["payments"][0]["photos"]] == [p["id"] for p in photos]
    assert all(key.startswith("production/suppliers/fac/") for key in bucket.files) and len(bucket.files) == 2

    served = owner.get(photos[0]["url"])
    assert served.status_code == 200 and served.content == PNG
    assert served.headers["content-disposition"] == "inline"
    assert served.headers["x-content-type-options"] == "nosniff"
    # The old single-receipt route serves the newest; the account line shows one.
    assert owner.get(f"/api/prod/entries/{entry}/receipt").content == PDF
    line = next(l for l in owner.get("/api/prod/suppliers/fac").json()["supplier"]["account"] if l["id"] == entry)
    assert line["receipt"] is not None and line["receipt"]["mime_type"] == "application/pdf"

    removed = owner.delete(photos[0]["url"])
    assert removed.status_code == 200 and [p["id"] for p in removed.json()["payment"]["photos"]] == [photos[1]["id"]]
    assert owner.get(photos[0]["url"]).status_code == 404
    assert owner.delete(photos[0]["url"]).status_code == 404
    assert owner.get("/api/prod/receipts/99999").status_code == 404

    summaries = _supplier_summaries("fac")
    assert summaries.count("Added a photo of a payment to Main factory") == 2
    assert "Removed a photo of a payment to Main factory" in summaries
    assert not any(ch.isdigit() for s in summaries for ch in s)  # words, never an amount


def test_the_old_receipt_route_replaces_and_removes_every_live_photo(owner, bucket):
    entry = _pay(owner, "fac", 50_000, _day(-1))
    _photo(owner, entry)
    _photo(owner, entry, JPG, "b.jpg")
    replaced = owner.post(f"/api/prod/entries/{entry}/receipt", files={"file": ("c.pdf", PDF, "application/pdf")})
    assert replaced.status_code == 201
    live = _payments(owner)["payments"][0]["photos"]
    assert [p["mime_type"] for p in live] == ["application/pdf"]
    _photo(owner, entry)
    assert len(_payments(owner)["payments"][0]["photos"]) == 2
    assert owner.delete(f"/api/prod/entries/{entry}/receipt").status_code == 200
    assert _payments(owner)["payments"][0]["photos"] == []
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM prod_supplier_receipt WHERE deleted_at IS NULL")).scalar_one() == 0
    assert len(bucket.files) == 4  # the copies stay in the bucket


def test_a_photo_goes_on_a_live_payment_and_is_checked_before_it_is_stored(owner, bucket):
    entry = _pay(owner, "fac", 50_000, _day(-1))
    assert _photo(owner, entry, b"hello", "a.txt").status_code == 422
    assert _photo(owner, entry, b"", "a.png").status_code == 422
    assert _photo(owner, 99999).status_code == 404
    opening = owner.post("/api/prod/suppliers/prt/opening", json={"amount_piastres": 1000}).json()["entry_id"]
    refused = _photo(owner, opening)
    assert refused.status_code == 422 and "payment" in refused.json()["detail"]
    reversal = owner.post(f"/api/prod/entries/{entry}/reverse", json={"reason": "Wrong"}).json()["entry_id"]
    assert _photo(owner, entry).status_code == 422  # reversed
    assert _photo(owner, reversal).status_code == 422  # a reversal is no payment
    assert bucket.files == {}


# ── Who may ───────────────────────────────────────────────────────────────────


def test_everybody_without_the_owner_permission_is_refused_every_payment_route(owner, staff, viewer, bucket):
    entry = _pay(owner, "fac", 50_000, _day(-1))
    photo = _photo(owner, entry).json()["payment"]["photos"][0]
    manager_less = [staff, viewer, _person("cs@example.com", "customer_service")]
    for person in manager_less:
        assert person.get("/api/prod/payments").status_code == 403
        assert person.get(f"/api/prod/payments?from={_day(-3)}").status_code == 403
        assert _photo(person, entry).status_code == 403
        assert person.get(photo["url"]).status_code == 403
        assert person.delete(photo["url"]).status_code == 403
    # The production manager holds all of Production, money included (ADR 0086).
    manager = _person("pm@example.com", "production_manager", name="PM")
    assert manager.get("/api/prod/payments").status_code == 200
    assert len(bucket.files) == 1


# ── The migration ─────────────────────────────────────────────────────────────


def test_the_downgrade_refuses_while_a_payment_holds_more_than_one_photo(owner, bucket):
    from alembic import command
    from alembic.config import Config

    entry = _pay(owner, "fac", 50_000, _day(-1))
    _photo(owner, entry)
    _photo(owner, entry)
    with pytest.raises(RuntimeError, match="more than one photo"):
        command.downgrade(Config("alembic.ini"), "e5b9a3d70038")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "a7c3e9d10040"
