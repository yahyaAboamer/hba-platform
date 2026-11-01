"""Khazenly's bulk-confirm file, from its Active Orders export (ADR 0071).

Every export here is synthetic (``tests.support_khazenly``): a real one holds
customer names. Shopify is never called; ``ops_shopify_order`` is written
directly, as the poller would.
"""

import base64
import io
import zipfile
from datetime import datetime, timedelta, timezone

import openpyxl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.businesstime import utcnow
from app.main import app
from app.modules.operations.models import OpsShopifyOrder
from app.modules.operations.services import khazenly
from app.modules.operations.services.freshness import record_failure, record_not_connected, record_success
from app.shared.models.audit import AuditEvent
from tests.support_khazenly import export, footer, order_row, rows_for, workbook


def _kh(number: int) -> str:
    return f"KH-HBA-{8_800_000 + number:08d}"


def _store(db, number: int, tags: list[str], fulfillment: str = "UNFULFILLED") -> None:
    db.add(
        OpsShopifyOrder(
            shopify_order_id=str(6_000_000 + number),
            order_number=f"#{number}",
            placed_at=utcnow() - timedelta(hours=3),
            tags=tags,
            fulfillment_status=fulfillment,
            seen_at=utcnow(),
        )
    )
    db.flush()


def _orders_sheet(content: bytes) -> list[tuple]:
    workbook_ = openpyxl.load_workbook(io.BytesIO(content))
    return list(workbook_["Orders"].iter_rows(values_only=True))


# ── Reading the export ────────────────────────────────────────────────────────


def test_the_header_is_found_by_its_text_under_any_filter_lines():
    many = [f"Filter line {n}" for n in range(9)]
    for filters in ([], many):
        found = khazenly.read_export("a.xlsx", export([(_kh(1), "31840")], filters=filters))
        assert found.orders == [khazenly.ExportOrder(_kh(1), "31840")]


def test_the_header_is_found_in_any_column():
    rows = rows_for([(_kh(1), "31840")])
    shifted = [[None, None, *row] for row in rows]
    found = khazenly.read_export("a.xlsx", workbook(shifted))
    assert found.orders == [khazenly.ExportOrder(_kh(1), "31840")]


def test_the_footer_is_skipped_and_its_count_kept():
    found = khazenly.read_export("a.xlsx", export([(_kh(1), "31840"), (_kh(2), "31841")]))
    assert [order.sales_order for order in found.orders] == [_kh(1), _kh(2)]
    assert found.stated_count == 2


def test_blank_and_footer_rows_between_groups_do_not_end_the_read():
    rows = rows_for([(_kh(1), "31840")], count=3)
    # A second group after the first one's footer, and a blank row.
    index = rows.index(footer(3)[0])
    rows[index:index] = [[], *footer(1)[:2], order_row(_kh(2), "31841", first=True), order_row(_kh(3), "31842")]
    found = khazenly.read_export("a.xlsx", workbook(rows))
    assert [order.sales_order for order in found.orders] == [_kh(1), _kh(2), _kh(3)]


def test_a_row_whose_sales_order_is_not_khazenlys_is_not_an_order_but_is_counted():
    rows = rows_for([(_kh(1), "31840")])
    rows.insert(rows.index(footer(1)[0]), order_row("Note: re-check", "31841"))
    found = khazenly.read_export("a.xlsx", workbook(rows))
    assert [order.sales_order for order in found.orders] == [_kh(1)]
    assert found.skipped == 1


