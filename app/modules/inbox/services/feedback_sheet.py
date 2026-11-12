"""The Feedback sheet as a spreadsheet (ADR 0083).

One row per asked order, human headings, dates as real dates in Cairo time.
**The file carries customers' names and phones**, so the route that returns it
is audited (``inbox.feedback_downloaded``). Customers' own words go in as text
and never as a formula: a comment that starts with ``=`` stays a comment.
"""

import io
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from app.core.businesstime import BUSINESS_TIMEZONE
from app.modules.inbox.services import feedback

CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: (heading, width)
COLUMNS = (
    ("Asked", 17),
    ("Customer", 22),
    ("Phone", 16),
    ("Order", 10),
    ("Products", 40),
    ("Courier", 14),
    ("Delivered", 17),
    ("Rating", 12),
    ("Reason", 16),
    ("Comment", 50),
    ("Would order again", 18),
    ("Resolved by", 18),
    ("Resolved on", 17),
    ("Solved", 9),
    ("Times reopened", 15),
    ("Code", 12),
    ("Code sent", 17),
    ("Code used", 17),
    ("Used on order", 14),
    ("Sending", 24),
    ("Problem", 50),
)

DATE_FORMAT = "yyyy-mm-dd hh:mm"


def file_name(now: datetime) -> str:
    """``feedback-2026-11-12.xlsx``, by the Cairo date."""
    return f"feedback-{now.astimezone(BUSINESS_TIMEZONE):%Y-%m-%d}.xlsx"


def _when(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso).astimezone(BUSINESS_TIMEZONE).replace(tzinfo=None)


def _yes_no(value: bool | None) -> str | None:
    return None if value is None else ("Yes" if value else "No")


def _line(row: dict) -> list:
    return [
        _when(row["asked_at"]),
        row["customer_name"],
        row["phone"],
        row["order_name"],
        "; ".join(row["products"]),
        row["courier"],
        _when(row["delivered_at"]),
        feedback.RATING_TITLES.get(row["rating"] or "", None),
        feedback.reason_title(row["rating"], row["reason"]),
        row["comment"],
        feedback.REORDER_TITLES.get(row["reorder"] or "", None),
        row["resolved_by_name"],
        _when(row["resolved_at"]),
        _yes_no(row["solved"]),
        row["reopened_count"],
        row["code"],
        _when(row["code_sent_at"]),
        _when(row["code_used_at"]),
        row["code_order_name"],
        row["state_label"],
        row["last_error"],
    ]


def build(rows: list[dict]) -> bytes:
    """The workbook, as the bytes of an ``.xlsx``."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Feedback"
    sheet.append([heading for heading, _ in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, (_, width) in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = width
    for row in rows:
        sheet.append(_line(row))
        for cell in sheet[sheet.max_row]:
            if isinstance(cell.value, datetime):
                cell.number_format = DATE_FORMAT
            elif isinstance(cell.value, str):
                # Words, never a formula (openpyxl reads a leading "=" as one).
                cell.data_type = "s"
                cell.alignment = Alignment(vertical="top", wrap_text=cell.column in (5, 10, 21))
    sheet.freeze_panes = "A2"
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
