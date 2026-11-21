"""The follow-up an unhappy answer is owed, as a record (ADR 0087): every call
with no answer, every note, *Resolved* with what was agreed, *Couldn't reach*,
and the WhatsApp message after the second unanswered call.

What is sent goes to a mock transport. Every number, name and order is made up.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.inbox.models import FeedbackFollowUp
from tests.feedback_support import survey


# ── The record ────────────────────────────────────────────────────────────────


def test_the_follow_up_table_holds_an_entry(db):
    s = survey(db, rating="unhappy", step="support")

    db.add(FeedbackFollowUp(survey_id=s.id, round=0, kind="no_answer", note=None))
    db.flush()

    entry = db.scalar(select(FeedbackFollowUp).where(FeedbackFollowUp.survey_id == s.id))
    assert (entry.round, entry.kind, entry.note, entry.actor_id) == (0, "no_answer", None, None)
    assert entry.at is not None


def test_an_unknown_kind_is_refused(db):
    s = survey(db, rating="unhappy", step="support")

    db.add(FeedbackFollowUp(survey_id=s.id, round=0, kind="call"))
    with pytest.raises(IntegrityError):
        db.flush()
