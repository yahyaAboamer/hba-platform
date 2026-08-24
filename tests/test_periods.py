"""Effective-dated periods.

Tasks 3 and 4 both need the same machinery: a period of months that the
database can refuse to overlap. Getting it wrong in two places is worse than
getting it right in one, so it is built and proven once here.

**The Python helper and the database must agree.** `covers` decides attribution;
the exclusion constraint decides what can be stored. If they disagreed, a
period could be stored that attribution never applies, or applied for a month
the constraint thinks belongs to somebody else. Several tests below exist only
to hold the two against each other.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, IntegrityError

from app.core.periods import (
    EFFECTIVE_RANGE_SQL,
    OPEN_ENDED,
    covers,
    month_bounds,
    validate_period,
)

# A throwaway table shaped exactly like the real ones, so the semantics proven
# here are the semantics Tasks 3 and 4 get.
SCRATCH = f"""
CREATE TABLE scratch_period (
    id serial PRIMARY KEY,
    owner_id integer NOT NULL,
    start_month varchar(7) NOT NULL,
    end_month varchar(7),
    effective_range daterange GENERATED ALWAYS AS ({EFFECTIVE_RANGE_SQL}) STORED,
    CONSTRAINT scratch_period_months_ordered
        CHECK (end_month IS NULL OR end_month >= start_month),
    EXCLUDE USING gist (owner_id WITH =, effective_range WITH &&)
)
"""


@pytest.fixture()
def scratch(db):
    """A real table with the real constraints.

    No teardown: CREATE TABLE is transactional in Postgres, so the db fixture's
    rollback removes it. Dropping it here explicitly would fail anyway in every
    test that deliberately provokes a constraint violation, because the
    transaction is aborted by then.
    """
    db.execute(text(SCRATCH))
    return db


def _insert(db, owner_id, start_month, end_month=None):
    db.execute(
        text(
            "INSERT INTO scratch_period (owner_id, start_month, end_month) "
            "VALUES (:o, :s, :e)"
        ),
        {"o": owner_id, "s": start_month, "e": end_month},
    )


def _stored_range(db, start_month, end_month=None) -> str:
    _insert(db, 99, start_month, end_month)
    return db.execute(
        text("SELECT effective_range::text FROM scratch_period WHERE owner_id = 99")
    ).scalar()


# ── The Python helper ──────────────────────────────────────────────────────────


def test_a_closed_period_covers_its_own_months():
    assert covers("2026-03", "2026-06", "2026-03") is True
    assert covers("2026-03", "2026-06", "2026-05") is True
    assert covers("2026-03", "2026-06", "2026-06") is True


def test_a_period_does_not_cover_the_month_before_it_starts():
    assert covers("2026-03", "2026-06", "2026-02") is False


def test_a_period_does_not_cover_the_month_after_it_ends():
    """The off-by-one that would pay somebody for a month they had left."""
    assert covers("2026-03", "2026-06", "2026-07") is False


def test_an_open_ended_period_covers_everything_after_its_start():
    assert covers("2026-03", OPEN_ENDED, "2026-03") is True
    assert covers("2026-03", OPEN_ENDED, "2030-11") is True
    assert covers("2026-03", OPEN_ENDED, "2026-02") is False


def test_a_single_month_period_covers_exactly_that_month():
    assert covers("2026-03", "2026-03", "2026-03") is True
    assert covers("2026-03", "2026-03", "2026-04") is False


def test_covers_refuses_a_malformed_month():
    with pytest.raises(ValueError):
        covers("2026-03", "2026-06", "March")


def test_month_bounds_are_half_open():
    """March-to-June is [2026-03-01, 2026-07-01). The upper bound is the month
    after the last one included - which is what stops a period ending in June
    touching one starting in July.
    """
    assert month_bounds("2026-03", "2026-06") == ("2026-03-01", "2026-07-01")


def test_month_bounds_cross_a_year_end():
    assert month_bounds("2026-11", "2026-12") == ("2026-11-01", "2027-01-01")


def test_an_open_ended_period_has_no_upper_bound():
    assert month_bounds("2026-03", OPEN_ENDED) == ("2026-03-01", None)


# ── The database agrees with the helper ────────────────────────────────────────


def test_the_stored_range_is_half_open(scratch):
    assert _stored_range(scratch, "2026-03", "2026-06") == "[2026-03-01,2026-07-01)"


def test_an_open_ended_range_is_unbounded_above(scratch):
    assert _stored_range(scratch, "2026-03", None) == "[2026-03-01,)"


@pytest.mark.parametrize(
    ("start", "end", "month"),
    [
        ("2026-03", "2026-06", "2026-02"),
        ("2026-03", "2026-06", "2026-03"),
        ("2026-03", "2026-06", "2026-06"),
        ("2026-03", "2026-06", "2026-07"),
        ("2026-11", "2027-01", "2026-12"),
        ("2026-11", "2027-01", "2027-02"),
        ("2026-03", None, "2099-12"),
        ("2026-03", None, "2026-02"),
    ],
)
def test_the_database_and_the_helper_never_disagree(scratch, start, end, month):
    """The test this file exists for.

    `covers` decides attribution; the exclusion constraint decides what can be
    stored. If they disagreed, a period could be stored that attribution never
    applies to, or applied for a month the constraint believes belongs to
    somebody else.
    """
    _insert(scratch, 1, start, end)
    in_database = scratch.execute(
        text(
            "SELECT effective_range @> (:m || '-01')::date FROM scratch_period "
            "WHERE owner_id = 1"
        ),
        {"m": month},
    ).scalar()
    assert in_database is covers(start, end, month)


# ── Overlap ────────────────────────────────────────────────────────────────────


def test_overlapping_periods_for_one_owner_are_refused(scratch):
    _insert(scratch, 1, "2026-03", "2026-06")
    with pytest.raises(IntegrityError):
        _insert(scratch, 1, "2026-05", "2026-08")


def test_adjacent_periods_are_allowed(scratch):
    """March-June and July-onward must both be storable.

    Getting the bound wrong makes every adjacent pair look like a conflict -
    which would make an ordinary rate change impossible to record.
    """
    _insert(scratch, 1, "2026-03", "2026-06")
    _insert(scratch, 1, "2026-07", None)
    scratch.flush()

    count = scratch.execute(
        text("SELECT count(*) FROM scratch_period WHERE owner_id = 1")
    ).scalar()
    assert count == 2


def test_a_period_inside_another_is_refused(scratch):
    _insert(scratch, 1, "2026-01", "2026-12")
    with pytest.raises(IntegrityError):
        _insert(scratch, 1, "2026-05", "2026-06")


def test_a_second_open_ended_period_is_refused(scratch):
    """Two "from now on" periods for one owner is a contradiction."""
    _insert(scratch, 1, "2026-03", None)
    with pytest.raises(IntegrityError):
        _insert(scratch, 1, "2026-09", None)


def test_different_owners_may_hold_the_same_months(scratch):
    _insert(scratch, 1, "2026-03", "2026-06")
    _insert(scratch, 2, "2026-03", "2026-06")
    scratch.flush()

    count = scratch.execute(text("SELECT count(*) FROM scratch_period")).scalar()
    assert count == 2


# ── The empty-range trap ───────────────────────────────────────────────────────


def test_a_backwards_period_is_refused(scratch):
    """A period ending before it starts cannot be stored.

    Asserted as "the database refuses it" rather than naming the mechanism.
    It is in fact daterange() raising during column generation, before the
    check constraint is ever evaluated - but the invariant is that the row
    cannot exist, and that should keep holding if the mechanism changes.
    """
    with pytest.raises(DatabaseError):
        _insert(scratch, 1, "2026-06", "2026-03")


def test_an_empty_range_overlaps_nothing_not_even_itself(scratch):
    """The trap this expression must never fall into.

    An empty range slips past an exclusion constraint completely - so a period
    that produced one would store, cover no months, conflict with nothing, and
    look perfectly correct in the table.

    Empty comes from *equal* bounds, not inverted ones. This expression cannot
    produce equal bounds, because the upper is always the month after the last
    included. Pinned here so that a future change to the expression has to
    reckon with it.
    """
    empty, overlaps = scratch.execute(
        text(
            "SELECT isempty(daterange('2026-04-01'::date, '2026-04-01'::date)), "
            "       daterange('2026-04-01'::date, '2026-04-01'::date) && "
            "       daterange('2026-04-01'::date, '2026-04-01'::date)"
        )
    ).one()
    assert empty is True
    assert overlaps is False


def test_no_valid_period_can_produce_an_empty_range(scratch):
    """The guarantee that keeps the trap above theoretical."""
    for start, end in [("2026-03", "2026-03"), ("2026-01", "2026-12"),
                       ("2026-12", "2026-12"), ("2026-03", None)]:
        _insert(scratch, 1, start, end)
        stored_empty = scratch.execute(
            text("SELECT isempty(effective_range) FROM scratch_period "
                 "WHERE owner_id = 1")
        ).scalar()
        assert stored_empty is False, f"{start}..{end} produced an empty range"
        scratch.execute(text("DELETE FROM scratch_period WHERE owner_id = 1"))


# ── The generated column cannot drift ──────────────────────────────────────────


def test_the_range_cannot_be_written_by_hand(scratch):
    """It is generated. A row supplying it is refused, which is what stops the
    range drifting from the months it claims to describe.
    """
    with pytest.raises(DatabaseError):
        scratch.execute(
            text(
                "INSERT INTO scratch_period "
                "(owner_id, start_month, end_month, effective_range) "
                "VALUES (1, '2026-03', '2026-06', '[2000-01-01,2001-01-01)')"
            )
        )


def test_the_range_follows_the_months_when_they_change(scratch):
    _insert(scratch, 1, "2026-03", "2026-06")
    scratch.execute(
        text("UPDATE scratch_period SET end_month = '2026-09' WHERE owner_id = 1")
    )
    stored = scratch.execute(
        text("SELECT effective_range::text FROM scratch_period WHERE owner_id = 1")
    ).scalar()
    assert stored == "[2026-03-01,2026-10-01)"


# ── The extension is present ───────────────────────────────────────────────────


def test_btree_gist_is_installed(db):
    """Without it, `owner_id WITH =` in a gist exclusion constraint is not a
    thing Postgres can do, and every period table fails to migrate.
    """
    installed = db.execute(
        text("SELECT count(*) FROM pg_extension WHERE extname = 'btree_gist'")
    ).scalar()
    assert installed == 1


# ── The readable error ─────────────────────────────────────────────────────────


def test_validation_names_the_months_the_database_would_not():
    """The database refuses a backwards period with a message about range
    bounds, which tells a person nothing. This is what they should hit first.
    """
    with pytest.raises(ValueError, match="2026-06 to 2026-03"):
        validate_period("2026-06", "2026-03")


def test_a_single_month_period_is_valid():
    """Start equals end is one month, not a backwards period."""
    assert validate_period("2026-03", "2026-03") == ("2026-03", "2026-03")


def test_an_open_ended_period_is_valid():
    assert validate_period("2026-03", OPEN_ENDED) == ("2026-03", OPEN_ENDED)


def test_validation_refuses_a_malformed_month():
    with pytest.raises(ValueError, match="YYYY-MM"):
        validate_period("March", "2026-06")


def test_validation_agrees_with_the_database(scratch):
    """Anything validation accepts, the database must store - and anything it
    rejects, the database must refuse. A disagreement either way means one of
    them is lying about what a period is.
    """
    for start, end in [("2026-03", "2026-06"), ("2026-03", "2026-03"),
                       ("2026-12", "2027-01"), ("2026-03", None)]:
        validate_period(start, end)
        _insert(scratch, 1, start, end)
        scratch.execute(text("DELETE FROM scratch_period WHERE owner_id = 1"))

    with pytest.raises(ValueError):
        validate_period("2026-06", "2026-03")
    with pytest.raises(DatabaseError):
        _insert(scratch, 1, "2026-06", "2026-03")
