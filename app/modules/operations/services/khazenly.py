"""Khazenly: the bulk-confirm file for orders confirmed in Shopify (ADR 0071).

Khazenly holds every Shopify order on hold until we confirm it. A person
exports *Dashboard - Active Orders* from Khazenly, uploads it here, and gets
back Khazenly's own bulk-confirm template, filled in with the orders whose
Shopify tags say *Confirmed*, each ``True``, to upload to Khazenly.

Three steps, each its own function: ``read_export`` reads Khazenly's file,
``decide`` matches it against ``ops_shopify_order``, ``fill_template`` writes
the answer. ``build`` runs them for the route, and ``keep`` stores the
summary as a run for the tab's history (ADR 0072).

Nothing is written to Shopify or Khazenly, and nothing about the customer is
kept: the upload is read in memory, and only the sales order number and the
merchant order number of each row are ever read - and kept.
"""

import io
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.businesstime import BUSINESS_TIMEZONE, utcnow
from app.modules.operations.models import OpsKhazenlyRun, OpsShopifyOrder
from app.shared.models.identity import UserAccount
from app.modules.operations.services.shopify import (
    CANCELLED,
    CONFIRMED,
    NO_WHATSAPP,
    WA_SENT,
    tag_key,
)

#: The blank template exactly as Khazenly gave it. No customer data in it.
TEMPLATE = Path(__file__).with_name("khazenly_bulk_confirm_template.xlsx")
#: The sheet Khazenly reads, and the strings its cells point to.
ORDERS_SHEET = "xl/worksheets/sheet2.xml"
SHARED_STRINGS = "xl/sharedStrings.xml"
#: The template's own cell style for column B: text (``@``).
TEXT_STYLE = 3
#: Their page: "Confirmed column value should be 'True' or 'False'".
TRUE = "True"

#: A whole export is ~20 KB; this is far more than any day's orders.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
#: An .xlsx is a zip; this bounds what it may unpack to (an export is ~20 KB,
#: and openpyxl holds the unpacked text in memory while it reads).
MAX_UNPACKED_BYTES = 20 * 1024 * 1024
#: A bound on the rows read, so a padded sheet cannot keep the request busy.
MAX_ROWS = 20_000

SALES_ORDER_HEADER = "Sales Order: Sales Order Number"
MERCHANT_ORDER_HEADER = "Merchant Order Number"
ORDER_PREFIX = "KH-"
#: A Khazenly sales order number as it goes into their file, e.g. KH-HBA-08863368.
SALES_ORDER = re.compile(r"KH-[A-Z0-9-]{1,40}")
#: Khazenly's footer: the grand total of orders is in the last ``Count`` row.
COUNT = "count"

EDIT = tag_key("Edit ✏️")
AWAITING_PAYMENT = tag_key("Awaiting payment 💳")
#: Shopify's word for an order shipped, in whole or in part.
SHIPPED = frozenset({"FULFILLED", "PARTIALLY_FULFILLED", "RESTOCKED"})


class ExportRefused(ValueError):
    """The upload was refused, in words a person can act on."""


class NotFresh(RuntimeError):
    """Shopify's tags are not fresh enough to confirm anything with."""


# ── Reading Khazenly's export ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportOrder:
    sales_order: str
    #: Shopify's order number as Khazenly writes it, e.g. "31840". Empty
    #: when Khazenly has none for the row.
    merchant_order: str


@dataclass(frozen=True)
class Export:
    orders: list[ExportOrder]
    #: Khazenly's own grand total, from the footer; None when it has none.
    stated_count: int | None
    #: Rows after the header with a merchant order number but no Khazenly
    #: sales order number: not orders, and said so in the summary.
    skipped: int = 0


