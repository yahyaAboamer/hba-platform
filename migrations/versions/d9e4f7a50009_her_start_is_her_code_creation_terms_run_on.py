"""her start is her code's creation; the latest terms run on (ADR 0055)

Two data corrections, no schema change.

1. **A start month taken from her code is brought to her code's creation
   month.** Until ADR 0055 her start month came from the code's "Active from"
   date on Shopify, while her code's ownership came from its creation date.
   ALI10 was created on 4 April 2026 with an "Active from" of February 2025,
   copied when it was duplicated, so Ali was given January and her code April.
   The owner, 1 October 2026: the code starts when it was created; the ALI10
   orders before April were another model's, on the discount now named
   *ALI10 OLD*. Only a start the platform took from her code is changed (the
   last `affiliate.collaboration_start_set` for her says ``"from":
   "shopify_code"``); a start somebody typed is never touched. It is set to
   the month her first confirmed code starts, which is that code's creation.

2. **The latest arrangement that ends in or after the current month is made
   open-ended.** Months that have not begun can no longer be arranged; each
   takes the terms of the month before it when it begins. An arrangement that
   ends this month would leave next month with nothing.

Each change writes an `audit_event` row saying what moved, from what, and why.

**Terms that start after the current month are not handled here**, because
none exist: read on 1 October 2026, staging has only Sara's three runs (the
latest from August) and production has no terms at all. After this release
nothing can create one; the server refuses a start after the working month.

**Downgrade changes nothing.** Both are corrections of what the records should
always have said; putting them back would restore a start month that disagrees
with her code, and a month without terms.

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


START_FROM_CODE_CREATION = """
WITH last_set AS (
    SELECT DISTINCT ON (subject) subject, after_json
    FROM audit_event
    WHERE action = 'affiliate.collaboration_start_set'
    ORDER BY subject, id DESC
),
candidates AS (
    SELECT a.id, a.collaboration_start_month AS was, p.start_month AS now
    FROM affiliate_profile a
    JOIN discount_code_period p
      ON p.id = (SELECT min(q.id) FROM discount_code_period q
                 WHERE q.affiliate_id = a.id)
    JOIN last_set s ON s.subject = 'affiliate:' || a.id
    WHERE p.shopify_verified_at IS NOT NULL
      AND s.after_json ->> 'from' = 'shopify_code'
      AND a.collaboration_start_month IS DISTINCT FROM p.start_month
),
moved AS (
    UPDATE affiliate_profile a
    SET collaboration_start_month = c.now
    FROM candidates c
    WHERE a.id = c.id
    RETURNING a.id
)
INSERT INTO audit_event (action, subject, before_json, after_json, reason)
SELECT 'affiliate.collaboration_start_set',
       'affiliate:' || c.id,
       jsonb_build_object('collaboration_start_month', c.was),
       jsonb_build_object('collaboration_start_month', c.now, 'from', 'shopify_code'),
       'ADR 0055: her start is when her code was created on Shopify (migration d9e4f7a50009)'
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
    op.execute(START_FROM_CODE_CREATION)
    op.execute(LATEST_TERMS_RUN_ON)


def downgrade() -> None:
    # Deliberately nothing; see the module docstring.
    pass
