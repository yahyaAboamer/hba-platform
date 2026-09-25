"""Settings → Reference: the audit trail read as sentences (item 11).

The trail is unchanged; these are its words. Every action the code writes has
a sentence of its own, so a new action cannot quietly arrive as a code.
"""

import re
from pathlib import Path
from types import SimpleNamespace

from app.services import audit_words
from app.services.audit_words import _Names, sentence

APP = Path(__file__).resolve().parents[1] / "app"


def _written_actions() -> set[str]:
    found = set()
    for path in APP.rglob("*.py"):
        found |= set(re.findall(r'action="([a-z_]+\.[a-z_]+)"', path.read_text()))
        found |= set(re.findall(r'"(payout_destination\.(?:set|changed))"', path.read_text()))
    return found


def _names(**kw):
    names = _Names.__new__(_Names)
    names.affiliates = kw.get("affiliates", {6: "Yahya Aboamer"})
    names.users = kw.get("users", {1: "Nour Hassan"})
    names.months = kw.get("months", {5: "2026-09"})
    return names


def _event(action, subject="affiliate:6", before=None, after=None, actor_id=1):
    return SimpleNamespace(action=action, subject=subject, before_json=before, after_json=after,
                           actor_id=actor_id, actor_email="nour@example.com")


def test_every_action_the_code_writes_has_its_own_sentence():
    actions = _written_actions()
    assert len(actions) > 40
    fallback = []
    for action in sorted(actions):
        words = sentence(_event(action, after={"month": "2026-09"}), _names())
        if " - " in words and words.split(" - ")[0].lower().startswith(action.split(".")[0]):
            fallback.append(action)
    assert fallback == []


def test_the_exports_own_examples_read_the_same():
    names = _names()
    assert sentence(_event("payment.recorded", after={"amount_piastres": 190000, "allocations": {"5": 190000}}), names) \
        == "Recorded a payment of EGP 1,900.00 to Yahya Aboamer for September 2026"
    assert sentence(_event("target.actuals_recorded", after={"month": "2026-10"}), names) \
        == "Recorded achieved content for Yahya Aboamer, October 2026"


def test_money_moving_without_a_transfer_says_which_way():
    names = _names()
    assert sentence(_event("adjustment.credit", after={"amount_piastres": 6100, "source_month": "2026-08", "destination_month": "2026-09"}), names) \
        == "Carried EGP 61.00 overpaid to Yahya Aboamer in August 2026 forward to September 2026"
    assert sentence(_event("adjustment.writeoff", after={"amount_piastres": 6100, "source_month": "2026-08"}), names) \
        == "Wrote off EGP 61.00 overpaid to Yahya Aboamer in August 2026"


def test_a_destination_is_named_by_its_method_only():
    words = sentence(_event("payout_destination.changed", after={"method": "instapay", "instapay_phone": "****"}), _names())
    assert words == "Changed where Yahya Aboamer's payments go (InstaPay)"
    assert "*" not in words


def test_an_unknown_action_still_reads_as_words_not_a_code():
    words = sentence(_event("thing.happened_today"), _names())
    assert "." not in words.split(" - ")[0]


def test_who_is_the_person_not_the_address():
    assert _names().who(_event("auth.login", subject="user:1")) == "Nour Hassan"
    assert audit_words._month("2026-02") == "February 2026"
