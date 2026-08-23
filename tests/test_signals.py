"""Prevented failures are reported, and the reporting path itself is sound.

A reporting mechanism that can break, or that can be silently switched off, is
worse than none: it produces confident silence.
"""

import logging
import re
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.signals import Anomaly, report

LIMITS = Path(__file__).resolve().parents[1] / "docs" / "limits.md"


def _anomaly_names() -> list[str]:
    return [
        value
        for name, value in vars(Anomaly).items()
        if not name.startswith("_") and isinstance(value, str)
    ]


# ── The catalogue and the register agree ───────────────────────────────────────


def test_every_anomaly_is_explained_in_the_limits_register(db):
    """A log line nobody can look up is barely better than no log line.

    docs/limits.md is where someone goes when they meet one of these in
    production. Adding a name without an entry there leaves them stranded.
    """
    register = LIMITS.read_text(encoding="utf-8")
    missing = [name for name in _anomaly_names() if name not in register]
    assert not missing, f"anomalies with no entry in docs/limits.md: {missing}"


def test_the_catalogue_is_not_empty(db):
    """Guards the test above, which would pass vacuously on an empty list."""
    assert len(_anomaly_names()) >= 5


def test_anomaly_names_are_stable_tokens(db):
    """They are grepped for in logs, so they must be plain and lowercase."""
    for name in _anomaly_names():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), name


# ── Reporting never breaks its caller ──────────────────────────────────────────


def test_reporting_emits_the_name_and_the_context(caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        report(Anomaly.JOB_GAVE_UP, job_id=7, kind="sync_order")

    assert "ANOMALY" in caplog.text
    assert Anomaly.JOB_GAVE_UP in caplog.text
    assert "job_id=7" in caplog.text
    assert "kind='sync_order'" in caplog.text


def test_reporting_survives_a_value_that_cannot_be_rendered(caplog):
    """Reporting must never be the thing that breaks the operation."""

    class Awkward:
        def __repr__(self):
            raise RuntimeError("no repr for you")

    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        report(Anomaly.ERROR_TRUNCATED, value=Awkward())

    assert Anomaly.ERROR_TRUNCATED in caplog.text


def test_reporting_with_no_context_is_fine(caplog):
    with caplog.at_level(logging.WARNING, logger="hba.anomaly"):
        report(Anomaly.WORK_DEDUPLICATED)
    assert Anomaly.WORK_DEDUPLICATED in caplog.text


# ── The reporting path cannot be silently switched off ─────────────────────────


def test_running_migrations_does_not_disable_application_logging():
    """Regression. alembic's env.py calls logging.config.fileConfig, which
    defaults to disable_existing_loggers=True and switches off every logger
    created before it - permanently, and without erroring.

    The symptom is the worst kind: logs simply stop, and everything looks fine.
    It silenced hba.anomaly under test, which is the only reason it was found.
    """
    logger = logging.getLogger("hba.anomaly")
    assert not logger.disabled, "already disabled before migrating"

    command.upgrade(Config("alembic.ini"), "head")

    assert not logger.disabled, (
        "running migrations disabled the anomaly logger - check that env.py "
        "passes disable_existing_loggers=False to fileConfig"
    )