def _text(value) -> str:
    """A cell as text: ``31840`` whether Khazenly wrote it as text or a number."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _header_key(value) -> str:
    return " ".join(_text(value).split()).casefold()


def _check_package(filename: str, content: bytes) -> None:
    if not filename.lower().endswith(".xlsx"):
        raise ExportRefused("That isn't an .xlsx file. Upload the Active Orders export from Khazenly as it downloads.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ExportRefused(
            f"That file is {len(content) // 1024} KB. The limit is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB - Khazenly's export is far smaller."
        )
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            unpacked = sum(info.file_size for info in package.infolist())
            names = set(package.namelist())
    except zipfile.BadZipFile:
        raise ExportRefused("That file isn't a workbook Excel can open. Download the export from Khazenly again.") from None
    if unpacked > MAX_UNPACKED_BYTES:
        raise ExportRefused("That workbook is far larger inside than Khazenly's export. Nothing was read.")
    if "xl/workbook.xml" not in names:
        raise ExportRefused("That file isn't a workbook Excel can open. Download the export from Khazenly again.")


def read_export(filename: str, content: bytes) -> Export:
    """Every order in Khazenly's *Active Orders* export.

    The header row is found by its text, not its place: Khazenly's filter
    lines above it change. Blank rows and the Subtotal / Total / Count
    footers are skipped rather than ending the read, because a grouped export
    puts footers between its groups; Khazenly's own grand total is kept to
    check the count against instead.
    """
    _check_package(filename, content)

    import openpyxl

    try:
        with warnings.catch_warnings():
            # Khazenly's workbook has no default style; openpyxl says so.
            warnings.simplefilter("ignore")
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise ExportRefused("That file isn't a workbook Excel can open. Download the export from Khazenly again.") from None

    try:
        for sheet in workbook.worksheets:
            found = _read_sheet(sheet)
            if found is not None:
                return found
    except ExportRefused:
        raise
    except Exception:
        # Read-only sheets are parsed as they are read, so a damaged one
        # fails here rather than when the workbook opens.
        raise ExportRefused("Part of that workbook can't be read. Download the export from Khazenly again.") from None
    finally:
        workbook.close()
    raise ExportRefused(
        f"Couldn't find the \"{SALES_ORDER_HEADER}\" and \"{MERCHANT_ORDER_HEADER}\" "
        "columns. Is this Khazenly's Active Orders export?"
    )


def _read_sheet(sheet) -> Export | None:
    rows = sheet.iter_rows(values_only=True, max_row=MAX_ROWS)
    columns = None
    for row in rows:
        keys = [_header_key(cell) for cell in row]
        if _header_key(SALES_ORDER_HEADER) in keys and _header_key(MERCHANT_ORDER_HEADER) in keys:
            columns = (keys.index(_header_key(SALES_ORDER_HEADER)), keys.index(_header_key(MERCHANT_ORDER_HEADER)))
            break
    if columns is None:
        return None

    sales_column, merchant_column = columns
    orders: list[ExportOrder] = []
    stated: int | None = None
    skipped = 0
    for row in rows:
        cells = list(row) + [None] * (max(columns) + 1 - len(row))
        sales_cell = cells[sales_column]
        sales_order = _text(sales_cell)
        if any(_header_key(cell) == COUNT for cell in cells) and isinstance(sales_cell, (int, float)):
            stated = int(sales_cell)
            continue
        if not sales_order.upper().startswith(ORDER_PREFIX):
            if _text(cells[merchant_column]):
                skipped += 1
            continue
        if not SALES_ORDER.fullmatch(sales_order.upper()):
            raise ExportRefused(
                f"\"{sales_order[:60]}\" isn't a Khazenly sales order number. Nothing was built."
            )
        orders.append(ExportOrder(sales_order.upper(), _text(cells[merchant_column])))

    if not orders:
        raise ExportRefused("The export lists no orders. Nothing to confirm.")
    _refuse_twice([order.sales_order for order in orders], "sales order number")
    _refuse_twice([order.merchant_order for order in orders if order.merchant_order], "merchant order number")
    if stated is not None and stated != len(orders):
        raise ExportRefused(
            f"Khazenly's file says it lists {stated} orders, but the platform found "
            f"{len(orders)}. Nothing was built - download the export again."
        )
    return Export(orders, stated, skipped)


def _refuse_twice(values: list[str], what: str) -> None:
    seen: set[str] = set()
    for value in values:
        key = normalise(value)
        if key in seen:
            raise ExportRefused(f"The {what} {value} is in the file twice. Nothing was built.")
        seen.add(key)


# ── Matching against Shopify ──────────────────────────────────────────────────


def normalise(number: str) -> str:
    """An order number as both sides are matched: ``#31840`` is ``31840``."""
    return re.sub(r"\s+", "", number).lstrip("#").upper()


