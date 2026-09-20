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
# until it exits 0. Each call skips everything already recorded as passing at
# this revision, so a kill costs one file rather than the run.
#
#   bash docs/repair/batch-1/run-suite.sh            # 540s of work, then stop
#   bash docs/repair/batch-1/run-suite.sh 300        # a shorter slice
#
# ## This script destroys data, so it refuses to run against a database that
# ## has not said, in writing and inside itself, that it is disposable
#
# It terminates every other connection and then truncates every table. Against
# staging or production that is the worst thing in this repository, and the
# only thing standing between here and there used to be whichever
# `DATABASE_URL` happened to be exported - the exact mistake CLAUDE.md already
# records for pytest, where an unset variable emptied the dev database on 10
# September and every test passed because the suite builds its own rows.
#
# An environment variable cannot be the guard, because an environment variable
# is what goes wrong. The designation lives **in the database**:
#
#   CREATE SCHEMA IF NOT EXISTS hba_test_guard;
#   CREATE TABLE IF NOT EXISTS hba_test_guard.designation (token text primary key);
#   INSERT INTO hba_test_guard.designation VALUES
#     ('this database is disposable and may be erased at any time');
#
# It survives both things the suite does to the schema: `empty_the_database`
# truncates only `public`, and `_rebuild_schema` drops only `public`. So it is
# written once, by a person, into a database they have decided is disposable,
# and it stays there. Nothing in this script or the test suite creates it, and
# that is the point - the refusal below is only worth having if getting past it
# takes a deliberate act against the right database.
#
# Exit codes, because a caller has to be able to tell these apart:
#
#   0  every file passed and nothing is left to run
#   1  at least one file failed
#   2  refused: the database is not designated disposable (nothing was touched)
#   3  the pre-run cleanup failed (nothing was run)
#   4  incomplete: the budget ran out with files still to go - call it again

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

# Check the designation, then clear. In that order, in one place, and the
# script goes no further if either part is unhappy: a slice that starts on a
# database the last one left dirty reports unique violations and TRUNCATE
# deadlocks that read exactly like a regression in whatever you last changed.
# That cost an hour on 10 September and produced three phantom failures on 20
# September.
DATABASE_URL="$DB" .venv/Scripts/python.exe - <<'PY'
import sys

from sqlalchemy import create_engine, text

from app.config import settings

url = settings.database_url
engine = create_engine(url, connect_args={"connect_timeout": 20})

DESIGNATION = "this database is disposable and may be erased at any time"

try:
    with engine.connect() as c:
        name = c.execute(text("select current_database()")).scalar()
        host = c.execute(text("select inet_server_addr()")).scalar()
        designated = c.execute(
            text(
                "select exists ("
                "  select 1 from information_schema.tables"
                "   where table_schema = 'hba_test_guard'"
                "     and table_name = 'designation'"
                ")"
            )
        ).scalar()
        token = None
        if designated:
            token = c.execute(
                text("select token from hba_test_guard.designation limit 1")
            ).scalar()
except Exception as reaching:  # noqa: BLE001 - reported, not handled
    print(f"could not reach the database to check its designation: {reaching}")
    sys.exit(3)

if token != DESIGNATION:
    print(
        f"REFUSED. {name!r} on {host or 'this host'} is not designated as a "
        "disposable test database, and this script erases every table in it.\n"
        "\n"
        "If - and only if - that database exists to be thrown away, say so "
        "inside it:\n"
        "\n"
        "  CREATE SCHEMA IF NOT EXISTS hba_test_guard;\n"
        "  CREATE TABLE IF NOT EXISTS hba_test_guard.designation "
        "(token text primary key);\n"
        f"  INSERT INTO hba_test_guard.designation VALUES ('{DESIGNATION}');\n"
        "\n"
        "Never run this against staging or production."
    )
    sys.exit(2)

try:
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
except Exception as clearing:  # noqa: BLE001 - reported, not handled
    print(f"could not clear {name!r} before the run: {clearing}")
    sys.exit(3)

print(f"{name!r} is designated disposable, and is now empty")
PY
guard=$?
if [ "$guard" != 0 ]; then
  echo "run-suite: nothing was run (exit $guard)"
  exit "$guard"
fi

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
remaining=$((total - passed - failed))
echo "PASSED $passed  FAILED $failed  OF $total  REMAINING $remaining"

# A caller that only looks at the last line should still be able to tell a
# finished green run from a slice that stopped halfway, which is why
# "incomplete" is not 0.
[ "$failed" -gt 0 ] && exit 1
[ "$remaining" -gt 0 ] && exit 4
exit 0
