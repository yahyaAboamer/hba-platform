"""Order-import completeness report - read-only, for the owner to review.

Before HBA is asked to confirm that the historical order import is complete
(`HISTORICAL-INFORMATION-NEEDED.md`, item 4), this prints what the database
actually holds, so the confirmation is a judgement about evidence rather than
a guess.

**It writes nothing.** The transaction is opened `READ ONLY`, so the database
itself refuses any write this script might attempt.

    DATABASE_URL=... .venv/Scripts/python.exe docs/repair/order_import_report.py > report.md

**This is investigation, not proof.** Nothing in this report can establish
that the import is complete, because it only reads what was imported. Proof
is a comparison with Shopify itself - its order IDs for the same period
against the imported IDs, with every page of the listing accounted for and
any access limit recorded - which is `order_import_compare.py`.

What it can show:

- The historical import asks Shopify for **every order created since
  1 January 2026**, not only discounted ones (`bulk._orders_query`). A gap in
  the order numbers is a **clue to look at**, not a missing import: a number
  can be skipped by an order deleted in Shopify, a test order, or a number
  Shopify never issued as an order. The report lists every gap with the dates
  either side so the right ones can be looked up.
- Days with no orders are listed, because a quiet day and a day the import
  missed look the same from here.
- A discount code seen on orders that no model owns, or used outside the
  months its owner held it, is money attributed to nobody.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import create_engine, text

URL = os.environ["DATABASE_URL"]
GO_LIVE = os.environ.get("GO_LIVE_MONTH") or None
FIRST = "2026-01"
MAX_RANGES = 60


def month_of(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


def main() -> None:
    engine = create_engine(URL)
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        q = lambda sql, **kw: conn.execute(text(sql), kw).all()  # noqa: E731

        now = q("select now() at time zone 'Africa/Cairo'")[0][0]
        orders = q(
            "select order_number, (placed_at at time zone 'Africa/Cairo')::date, "
            "business_month, discount_codes, cancelled_at is not null, shopify_order_id "
            "from order_index order by placed_at, shopify_order_id"
        )
        attributed = {
            row[0]: row[1]
            for row in q("select shopify_order_id, affiliate_id from attributed_order")
        }
        periods = q(
            "select upper(p.code), p.start_month, p.end_month, a.name "
            "from discount_code_period p join affiliate_profile a on a.id = p.affiliate_id"
        )
        jobs = q(
            "select kind, status, count(*), max(finished_at at time zone 'Africa/Cairo') "
            "from background_job where kind in ('shopify_bulk_import','backfill_code','shopify_reconcile') "
            "group by 1, 2 order by 1, 2"
        )
        failures = q(
            "select kind, left(coalesce(last_error, ''), 140), finished_at at time zone 'Africa/Cairo' "
            "from background_job where kind like :pattern and status = 'failed' "
            "order by id desc limit 8",
            pattern="shopify%",
        )
        bulk = q(
            "select payload, status, finished_at at time zone 'Africa/Cairo' from background_job "
            "where kind = 'shopify_bulk_import' order by id"
        )

    out: list[str] = []
    w = out.append
    w("# Order-import completeness report\n")
    w(f"Generated {now:%d %B %Y, %H:%M} (Cairo) from the database it was run against. "
      "Read-only. Go-live month: " + (GO_LIVE or "not set") + ".\n")
    w("Nothing here is a conclusion. Each section is evidence for you to judge "
      "before confirming that every order since January 2026 is present.\n")

    if not orders:
        w("**The order index is empty.** Nothing has been imported.\n")
        print("\n".join(out))
        return

    first_day, last_day = orders[0][1], orders[-1][1]
    w("## 1. What is in the index\n")
    w(f"- **{len(orders):,} orders**, placed {first_day:%d %B %Y} to {last_day:%d %B %Y}.")
    w(f"- {sum(1 for o in orders if o[3]):,} carry a discount code; "
      f"{len(attributed):,} are attributed to a model.")
    w(f"- {sum(1 for o in orders if o[4]):,} are cancelled in Shopify (still indexed, as they should be).")
    early = sum(1 for o in orders if o[2] < FIRST)
    if early:
        w(f"- {early:,} are dated before January 2026, which the platform does not count.")
    w("")

    w("## 2. The import runs\n")
    if bulk:
        for payload, status, finished in bulk:
            since = (payload or {}).get("since", "?")
            w(f"- Bulk import of orders created since **{since}**: {status}"
              + (f", finished {finished:%d %B %Y %H:%M}" if finished else ""))
    else:
        w("- **No bulk-import job is recorded in this database.** Either the jobs were "
          "pruned or the orders arrived another way; the other sections still stand.")
    for kind, status, count, finished in jobs:
        if kind == "shopify_bulk_import":
            continue
        w(f"- `{kind}`: {count} {status}" + (f", last finished {finished:%d %B %Y %H:%M}" if finished else ""))
    for kind, error, finished in failures:
        w(f"  - failed `{kind}`" + (f" {finished:%d %b %H:%M}" if finished else "") + f": {error or 'no message'}")
    w("")

    # -- By month --------------------------------------------------------
    by_month: dict[str, list] = defaultdict(list)
    for row in orders:
        by_month[row[2]].append(row)
    w("## 3. Month by month\n")
    w("| Month | Orders | With a code | Attributed | Code, not attributed | Days with orders | Days with none |")
    w("|---|---:|---:|---:|---:|---:|---|")
    cursor = date(int(FIRST[:4]), int(FIRST[5:]), 1)
    quiet: dict[str, list[date]] = {}
    while month_of(cursor) <= month_of(last_day):
        m = month_of(cursor)
        rows = by_month.get(m, [])
        days_with = {r[1] for r in rows}
        span_end = min(
            (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1),
            now.date(),
        )
        all_days = [cursor + timedelta(days=i) for i in range((span_end - cursor).days + 1)]
        none = [d for d in all_days if d not in days_with]
        quiet[m] = none
        coded = sum(1 for r in rows if r[3])
        attr = sum(1 for r in rows if r[5] in attributed)
        tag = " (before go-live)" if GO_LIVE and m < GO_LIVE else ""
        w(f"| {m}{tag} | {len(rows):,} | {coded:,} | {attr:,} | {max(coded - attr, 0):,} | "
          f"{len(days_with)} of {len(all_days)} | {_days(none)} |")
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    w("")
    w("*Code, not attributed* is not an error by itself: a code nobody held "
      "that month, a house code, or an order held for a decision all land there. "
      "Section 5 names the codes.\n")

    # -- Order-number continuity ----------------------------------------
    w("## 4. Order numbers\n")
    numbered = []
    odd = 0
    for number, day, *_ in orders:
        match = re.fullmatch(r"#?(\d+)", number.strip())
        if match:
            numbered.append((int(match.group(1)), day))
        else:
            odd += 1
    numbered.sort()
    missing = []
    for (a, day_a), (b, day_b) in zip(numbered, numbered[1:]):
        if b - a > 1:
            missing.append((a + 1, b - 1, day_a, day_b))
    total_missing = sum(hi - lo + 1 for lo, hi, *_ in missing)
    repeated = sorted(n for n, c in Counter(n for n, _ in numbered).items() if c > 1)
    lo, hi = numbered[0][0], numbered[-1][0]
    w(f"- Numbers **#{lo} to #{hi}**: {hi - lo + 1:,} possible, {len(numbered):,} present, "
      f"**{total_missing:,} missing** in {len(missing)} gap{'s' if len(missing) != 1 else ''}.")
    if repeated:
        w(f"- **{len(repeated)} order number{'s' if len(repeated) != 1 else ''} appear more than once** "
          f"(first: {', '.join('#' + str(n) for n in repeated[:8])}): two orders sharing a number "
          "is worth asking the shop about.")
    if odd:
        w(f"- {odd} order number{'s' if odd != 1 else ''} not of the form #1234, left out of this check.")
    w("- A gap is a **clue, not a finding**: an order deleted in Shopify, a test order "
      "or a number never issued leaves the same gap as an order that was not imported. "
      "Only a comparison of order IDs with Shopify can tell them apart.")
    w("- Orders before #" + str(lo) + " were created before 1 January 2026 and are not "
      "expected here.\n")
    if missing:
        w("| Missing | Between orders placed |")
        w("|---|---|")
        for lo_, hi_, a, b in missing[:MAX_RANGES]:
            label = f"#{lo_}" if lo_ == hi_ else f"#{lo_} to #{hi_} ({hi_ - lo_ + 1})"
            w(f"| {label} | {a:%d %b %Y} and {b:%d %b %Y} |")
        if len(missing) > MAX_RANGES:
            w(f"| ... {len(missing) - MAX_RANGES} more | |")
        w("")

    # -- Codes -----------------------------------------------------------
    w("## 5. Discount codes on orders\n")
    held = defaultdict(list)
    for code, start, end, name in periods:
        held[code].append((start, end, name))
    usage: dict[str, Counter] = defaultdict(Counter)
    for _, _, month, codes, *_ in orders:
        for code in codes or []:
            usage[code.upper()][month] += 1
    unowned = []
    outside = []
    for code, months in sorted(usage.items()):
        owners = held.get(code)
        if not owners:
            unowned.append((code, months))
            continue
        for month, count in months.items():
            if not any(s <= month and (e is None or month <= e) for s, e, _ in owners):
                outside.append((code, month, count, ", ".join(sorted({n for *_, n in owners}))))
    w(f"- {len(usage)} distinct codes appear on orders; {len(usage) - len(unowned)} belong to a model.")
    if unowned:
        w("- **Codes no model owns** (their orders are attributed to nobody):\n")
        w("| Code | Orders by month |")
        w("|---|---|")
        for code, months in unowned:
            w(f"| {code} | " + ", ".join(f"{m}: {n}" for m, n in sorted(months.items())) + " |")
        w("")
    if outside:
        w("- **Used outside the months its owner held it**:\n")
        w("| Code | Month | Orders | Held by |")
        w("|---|---|---:|---|")
        for code, month, count, names in outside:
            w(f"| {code} | {month} | {count} | {names} |")
        w("")
    if not unowned and not outside:
        w("- Every code on an order belongs to a model for the month it was used.\n")

    w("## What would prove it\n")
    w("This report cannot. Completeness is shown by `order_import_compare.py`: every "
      "Shopify order ID for the period against the imported IDs, every page of "
      "Shopify's listing accounted for, and any access limit (scopes, date windows, "
      "rate limits) recorded. Use the clues above to check its result:\n")
    w("1. Each gap in section 4: deleted in Shopify, a test order, or not imported?")
    w("2. Any day in section 3 with no orders that you know had sales.")
    w("3. Each code in section 5 that no model owns: a code that belonged to someone?")
    print("\n".join(out))


def _days(days: list[date]) -> str:
    """Runs of days, compactly: `3-5 Jan, 9 Jan`."""
    if not days:
        return "-"
    runs, start, prev = [], days[0], days[0]
    for d in days[1:]:
        if d - prev == timedelta(days=1):
            prev = d
            continue
        runs.append((start, prev))
        start = prev = d
    runs.append((start, prev))
    parts = [f"{a.day}" if a == b else f"{a.day}-{b.day}" for a, b in runs]
    text_ = ", ".join(parts)
    return text_ if len(text_) <= 60 else f"{len(days)} days, " + text_[:50] + "..."


if __name__ == "__main__":
    main()