#: Why an order was left out, in the order the summary shows them. The first
#: three are the safety exclusions; the rest are orders not confirmed.
REASONS: tuple[tuple[str, str], ...] = (
    ("not_open", "Not open in Shopify"),
    ("confirmed_but_cancelled", "Confirmed, but also tagged Cancelled ❌"),
    ("confirmed_but_shipped", "Confirmed, but already shipped in Shopify"),
    ("cancelled", "Cancelled ❌"),
    ("edit", "Asked to change the order (Edit ✏️)"),
    ("awaiting_payment", "Awaiting payment 💳"),
    ("no_whatsapp", "No WhatsApp 📵"),
    ("wa_sent", "Sent on WhatsApp, no answer yet (WA Sent 📤)"),
    ("no_tag", "No confirmation tag"),
    ("no_number", "No Shopify order number in Khazenly's file"),
)


def reason_for(tags: list[str], fulfillment_status: str | None) -> str | None:
    """Why an open Shopify order stays out of the file, or None if it goes in.

    In only when tagged Confirmed (both spellings; compression no longer
    needs a call - ADR 0071), and not also tagged Cancelled or shipped.
    """
    keys = {tag_key(tag) for tag in tags}
    if CONFIRMED in keys:
        if CANCELLED in keys:
            return "confirmed_but_cancelled"
        if (fulfillment_status or "").upper() in SHIPPED:
            return "confirmed_but_shipped"
        return None
    for key, reason in (
        (CANCELLED, "cancelled"),
        (EDIT, "edit"),
        (AWAITING_PAYMENT, "awaiting_payment"),
        (NO_WHATSAPP, "no_whatsapp"),
        (WA_SENT, "wa_sent"),
    ):
        if key in keys:
            return reason
    return "no_tag"


@dataclass
class Decision:
    #: The orders to confirm, in the export's order, by both numbers.
    confirmed: list[dict] = field(default_factory=list)
    #: Reason -> the orders left out for it.
    left_out: dict[str, list[dict]] = field(default_factory=dict)


def decide(db: Session, orders: list[ExportOrder]) -> Decision:
    """Each export order against the last clean read of open Shopify orders."""
    open_orders = {
        normalise(row.order_number): row for row in db.scalars(select(OpsShopifyOrder)).all()
    }
    decision = Decision()
    for order in orders:
        shopify = open_orders.get(normalise(order.merchant_order)) if order.merchant_order else None
        if not order.merchant_order:
            reason = "no_number"
        elif shopify is None:
            reason = "not_open"
        else:
            reason = reason_for(shopify.tags, shopify.fulfillment_status)
        if reason is None:
            decision.confirmed.append({"sales_order": order.sales_order, "order_number": shopify.order_number})
            continue
        decision.left_out.setdefault(reason, []).append(
            {
                "sales_order": order.sales_order,
                "order_number": shopify.order_number if shopify else (f"#{order.merchant_order}" if order.merchant_order else None),
            }
        )
    return decision


# ── Writing Khazenly's template ───────────────────────────────────────────────


def _cell_string(text: str) -> str:
    return f"<si><t>{escape(text)}</t></si>"


def fill_template(sales_orders: list[str]) -> bytes:
    """Khazenly's bulk-confirm template with one ``True`` row per order.

    Only the *Orders* sheet and the strings it points to are rewritten; every
    other part of the workbook - the User Guide, its picture, the styles - is
    copied byte for byte (ADR 0071, decision 7).
    """
    if not sales_orders:
        raise ValueError("A bulk-confirm file needs at least one order.")
    template = TEMPLATE.read_bytes()
    with zipfile.ZipFile(io.BytesIO(template)) as source:
        strings = source.read(SHARED_STRINGS).decode("utf-8")
        sheet = source.read(ORDERS_SHEET).decode("utf-8")

        unique = len(re.findall(r"<si>|<si\s", strings))
        true_index = unique
        additions = [_cell_string(TRUE)] + [_cell_string(number) for number in sales_orders]
        strings = strings.replace("</sst>", "".join(additions) + "</sst>")
        strings = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{unique + len(additions)}"', strings, count=1)
        strings = re.sub(
            r'(<sst\b[^>]*?\s)count="(\d+)"',
            lambda match: f'{match.group(1)}count="{int(match.group(2)) + 2 * len(sales_orders)}"',
            strings,
            count=1,
        )

        rows = "".join(
            f'<row r="{row}" spans="1:2">'
            f'<c r="A{row}" t="s"><v>{true_index + offset}</v></c>'
            f'<c r="B{row}" s="{TEXT_STYLE}" t="s"><v>{true_index}</v></c>'
            "</row>"
            for offset, row in enumerate(range(2, len(sales_orders) + 2), start=1)
        )
        sheet = sheet.replace("</sheetData>", rows + "</sheetData>", 1)
        sheet = re.sub(r'<dimension ref="[^"]*"/>', f'<dimension ref="A1:B{len(sales_orders) + 1}"/>', sheet, count=1)

        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for info in source.infolist():
                if info.filename == SHARED_STRINGS:
                    data = strings.encode("utf-8")
                elif info.filename == ORDERS_SHEET:
                    data = sheet.encode("utf-8")
                else:
                    data = source.read(info.filename)
                target.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def file_name(now: datetime) -> str:
    """``khazenly-bulk-confirm-2026-10-30-2245.xlsx``, in Cairo time."""
    return f"khazenly-bulk-confirm-{now.astimezone(BUSINESS_TIMEZONE):%Y-%m-%d-%H%M}.xlsx"


