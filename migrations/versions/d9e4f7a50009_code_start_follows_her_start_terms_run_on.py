"""her code is hers from her start; the latest terms run on (ADR 0055)

Two data corrections, no schema change.

1. **A confirmed code whose ownership starts after its model's start month is
   moved back to her start.** Until ADR 0055 the code's ownership started at
   the discount's creation date on Shopify while her start month came from its
   start date. ALI10 on staging was recreated on Shopify on 4 April 2026 with a
   start of February 2025: she started in January, her code in April, and
   January's five ALI10 orders belonged to nobody. Only her first code period
   is moved, only to a start at or after January 2026, and only where no other
   period of the same code covers those months (the exclusion constraint would
   refuse it anyway). The hourly orphan sweep then attaches the orders.

2. **The latest arrangement that ends in or after the current month is made
   open-ended.** Months that have not begun can no longer be arranged; each
   takes the terms of the month before it when it begins. An arrangement that
   ends this month would leave next month with nothing.

Each change writes an `audit_event` row saying what moved, from what, and why.

**Terms that start after the current month are not handled here**, because
none exist: read on 1 October 2026, staging has only Sara's three runs (the
latest from August) and production has no terms at all. After this release
nothing can create one; the server refuses a start after the working month.

**Downgrade changes nothing.** Moving an ownership start back later would
orphan orders attributed since, and closing an arrangement again would leave a
month without terms. Both are corrections of what the records should always
have said.

Revision ID: d9e4f7a50009
Revises: c8d3e6f40008
Create Date: 2026-10-01 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "d9e4f7a50009"
down_revision: Union[str, Sequence[str], None] = "c8d3e6f40008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ALIGN_CODE_STARTS = """
WITH candidates AS (
    SELECT p.id, p.affiliate_id, p.code,
           p.start_month AS was, a.collaboration_start_month AS now
    FROM discount_code_period p
    JOIN affiliate_profile a ON a.id = p.affiliate_id
    WHERE p.shopify_verified_at IS NOT NULL
      AND a.collaboration_start_month IS NOT NULL
      AND a.collaboration_start_month >= '2026-01'
      AND p.start_month > a.collaboration_start_month
      AND p.id = (SELECT min(q.id) FROM discount_code_period q
                  WHERE q.affiliate_id = p.affiliate_id)
      AND NOT EXISTS (
          SELECT 1 FROM discount_code_period o
          WHERE o.code = p.code AND o.id <> p.id
            AND o.start_month < p.start_month
            AND (o.end_month IS NULL OR o.end_month >= a.collaboration_start_month)
      )
),
moved AS (
    UPDATE discount_code_period p
    SET start_month = c.now
    FROM candidates c
    WHERE p.id = c.id
    RETURNING p.id
)
INSERT INTO audit_event (action, subject, before_json, after_json, reason)
SELECT 'code.start_aligned',
       'affiliate:' || c.affiliate_id,
       jsonb_build_object('code', c.code, 'start_month', c.was),
       jsonb_build_object('code', c.code, 'start_month', c.now),
       'ADR 0055: her code is hers from her start month (migration d9e4f7a50009)'
FROM candidates c JOIN moved m ON m.id = c.id
"""

LATEST_TERMS_RUN_ON = """
WITH latest AS (
    SELECT DISTINCT ON (affiliate_id) id, affiliate_id, start_month, end_month
    FROM compensation_period
    ORDER BY affiliate_id, start_month DESC
),
candidates AS (
    SELECT * FROM latest
    WHERE end_month IS NOT NULL
      AND end_month >= to_char(now() AT TIME ZONE 'Africa/Cairo', 'YYYY-MM')
),
opened AS (
    UPDATE compensation_period p
    SET end_month = NULL
    FROM candidates c
    WHERE p.id = c.id
    RETURNING p.id
)
INSERT INTO audit_event (action, subject, before_json, after_json, reason)
SELECT 'compensation.runs_on',
       'affiliate:' || c.affiliate_id,
       jsonb_build_object('start_month', c.start_month, 'end_month', c.end_month),
       jsonb_build_object('start_month', c.start_month, 'end_month', NULL),
       'ADR 0055: the latest arrangement runs on into each new month (migration d9e4f7a50009)'
FROM candidates c JOIN opened o ON o.id = c.id
"""


def upgrade() -> None:
    op.execute(ALIGN_CODE_STARTS)
    op.execute(LATEST_TERMS_RUN_ON)


def downgrade() -> None:
    # Deliberately nothing; see the module docstring.
    pass
