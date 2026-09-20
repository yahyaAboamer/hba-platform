#!/bin/bash
# The backend suite, one file per pytest process, resumable.
#
# CLAUDE.md's "Verification" section explains why this shape rather than the
# obvious one. The three things it gets right:
#
#   * **The exit code is the result.** `pytest | tail` reports *tail's* status,
#     so a file with a hundred failures reads as a pass.
#   * **A failure is recorded as a failure**, so a resume re-runs it rather
#     than skipping it as done.
#   * **The revision is in the line**, so yesterday's pass is not mistaken for
#     today's.
#
# It also takes a time budget. On 20 September there was 0.16 GB free and the
# watchdog killed this twice as a background job while foreground runs of the
# same thing survived - so it is meant to be run in the foreground, repeatedly,
# until it reports REMAINING 0. Each call skips everything already recorded as
# passing at this revision, so a kill costs one file rather than the run.
#
#   bash docs/repair/batch-1/run-suite.sh            # 540s of work, then stop
#   bash docs/repair/batch-1/run-suite.sh 300        # a shorter slice
#
# The log is never truncated: it *is* the progress. Delete it by hand to start
# a clean run, and clear leftover backends first (CLAUDE.md says how) - a
# killed run leaves one holding locks, and every file after it reports errors
# that look exactly like a regression in whatever you last changed.

set -u
cd "$(dirname "$0")/../../.." || exit 1

OUT="${OUT_DIR:-${CLAUDE_JOB_DIR:-/tmp}}"
LOG="$OUT/suite-log.txt"
ONE="$OUT/one.txt"
TODO="$OUT/todo.txt"
DB="${DATABASE_URL:-postgresql+psycopg://hba:hba@127.0.0.1:5433/hba_platform_test}"
REV="${REV:-$(git rev-parse --short HEAD)}"
BUDGET="${1:-540}"

mkdir -p "$OUT"
touch "$LOG"
ls tests/test_*.py > "$TODO"

# Start every slice from a clean database, because the previous one may not
# have ended tidily. A killed run skips its teardown, leaves committed rows and
# an idle backend holding locks, and the next file then fails on unique
# violations and TRUNCATE deadlocks that read exactly like a regression in
# whatever you last changed. That cost an hour on 10 September and produced
# three phantom failures on 20 September before this was here.
DATABASE_URL="$DB" .venv/Scripts/python.exe - <<'PY'
from sqlalchemy import create_engine, text

from app.config import settings

engine = create_engine(settings.database_url)
with engine.connect() as c:
    c.execute(
        text(
            "select pg_terminate_backend(pid) from pg_stat_activity "
            "where datname = current_database() and pid <> pg_backend_pid()"
        )
    )
    c.commit()
from tests.conftest import empty_the_database

empty_the_database()
print("database cleared before this slice")
PY

started=$(date +%s)

while read -r f; do
  grep -q "^PASS $REV $f " "$LOG" && continue
  now=$(date +%s)
  [ $((now - started)) -ge "$BUDGET" ] && break
  DATABASE_URL="$DB" .venv/Scripts/python.exe -m pytest -q --color=no \
    -p no:cacheprovider "$f" > "$ONE" 2>&1
  code=$?
  [ "$code" = 0 ] && state=PASS || state=FAIL
  echo "$state $REV $f $(tail -1 "$ONE")" >> "$LOG"
  [ "$state" = FAIL ] && echo "FAIL $f :: $(tail -1 "$ONE")"
done < "$TODO"

passed=$(grep -c "^PASS $REV " "$LOG")
failed=$(grep -c "^FAIL $REV " "$LOG")
total=$(wc -l < "$TODO")
echo "PASSED $passed  FAILED $failed  OF $total  REMAINING $((total - passed - failed))"
