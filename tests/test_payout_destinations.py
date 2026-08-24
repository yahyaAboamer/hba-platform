"""Where money is sent.

Spec section 6.4. Changing a payout destination is a money-impacting change,
not a profile edit: an account that can silently repoint an InstaPay address
can redirect an entire payout.

Two things are built here - append-only storage with supersession, and masking.
The rest of §6.4 (password re-entry, immediate notification, the recent-change
warning) needs the affiliate portal and arrives in Phase 8. See docs/limits.md.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.core.passwords import hash_password
from app.models.identity import UserAccount
from app.models.payouts import PayoutDestination, PayoutMethod
from app.services.affiliates import create_affiliate
from app.services.payouts import (
    VISIBLE_TAIL,
    current_destination,
    destination_history,
    mask_destination,
    set_destination,
)

INSTAPAY_URL = "https://ipn.eg/S/nour.mahmoud/instapay/8Xk2Qp"
ACCOUNT_NUMBER = "10098877665544"


def _affiliate(db, name="Nour"):
    account = UserAccount(
        email=f"{name.lower()}@example.com",
        password_hash=hash_password("a-long-enough-password"),
        status="active",
        display_name=name,
    )
    db.add(account)
    db.flush()
    return create_affiliate(db, user_account_id=account.id, name=name)


def _instapay(db, affiliate, url=INSTAPAY_URL, phone="01001234567"):
    return set_destination(
        db,
        affiliate,
        method=PayoutMethod.INSTAPAY,
        instapay_address_url=url,
        instapay_phone=phone,
    )


# ── Supersession ───────────────────────────────────────────────────────────────


def test_a_destination_can_be_set(db):
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    assert current_destination(db, nour).id == destination.id
    assert destination.superseded_at is None


def test_setting_a_new_destination_supersedes_the_previous_one(db):
    nour = _affiliate(db)
    first = _instapay(db, nour)
    db.flush()
    second = _instapay(db, nour, url="https://ipn.eg/S/other/instapay/9Yz")
    db.flush()

    assert first.superseded_at is not None
    assert second.superseded_at is None
    assert current_destination(db, nour).id == second.id


def test_a_superseded_destination_is_still_readable(db):
    """A payment made in March must still resolve where it was sent."""
    nour = _affiliate(db)
    first = _instapay(db, nour)
    db.flush()
    _instapay(db, nour, url="https://ipn.eg/S/other/instapay/9Yz")
    db.flush()

    assert db.get(PayoutDestination, first.id).instapay_address_url == INSTAPAY_URL


def test_history_is_ordered_newest_first(db):
    nour = _affiliate(db)
    _instapay(db, nour, url="https://ipn.eg/S/one/instapay/1")
    db.flush()
    _instapay(db, nour, url="https://ipn.eg/S/two/instapay/2")
    db.flush()

    history = destination_history(db, nour)
    assert len(history) == 2
    assert history[0].instapay_address_url.endswith("/2")


def test_an_affiliate_with_no_destination_has_none(db):
    nour = _affiliate(db)
    db.flush()
    assert current_destination(db, nour) is None


def test_one_affiliates_destination_is_not_anothers(db):
    nour = _affiliate(db, "Nour")
    sara = _affiliate(db, "Sara")
    _instapay(db, nour)
    db.flush()

    assert current_destination(db, sara) is None


# ── Append-only ────────────────────────────────────────────────────────────────


def test_a_destination_cannot_be_edited(db):
    """Editing in place would change where a past payment appears to have gone."""
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "UPDATE payout_destination SET instapay_address_url = 'x' "
                "WHERE id = :i"
            ),
            {"i": destination.id},
        )


def test_a_destination_cannot_be_deleted(db):
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    with pytest.raises(DatabaseError):
        db.execute(
            text("DELETE FROM payout_destination WHERE id = :i"), {"i": destination.id}
        )


def test_the_table_cannot_be_truncated(db):
    """A row-level trigger does not fire on TRUNCATE. A second one is needed."""
    with pytest.raises(DatabaseError):
        db.execute(text("TRUNCATE payout_destination"))


def test_superseding_is_the_one_permitted_change(db):
    """Supersession is what makes the history a history rather than a pile."""
    nour = _affiliate(db)
    first = _instapay(db, nour)
    db.flush()
    _instapay(db, nour, url="https://ipn.eg/S/other/instapay/9Yz")
    db.flush()

    assert db.get(PayoutDestination, first.id).superseded_at is not None


def test_only_superseded_at_may_change(db):
    """Guards the exception from becoming a loophole: the trigger permits the
    supersession stamp and nothing else.
    """
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "UPDATE payout_destination "
                "SET superseded_at = now(), instapay_phone = '01099999999' "
                "WHERE id = :i"
            ),
            {"i": destination.id},
        )


def test_superseded_at_cannot_be_cleared(db):
    """Un-superseding would resurrect an old destination as the current one."""
    nour = _affiliate(db)
    first = _instapay(db, nour)
    db.flush()
    _instapay(db, nour, url="https://ipn.eg/S/other/instapay/9Yz")
    db.flush()

    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE payout_destination SET superseded_at = NULL WHERE id = :i"),
            {"i": first.id},
        )


# ── Masking ────────────────────────────────────────────────────────────────────


def test_masking_keeps_enough_to_recognise(db):
    """Somebody confirming a change has to be able to tell one destination from
    another. Masking everything would make the confirmation meaningless.
    """
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    masked = mask_destination(destination)
    assert masked["method"] == PayoutMethod.INSTAPAY
    assert masked["instapay_address_url"].endswith(INSTAPAY_URL[-VISIBLE_TAIL:])


def test_masking_hides_enough_to_be_useless_to_a_stranger(db):
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    masked = mask_destination(destination)
    assert INSTAPAY_URL not in masked["instapay_address_url"]
    assert "nour.mahmoud" not in masked["instapay_address_url"]


def test_a_bank_account_number_is_masked_to_its_last_digits(db):
    nour = _affiliate(db)
    destination = set_destination(
        db,
        nour,
        method=PayoutMethod.BANK,
        bank_name="CIB",
        bank_account_holder="Nour Mahmoud",
        bank_account_number=ACCOUNT_NUMBER,
    )
    db.flush()

    masked = mask_destination(destination)
    # Asserted against the constant, not a hardcoded count: if somebody widens
    # the window, this test should keep testing the rule rather than quietly
    # start testing a different one.
    assert masked["bank_account_number"].endswith(ACCOUNT_NUMBER[-VISIBLE_TAIL:])
    assert ACCOUNT_NUMBER not in masked["bank_account_number"]
    assert len(masked["bank_account_number"]) < len(ACCOUNT_NUMBER)


def test_a_phone_number_is_masked(db):
    nour = _affiliate(db)
    destination = _instapay(db, nour, phone="01001234567")
    db.flush()

    masked = mask_destination(destination)
    assert "01001234567" not in str(masked)
    assert masked["instapay_phone"].endswith("01001234567"[-VISIBLE_TAIL:])


def test_a_short_value_does_not_leak_by_being_short(db):
    """Masking that keeps the last four of a five-character value has masked
    nothing. The rule has to hold at the small end too.
    """
    nour = _affiliate(db)
    destination = set_destination(
        db,
        nour,
        method=PayoutMethod.BANK,
        bank_name="CIB",
        bank_account_holder="N",
        bank_account_number="1234",
    )
    db.flush()

    masked = mask_destination(destination)
    assert "1234" not in masked["bank_account_number"]


def test_the_account_holder_name_is_not_masked(db):
    """It is the part a person checks. Masking it would make the confirmation
    step useless, and it is not a credential.
    """
    nour = _affiliate(db)
    destination = set_destination(
        db,
        nour,
        method=PayoutMethod.BANK,
        bank_name="CIB",
        bank_account_holder="Nour Mahmoud",
        bank_account_number=ACCOUNT_NUMBER,
    )
    db.flush()

    assert mask_destination(destination)["bank_account_holder"] == "Nour Mahmoud"


# ── The audit trail must not itself be the leak ────────────────────────────────


def test_the_audit_record_never_contains_the_raw_address(db):
    """§6.4.4. The whole point of masking - and the test that proves the audit
    trail is not itself a way to read everybody's banking details.
    """
    nour = _affiliate(db)
    _instapay(db, nour)
    db.flush()

    everything = " ".join(
        str(row[0]) + str(row[1])
        for row in db.execute(text("SELECT before_json, after_json FROM audit_event"))
    )
    assert INSTAPAY_URL not in everything
    assert "nour.mahmoud" not in everything


def test_the_audit_record_never_contains_a_raw_account_number(db):
    nour = _affiliate(db)
    set_destination(
        db,
        nour,
        method=PayoutMethod.BANK,
        bank_name="CIB",
        bank_account_holder="Nour Mahmoud",
        bank_account_number=ACCOUNT_NUMBER,
    )
    db.flush()

    everything = " ".join(
        str(row[0]) + str(row[1])
        for row in db.execute(text("SELECT before_json, after_json FROM audit_event"))
    )
    assert ACCOUNT_NUMBER not in everything


def test_a_change_records_both_sides_masked(db):
    """What it changed from matters as much as what it changed to - and both
    have to be masked.
    """
    nour = _affiliate(db)
    _instapay(db, nour)
    db.flush()
    _instapay(db, nour, url="https://ipn.eg/S/other/instapay/9Yz")
    db.flush()

    before, after = db.execute(
        text(
            "SELECT before_json, after_json FROM audit_event "
            "WHERE action = 'payout_destination.changed' ORDER BY id DESC LIMIT 1"
        )
    ).one()
    assert before is not None
    assert INSTAPAY_URL not in str(before)
    assert "9Yz" not in str(after) or "…" in str(after)


def test_the_repr_does_not_leak(db):
    """A destination reaching a log line or a traceback must not carry the
    address with it.
    """
    nour = _affiliate(db)
    destination = _instapay(db, nour)
    db.flush()

    assert INSTAPAY_URL not in repr(destination)
    assert "01001234567" not in repr(destination)


# ── Each method needs its own details ──────────────────────────────────────────


def test_an_instapay_destination_requires_an_address(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="instapay_address_url"):
        set_destination(db, nour, method=PayoutMethod.INSTAPAY, instapay_phone="0100")


def test_a_bank_destination_requires_an_account_number(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="bank_account_number"):
        set_destination(db, nour, method=PayoutMethod.BANK, bank_name="CIB")


def test_a_wallet_destination_requires_a_phone(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="wallet_phone"):
        set_destination(db, nour, method=PayoutMethod.WALLET)


def test_an_unknown_method_is_refused(db):
    nour = _affiliate(db)
    with pytest.raises(ValueError, match="Unknown payout method"):
        set_destination(db, nour, method="carrier_pigeon")


def test_an_unknown_method_is_refused_by_the_database(db):
    nour = _affiliate(db)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text(
                "INSERT INTO payout_destination (affiliate_id, method) "
                "VALUES (:a, 'carrier_pigeon')"
            ),
            {"a": nour.id},
        )


def test_the_instapay_phone_is_optional(db):
    """§13.1 collects it as a fallback, not as a requirement."""
    nour = _affiliate(db)
    destination = set_destination(
        db, nour, method=PayoutMethod.INSTAPAY, instapay_address_url=INSTAPAY_URL
    )
    db.flush()
    assert destination.instapay_phone is None