def test_a_damaged_sheet_is_refused_in_words():
    good = export([(_kh(1), "31840")])
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(good)) as source, zipfile.ZipFile(buffer, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                # Cut inside the rows: openpyxl opens the workbook and
                # fails only when it reads the sheet.
                data = data[:-40]
            target.writestr(info, data)
    with pytest.raises(khazenly.ExportRefused, match="Download the export from Khazenly again"):
        khazenly.read_export("a.xlsx", buffer.getvalue())


def test_a_merchant_number_written_as_a_number_reads_the_same():
    found = khazenly.read_export("a.xlsx", export([(_kh(1), 31840.0)]))
    assert found.orders[0].merchant_order == "31840"


def test_the_recipient_name_is_never_read():
    found = khazenly.read_export("a.xlsx", export([(_kh(1), "31840")]))
    assert "Test Customer" not in repr(found)


@pytest.mark.parametrize(
    ("filename", "content", "words"),
    [
        pytest.param("orders.csv", export([(_kh(1), "1")]), ".xlsx", id="not-xlsx"),
        pytest.param("orders.xlsx", b"not a workbook", "isn't a workbook", id="not-a-workbook"),
        pytest.param("orders.xlsx", b"PK" + b"\0" * khazenly.MAX_UPLOAD_BYTES, "The limit is 5 MB", id="too-big"),
        pytest.param(
            "orders.xlsx",
            workbook([[None, "Merchant Order Number"], [None, "31840"]]),
            "Couldn't find",
            id="no-sales-order-header",
        ),
        pytest.param("orders.xlsx", export([]), "no orders", id="no-orders"),
        pytest.param(
            "orders.xlsx",
            export([(_kh(1), "31840"), (_kh(1), "31841")]),
            f"{_kh(1)} is in the file twice",
            id="sales-order-twice",
        ),
        pytest.param(
            "orders.xlsx",
            export([(_kh(1), "31840"), (_kh(2), "31840")]),
            "31840 is in the file twice",
            id="merchant-order-twice",
        ),
        pytest.param(
            "orders.xlsx", export([(_kh(1), "31840")], count=5), "says it lists 5 orders", id="count-differs"
        ),
        pytest.param(
            "orders.xlsx", export([("KH-HBA 08863368", "31840")]), "isn't a Khazenly sales order", id="odd-number"
        ),
    ],
)
def test_a_file_that_cannot_be_trusted_is_refused_in_words(filename, content, words):
    with pytest.raises(khazenly.ExportRefused) as refused:
        khazenly.read_export(filename, content)
    assert words in str(refused.value)


def test_a_workbook_that_unpacks_huge_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr("xl/workbook.xml", b"<" + b" " * (khazenly.MAX_UNPACKED_BYTES + 1))
    with pytest.raises(khazenly.ExportRefused, match="far larger inside"):
        khazenly.read_export("a.xlsx", buffer.getvalue())


# ── The rule ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tags", "fulfillment", "reason"),
    [
        (["Confirmed ✅"], "UNFULFILLED", None),
        (["Confirmed✅"], "UNFULFILLED", None),
        (["confirmed ✅"], None, None),
        (["Confirmed✅", "Paid 💳"], "UNFULFILLED", None),
        # Compression no longer needs a call (owner, 30 October).
        (["Confirmed ✅", "compression"], "UNFULFILLED", None),
        (["Cancelled ❌"], "UNFULFILLED", "cancelled"),
        (["WA Sent 📤"], "UNFULFILLED", "wa_sent"),
        (["No WhatsApp 📵"], "UNFULFILLED", "no_whatsapp"),
        (["Edit ✏️"], "UNFULFILLED", "edit"),
        (["Awaiting payment 💳"], "UNFULFILLED", "awaiting_payment"),
        (["compression", "Call Confirmed📞"], "UNFULFILLED", "no_tag"),
        ([], "UNFULFILLED", "no_tag"),
        # The safety exclusions.
        (["Confirmed ✅", "Cancelled ❌"], "UNFULFILLED", "confirmed_but_cancelled"),
        (["Confirmed ✅"], "PARTIALLY_FULFILLED", "confirmed_but_shipped"),
        (["Confirmed ✅"], "FULFILLED", "confirmed_but_shipped"),
    ],
)
def test_only_a_confirmed_open_unshipped_order_goes_in(tags, fulfillment, reason):
    assert khazenly.reason_for(tags, fulfillment) == reason


def test_numbers_match_with_or_without_the_hash():
    assert khazenly.normalise("#31840") == khazenly.normalise("31840") == "31840"
    assert khazenly.normalise(" # 31840 ") == "31840"