# ── All three, for the route ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Built:
    summary: dict
    #: The filled template, or None when nothing is confirmed.
    file: bytes | None
    file_name: str | None


def build(db: Session, filename: str, content: bytes, now: datetime | None = None) -> Built:
    """Read the export, match it, and fill the template.

    The caller checks Shopify's freshness first: an export matched against
    old tags must never become a file.
    """
    now = now or utcnow()
    export = read_export(filename, content)
    decision = decide(db, export.orders)
    left_out = [
        {"reason": key, "label": label, "count": len(decision.left_out[key]), "orders": decision.left_out[key]}
        for key, label in REASONS
        if key in decision.left_out
    ]
    summary = {
        "rows_read": len(export.orders),
        "stated_count": export.stated_count,
        "skipped_rows": export.skipped,
        "confirmed": len(decision.confirmed),
        "not_confirmed": len(export.orders) - len(decision.confirmed),
        "confirmed_orders": decision.confirmed,
        "left_out": left_out,
    }
    if not decision.confirmed:
        return Built(summary, None, None)
    return Built(
        summary, fill_template([order["sales_order"] for order in decision.confirmed]), file_name(now)
    )


# ── The runs, for the tab's history (ADR 0072) ────────────────────────────────

#: How many runs the history lists. Older ones are kept, just not listed.
HISTORY_LIMIT = 60


def keep(db: Session, built: Built, built_by: int | None, shopify_read_at: datetime | None) -> OpsKhazenlyRun:
    """Store the run the person was just shown. The caller commits."""
    summary = built.summary
    run = OpsKhazenlyRun(
        built_by=built_by,
        shopify_read_at=shopify_read_at,
        rows_read=summary["rows_read"],
        stated_count=summary["stated_count"],
        skipped_rows=summary["skipped_rows"],
        confirmed=summary["confirmed"],
        not_confirmed=summary["not_confirmed"],
        file_name=built.file_name,
        confirmed_orders=summary["confirmed_orders"],
        left_out=summary["left_out"],
    )
    db.add(run)
    db.flush()
    return run


def _who(db: Session, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = db.execute(
        select(UserAccount.id, UserAccount.display_name, UserAccount.email).where(UserAccount.id.in_(user_ids))
    ).all()
    return {row.id: row.display_name or row.email for row in rows}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _head(run: OpsKhazenlyRun, names: dict[int, str]) -> dict:
    return {
        "id": run.id,
        "built_at": run.built_at.isoformat(),
        "built_by": names.get(run.built_by) if run.built_by else None,
        "shopify_read_at": _iso(run.shopify_read_at),
        "rows_read": run.rows_read,
        "stated_count": run.stated_count,
        "skipped_rows": run.skipped_rows,
        "confirmed": run.confirmed,
        "not_confirmed": run.not_confirmed,
        "file_name": run.file_name,
    }


def history(db: Session, limit: int = HISTORY_LIMIT) -> list[dict]:
    """The latest runs, newest first: when, who and the counts."""
    runs = db.scalars(
        select(OpsKhazenlyRun).order_by(OpsKhazenlyRun.built_at.desc(), OpsKhazenlyRun.id.desc()).limit(limit)
    ).all()
    names = _who(db, {run.built_by for run in runs if run.built_by})
    return [_head(run, names) for run in runs]


def run_summary(db: Session, run_id: int) -> dict | None:
    """One run with its orders, as its summary showed them."""
    run = db.get(OpsKhazenlyRun, run_id)
    if run is None:
        return None
    names = _who(db, {run.built_by} if run.built_by else set())
    return {**_head(run, names), "confirmed_orders": run.confirmed_orders, "left_out": run.left_out}
