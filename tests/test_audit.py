"""Append-only audit trail.

Spec sections 4.8, 16, and 17. The point of this module is that the audit
trail cannot be rewritten by anyone, including the application itself. The
database enforces that, so these tests attack the tables with raw SQL rather
than going through the ORM: if the guard only existed in Python it would pass
an ORM test and fail in reality.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app.models.audit import AuditEvent
from app.models.identity import UserAccount
from app.services.audit import SENSITIVE_FIELDS, mask_sensitive, record_audit


def _actor(db, email="actor@example.com"):
    user = UserAccount(email=email, password_hash="x", status="active")
    db.add(user)
    db.flush()
    return user


# ── Masking ────────────────────────────────────────────────────────────────────


def test_masking_hides_account_identifiers():
    masked = mask_sensitive(
        {
            "name": "Nour Adel",
            "instapay_address_url": "https://ipn.eg/nour@instapay",
            "bank_account_number": "EG380003000123456789",
            "wallet_phone": "01012345678",
        }
    )
    # Ordinary fields survive untouched — the audit trail is still useful.
    assert masked["name"] == "Nour Adel"
    # Secrets do not.
    assert "nour@instapay" not in str(masked["instapay_address_url"])
    assert "0003000123456789" not in str(masked["bank_account_number"])
    assert "1012345678" not in str(masked["wallet_phone"])


def test_masking_leaves_enough_to_recognise_a_value():
    """Enough to confirm which account was meant, never enough to reuse it."""
    masked = mask_sensitive({"bank_account_number": "EG380003000123456789"})
    assert masked["bank_account_number"] == "****6789"


def test_short_values_are_masked_entirely():
    # Four characters or fewer would otherwise be revealed in full.
    assert mask_sensitive({"password": "abcd"})["password"] == "****"
    assert mask_sensitive({"password": "ab"})["password"] == "****"


def test_masking_is_recursive_through_dicts_and_lists():
    masked = mask_sensitive(
        {
            "destination": {"bank_account_number": "EG3800030001234"},
            "history": [{"instapay_address_url": "https://ipn.eg/x@instapay"}],
        }
    )
    assert "0003000123" not in str(masked["destination"]["bank_account_number"])
    assert "x@instapay" not in str(masked["history"][0]["instapay_address_url"])


def test_every_declared_sensitive_field_is_masked():
    payload = {field: "SECRETVALUE12345" for field in SENSITIVE_FIELDS}
    masked = mask_sensitive(payload)
    for field in SENSITIVE_FIELDS:
        assert "SECRETVALUE12345" not in str(masked[field]), field


def test_unknown_but_obviously_sensitive_names_are_caught():
    """Matching only an exact list would leak the next field somebody adds."""
    masked = mask_sensitive(
        {
            "new_bank_account_number": "EG380003000123456789",
            "old_instapay_address": "https://ipn.eg/x@instapay",
            "shopify_api_key": "shpat_abcdef123456",
            "refresh_token": "1//0abcdefg",
        }
    )
    assert "0003000123456789" not in str(masked["new_bank_account_number"])
    assert "x@instapay" not in str(masked["old_instapay_address"])
    assert "abcdef123456" not in str(masked["shopify_api_key"])
    assert "0abcdefg" not in str(masked["refresh_token"])


def test_absent_values_stay_absent():
    """Masking a null would imply a value existed. It did not."""
    assert mask_sensitive({"bank_account_number": None})["bank_account_number"] is None


def test_numeric_secrets_are_masked_too():
    masked = mask_sensitive({"wallet_phone": 1012345678})
    assert masked["wallet_phone"] == "****5678"


def test_innocent_fields_are_not_over_masked():
    """Over-masking would make the audit trail useless for its actual job."""
    masked = mask_sensitive(
        {
            "account_status": "active",
            "display_name": "Sara",
            "month": "2026-08",
            "commission_rate_bp": 1000,
            "role": "content_manager",
        }
    )
    assert masked["account_status"] == "active"
    assert masked["display_name"] == "Sara"
    assert masked["month"] == "2026-08"
    assert masked["commission_rate_bp"] == 1000
    assert masked["role"] == "content_manager"


def test_deeply_nested_structures_do_not_recurse_forever():
    payload: dict = {"level": {}}
    node = payload["level"]
    for _ in range(60):
        node["level"] = {}
        node = node["level"]
    node["password"] = "should-not-crash"
    # Must return rather than exhaust the stack.
    assert isinstance(mask_sensitive(payload), dict)


# ── Recording ──────────────────────────────────────────────────────────────────


def test_record_audit_writes_a_row(db):
    actor = _actor(db, "a@example.com")
    event = record_audit(
        db,
        action="auth.login",
        subject=f"user:{actor.id}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"email": actor.email},
    )
    db.flush()
    assert event.id is not None
    assert event.action == "auth.login"
    assert event.created_at is not None


def test_record_audit_masks_before_storing(db):
    """Masking must happen on the way in, not on the way out.

    An unmasked value written to the table could never be removed afterwards,
    because the table is append-only.
    """
    actor = _actor(db, "b@example.com")
    event = record_audit(
        db,
        action="payout_destination.change",
        subject="affiliate:1",
        actor_id=actor.id,
        after={"bank_account_number": "EG380003000123456789"},
    )
    db.flush()
    assert "0003000123456789" not in str(event.after_json)


def test_record_audit_masks_the_before_state_too(db):
    actor = _actor(db, "c@example.com")
    event = record_audit(
        db,
        action="payout_destination.change",
        subject="affiliate:1",
        actor_id=actor.id,
        before={"instapay_address_url": "https://ipn.eg/old@instapay"},
        after={"instapay_address_url": "https://ipn.eg/new@instapay"},
    )
    db.flush()
    assert "old@instapay" not in str(event.before_json)
    assert "new@instapay" not in str(event.after_json)


def test_actor_email_is_recorded_alongside_the_id(db):
    """The email survives even if the account is later removed."""
    actor = _actor(db, "d@example.com")
    event = record_audit(
        db, action="x.y", subject="s", actor_id=actor.id, actor_email=actor.email
    )
    db.flush()
    assert event.actor_email == "d@example.com"


def test_a_reason_can_be_recorded(db):
    actor = _actor(db, "e@example.com")
    event = record_audit(
        db,
        action="payroll.reopen",
        subject="payroll:1:2026-08",
        actor_id=actor.id,
        reason="Rate corrected to 12% per July agreement",
    )
    db.flush()
    assert "12%" in event.reason


# ── Immutability, enforced by the database ─────────────────────────────────────


def test_audit_rows_cannot_be_updated(db):
    actor = _actor(db, "f@example.com")
    event = record_audit(db, action="x.y", subject="s", actor_id=actor.id)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(
            text("UPDATE audit_event SET action = 'tampered' WHERE id = :i"),
            {"i": event.id},
        )


def test_audit_rows_cannot_be_deleted(db):
    actor = _actor(db, "g@example.com")
    event = record_audit(db, action="x.y", subject="s", actor_id=actor.id)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM audit_event WHERE id = :i"), {"i": event.id})


def test_the_whole_table_cannot_be_truncated(db):
    """TRUNCATE bypasses row-level triggers, so it needs its own guard.

    Verified against Postgres before writing this: a BEFORE UPDATE OR DELETE
    row-level trigger does not fire on TRUNCATE, so without a statement-level
    guard one statement would erase the entire audit trail silently.
    """
    with pytest.raises(DatabaseError):
        db.execute(text("TRUNCATE audit_event"))


def test_deleting_an_actor_is_refused_while_audit_history_exists(db):
    """Append-only and ON DELETE SET NULL are incompatible.

    Nulling the actor would be an UPDATE, which the trigger blocks. The
    reference is therefore RESTRICT: an account that has done something is
    suspended, never deleted, which is what the spec calls for anyway.
    """
    actor = _actor(db, "h@example.com")
    record_audit(db, action="x.y", subject="s", actor_id=actor.id)
    db.flush()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM user_account WHERE id = :i"), {"i": actor.id})


def test_an_actor_with_no_audit_history_can_still_be_deleted(db):
    actor = _actor(db, "i@example.com")
    db.execute(text("DELETE FROM user_account WHERE id = :i"), {"i": actor.id})
    db.flush()
    remaining = db.execute(
        text("SELECT count(*) FROM user_account WHERE id = :i"), {"i": actor.id}
    ).scalar()
    assert remaining == 0


def test_the_schema_rebuilds_cleanly_from_empty(fresh_database, db):
    """Proves the fresh_database fixture works, and that migrations build from nothing.

    TRUNCATE is deliberately impossible here, so a test needing an empty
    database must rebuild the schema. Running that on every use also means the
    migration chain is exercised from zero continuously, rather than only when
    someone remembers to try it.
    """
    tables = db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
    ).scalars().all()
    assert "audit_event" in tables
    assert "user_account" in tables
    assert db.execute(text("SELECT count(*) FROM audit_event")).scalar() == 0

    # The guards exist on the rebuilt schema, not only on the original one.
    with pytest.raises(DatabaseError):
        db.execute(text("TRUNCATE audit_event"))