def test_each_order_is_decided_against_shopify(db):
    _store(db, 31840, ["Confirmed ✅"])
    _store(db, 31841, ["Confirmed✅", "compression"])
    _store(db, 31842, ["WA Sent 📤"])
    _store(db, 31843, ["Confirmed ✅", "Cancelled ❌"])
    orders = [
        khazenly.ExportOrder(_kh(1), "31840"),
        khazenly.ExportOrder(_kh(2), "31841"),
        khazenly.ExportOrder(_kh(3), "31842"),
        khazenly.ExportOrder(_kh(4), "31843"),
        # Cancelled, closed or shipped: not in the table at all (#31874).
        khazenly.ExportOrder(_kh(5), "31874"),
        khazenly.ExportOrder(_kh(6), ""),
    ]

    decision = khazenly.decide(db, orders)

    assert decision.confirmed == [_kh(1), _kh(2)]
    assert decision.left_out == {
        "wa_sent": [{"sales_order": _kh(3), "order_number": "#31842"}],
        "confirmed_but_cancelled": [{"sales_order": _kh(4), "order_number": "#31843"}],
        "not_open": [{"sales_order": _kh(5), "order_number": "#31874"}],
        "no_number": [{"sales_order": _kh(6), "order_number": None}],
    }


# ── The file ──────────────────────────────────────────────────────────────────


def test_the_file_holds_only_true_rows_with_khazenly_numbers():
    content = khazenly.fill_template([_kh(1), _kh(2), _kh(3)])

    assert _orders_sheet(content) == [
        ("Sales Order Number", "Confirmed"),
        (_kh(1), "True"),
        (_kh(2), "True"),
        (_kh(3), "True"),
    ]


def test_column_b_is_text_and_every_other_part_is_khazenlys_own():
    content = khazenly.fill_template([_kh(1)])

    sheet = openpyxl.load_workbook(io.BytesIO(content))["Orders"]
    assert sheet["B2"].number_format == "@"
    assert sheet["B2"].data_type == "s"

    template = zipfile.ZipFile(khazenly.TEMPLATE)
    filled = zipfile.ZipFile(io.BytesIO(content))
    assert filled.namelist() == template.namelist()
    for name in template.namelist():
        if name not in (khazenly.ORDERS_SHEET, khazenly.SHARED_STRINGS):
            assert filled.read(name) == template.read(name), name


def test_the_user_guide_and_its_picture_are_untouched():
    content = khazenly.fill_template([_kh(1)])

    filled = openpyxl.load_workbook(io.BytesIO(content))
    blank = openpyxl.load_workbook(khazenly.TEMPLATE)
    assert filled.sheetnames == ["User Guide", "Orders"]
    assert list(filled["User Guide"].values) == list(blank["User Guide"].values)
    assert zipfile.ZipFile(io.BytesIO(content)).read("xl/media/image1.png") == zipfile.ZipFile(
        khazenly.TEMPLATE
    ).read("xl/media/image1.png")


def test_the_template_is_still_the_one_the_writer_expects():
    """If Khazenly sends a new template, this says so before a file does."""
    blank = openpyxl.load_workbook(khazenly.TEMPLATE)
    assert list(blank["Orders"].values) == [("Sales Order Number", "Confirmed")]
    package = zipfile.ZipFile(khazenly.TEMPLATE)
    assert b'<sheet name="Orders" sheetId="1" r:id="rId2"/>' in package.read("xl/workbook.xml")
    assert b'Target="worksheets/sheet2.xml"' in package.read("xl/_rels/workbook.xml.rels")


def test_the_file_is_named_in_cairo_time():
    at = datetime(2026, 10, 30, 20, 45, tzinfo=timezone.utc)
    assert khazenly.file_name(at) == "khazenly-bulk-confirm-2026-10-30-2245.xlsx"


# ── Through the API ───────────────────────────────────────────────────────────

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _committed(write) -> None:
    from app.db import SessionLocal

    with SessionLocal() as session:
        write(session)
        session.commit()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _upload(client, content: bytes, name: str = "Dashboard - Active Orders.xlsx"):
    return client.post("/api/order-ops/khazenly", files={"file": (name, content, XLSX)})


def _shop(*orders, at=None):
    def write(session):
        for number, tags in orders:
            _store(session, number, tags)
        record_success(session, "shopify", len(orders), at=at)

    _committed(write)


