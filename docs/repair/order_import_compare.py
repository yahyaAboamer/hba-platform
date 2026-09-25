"""Compare Shopify's order IDs with the imported ones - read-only, for the owner.

This is what can show the historical import is complete; the report beside it
(`order_import_report.py`) shows only clues. The logic and its tests are
`app/services/shopify/completeness.py` and `tests/test_import_completeness.py`.

    DATABASE_URL=... SHOPIFY_SHOP_DOMAIN=... SHOPIFY_CLIENT_ID=... SHOPIFY_CLIENT_SECRET=... \\
      .venv/Scripts/python.exe docs/repair/order_import_compare.py \\
      --environment staging --from 2026-01-01 --to 2026-09-01 > comparison.md

It reads Shopify (the app holds read scopes only) and reads the database in a
read-only transaction. **Not to be run against production data until the
owner authorises it** - he has not, as of 25 September.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.services.shopify.completeness import compare, render  # noqa: E402
from app.services.shopify.sync import build_client  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--environment", required=True, help="named in the report, e.g. staging")
    parser.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD, inclusive (UTC)")
    parser.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD, exclusive (UTC)")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        with Session(bind=connection) as db:
            result = compare(db, build_client(), start, end)
    print(render(result, args.environment))


if __name__ == "__main__":
    main()