def test_the_tab_shows_how_fresh_shopifys_tags_are(client):
    assert client.get("/api/order-ops/khazenly").json()["freshness"]["state"] == "never"
    _shop((31840, ["Confirmed ✅"]))
    assert client.get("/api/order-ops/khazenly").json()["freshness"]["state"] == "fresh"


def test_an_export_comes_back_as_khazenlys_file_with_a_summary(client):
    _shop(
        (31840, ["Confirmed ✅"]),
        (31841, ["Confirmed✅", "compression"]),
        (31842, ["Edit ✏️"]),
        (31843, ["No WhatsApp 📵"]),
        (31844, ["Cancelled ❌"]),
    )
    upload = export(
        [(_kh(n), str(31840 + n)) for n in range(5)] + [(_kh(9), "31874")]
    )

    response = _upload(client, upload)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows_read"] == 6
    assert body["stated_count"] == 6
    assert body["skipped_rows"] == 0
    assert body["confirmed"] == 2
    assert body["not_confirmed"] == 4
    assert [(group["reason"], group["count"]) for group in body["left_out"]] == [
        ("not_open", 1),
        ("cancelled", 1),
        ("edit", 1),
        ("no_whatsapp", 1),
    ]
    assert body["left_out"][0]["orders"] == [{"sales_order": _kh(9), "order_number": "#31874"}]
    assert body["freshness"]["state"] == "fresh"
    assert body["file"]["name"].startswith("khazenly-bulk-confirm-")
    content = base64.b64decode(body["file"]["content_base64"])
    assert _orders_sheet(content)[1:] == [(_kh(0), "True"), (_kh(1), "True")]


def test_the_answer_carries_no_customer_details(client):
    _shop((31840, ["Confirmed ✅"]), (31841, ["WA Sent 📤"]))
    body = _upload(client, export([(_kh(0), "31840"), (_kh(1), "31841")])).json()
    assert "Test Customer" not in str(body)
    assert set(body["left_out"][0]["orders"][0]) == {"sales_order", "order_number"}


def test_who_built_it_is_audited_with_counts_only(client):
    _shop((31840, ["Confirmed ✅"]), (31841, ["WA Sent 📤"]))
    _upload(client, export([(_kh(0), "31840"), (_kh(1), "31841")]))

    from app.db import SessionLocal

    with SessionLocal() as session:
        event = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "order_ops.khazenly_file_built")
        ).one()
    assert event.actor_email == "owner@example.com"
    assert event.department == "operations"
    assert event.after_json == {"rows_read": 2, "confirmed": 1, "file": True}


def test_nothing_confirmed_offers_no_file(client):
    _shop((31840, ["WA Sent 📤"]))
    body = _upload(client, export([(_kh(0), "31840")])).json()
    assert body["confirmed"] == 0
    assert body["file"] is None


@pytest.mark.parametrize(
    "state",
    ["never", "stale", "failed", "not_connected"],
)
def test_without_fresh_shopify_tags_no_file_is_built(client, state):
    def write(session):
        _store(session, 31840, ["Confirmed ✅"])
        if state == "stale":
            record_success(session, "shopify", 1, at=utcnow() - timedelta(minutes=11))
        elif state == "failed":
            record_success(session, "shopify", 1)
            record_failure(session, "shopify", "Shopify didn't answer.")
        elif state == "not_connected":
            record_success(session, "shopify", 1)
            record_not_connected(session, "shopify")

    _committed(write)

    response = _upload(client, export([(_kh(0), "31840")]))

    assert response.status_code == 409
    assert "no file was built" in response.json()["detail"]


def test_a_refused_file_says_why(client):
    _shop((31840, ["Confirmed ✅"]))
    response = _upload(client, export([(_kh(0), "31840"), (_kh(0), "31841")]))
    assert response.status_code == 422
    assert "twice" in response.json()["detail"]


def test_someone_signed_out_cannot_upload():
    with TestClient(app) as anonymous:
        response = _upload(anonymous, export([(_kh(0), "31840")]))
    assert response.status_code in (401, 403)
