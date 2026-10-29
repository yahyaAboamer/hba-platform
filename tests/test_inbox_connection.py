"""The inbox's two connections in Settings, and who may be messaged (ADR 0059).

The same rules as the Shopify connection: saved encrypted, tried against the
provider before saving, never shown, logged or audited - and refused details
leave what is in use as it was. Neither Meta nor Shopify is called: the check
is replaced. Every key and number here is made up.
"""

import json

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.shared.models.audit import AuditEvent
from app.modules.inbox.models import InboxConnection, ShopifyTagsConnection
from app.modules.inbox.services import connection, sending
from app.modules.inbox.services.meta import MetaError, NumberInfo
from app.shared.services.shopify.client import ShopifyError

ACCESS = "EAAG-made-up-access-key-0000a1b2"
APP_SECRET = "made-up-app-secret-000000009f3c"
CHECK_WORD = "made-up-check-word-0001"
NUMBER_ID = "100200300400500"
ACCOUNT_ID = "777888999000111"

MAIN_CLIENT_ID = "main-app-client-id-0000aaaa"
TAGS_CLIENT_ID = "tags-app-client-id-0000bbbb"
TAGS_SECRET = "made-up-tags-secret-0000c7d8"


@pytest.fixture()
def protected(monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "hba-test.myshopify.com")
    monkeypatch.setattr("app.config.settings.shopify_client_id", MAIN_CLIENT_ID)
    monkeypatch.setattr("app.config.settings.shopify_client_secret", "main-app-secret")
    monkeypatch.setattr("app.config.settings.shopify_access_token", "")


def _answers(*_args):
    return NumberInfo("+20 100 555 0100", "HBA Wear", "GREEN")


def _refuses(*_args):
    raise MetaError("WhatsApp did not accept the access key (code 190)", kind="auth", code=190)


def _save(db, checker=_answers, **changes):
    values = dict(
        phone_number_id=NUMBER_ID,
        business_account_id=ACCOUNT_ID,
        access_token=ACCESS,
        app_secret=APP_SECRET,
        verify_token=CHECK_WORD,
    )
    values.update(changes)
    return connection.save_whatsapp(
        db, actor_id=None, actor_email="owner@example.com", checker=checker, **values
    )


def _save_tags(db, checker=lambda *args: {"write_orders", "read_orders"}, **changes):
    values = dict(client_id=TAGS_CLIENT_ID, client_secret=TAGS_SECRET)
    values.update(changes)
    return connection.save_tags(
        db, actor_id=None, actor_email="owner@example.com", checker=checker, **values
    )


# ── WhatsApp ──────────────────────────────────────────────────────────────────


def test_with_nothing_saved_whatsapp_is_not_connected(db, protected):
    assert connection.whatsapp(db) is None
    described = connection.describe_whatsapp(db)
    assert described["connected"] is False
    assert described["sending_enabled"] is False
    assert described["problem"] is None


def test_keys_meta_answers_are_saved_encrypted_and_never_shown(db, protected):
    described = _save(db)
    row = db.get(InboxConnection, 1)
    stored = " ".join(
        [row.access_token_encrypted, row.app_secret_encrypted, row.verify_token_encrypted]
    )
    shown = json.dumps(described)
    for secret in (ACCESS, APP_SECRET, CHECK_WORD):
        assert secret not in stored
        assert secret not in shown
    assert described["connected"] is True
    assert described["display_number"] == "+20 100 555 0100"
    assert described["verified_name"] == "HBA Wear"
    assert described["access_token_hint"] == "a1b2"
    assert described["app_secret_hint"] == "9f3c"
    assert "verify_token_hint" not in described

    in_use = connection.whatsapp(db)
    assert (in_use.access_token, in_use.app_secret, in_use.verify_token) == (
        ACCESS, APP_SECRET, CHECK_WORD,
    )
    assert ACCESS not in repr(in_use)


def test_a_new_connection_starts_with_sending_off(db, protected):
    assert _save(db)["sending_enabled"] is False


def test_refused_keys_are_not_saved_and_the_ones_in_use_stay(db, protected):
    _save(db)
    with pytest.raises(connection.NotSaved) as refused:
        _save(db, checker=_refuses, access_token="EAAG-a-wrong-key-zzzz9999")
    assert str(refused.value) == (
        "WhatsApp did not accept these details (WhatsApp did not accept the "
        "access key (code 190)). The connection in use has not changed."
    )
    assert "a-wrong-key" not in str(refused.value)
    assert connection.whatsapp(db).access_token == ACCESS


def test_a_secret_left_blank_keeps_the_saved_one(db, protected):
    _save(db)
    asked = []

    def checker(access_token, phone_number_id, business_account_id):
        asked.append(access_token)
        return _answers()

    _save(db, checker=checker, access_token="EAAG-a-newer-access-key-7e7e", app_secret="", verify_token="")
    in_use = connection.whatsapp(db)
    assert asked == ["EAAG-a-newer-access-key-7e7e"]
    assert in_use.access_token == "EAAG-a-newer-access-key-7e7e"
    assert (in_use.app_secret, in_use.verify_token) == (APP_SECRET, CHECK_WORD)


def test_the_first_save_needs_all_three_secrets(db, protected):
    asked = []
    with pytest.raises(connection.NotSaved, match="Enter the access key, the app secret"):
        _save(db, checker=lambda *args: asked.append(args), app_secret="")
    assert asked == []
    assert db.get(InboxConnection, 1) is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"phone_number_id": "abc"}, "number ID is a number"),
        ({"phone_number_id": ""}, "number ID is a number"),
        ({"business_account_id": "12/34"}, "business account ID is a number"),
        ({"access_token": "two words"}, "doesn't look like a WhatsApp access key"),
        ({"access_token": "x" * 2000}, "doesn't look like a WhatsApp access key"),
        ({"app_secret": "a-“smart”-quote-1234"}, "doesn't look like an app secret"),
    ],
)
def test_details_that_cannot_be_right_are_refused_before_asking(db, protected, changes, message):
    asked = []
    with pytest.raises(connection.NotSaved, match=message):
        _save(db, checker=lambda *args: asked.append(args), **changes)
    assert asked == []


def test_nothing_is_saved_without_an_encryption_key(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.settings_encryption_key", "")
    with pytest.raises(connection.NotSaved, match="SETTINGS_ENCRYPTION_KEY is not set"):
        _save(db)
    assert db.scalar(select(InboxConnection)) is None


def test_keys_this_server_cannot_read_say_so_and_need_all_three_again(db, protected, monkeypatch):
    _save(db)
    monkeypatch.setattr(
        "app.config.settings.settings_encryption_key", Fernet.generate_key().decode()
    )
    assert connection.whatsapp(db) is None
    described = connection.describe_whatsapp(db)
    assert described["connected"] is False
    assert "cannot be read with this server's key" in described["problem"]
    with pytest.raises(connection.NotSaved, match="all three are needed again"):
        _save(db, app_secret="", verify_token="")
    _save(db)
    assert connection.whatsapp(db).access_token == ACCESS


def test_the_audit_trail_records_the_number_and_no_key(db, protected):
    _save(db)
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "inbox.whatsapp_saved"))
    recorded = json.dumps([event.before_json, event.after_json])
    assert event.after_json == {"phone_number_id": NUMBER_ID}
    for secret in (ACCESS, APP_SECRET, CHECK_WORD):
        assert secret not in recorded


# ── The sending switch ────────────────────────────────────────────────────────


def _switch(db, enabled):
    return connection.set_sending(db, enabled, actor_id=None, actor_email="owner@example.com")


def test_sending_cannot_be_turned_on_before_whatsapp_is_connected(db, protected):
    with pytest.raises(connection.NotSaved, match="Connect WhatsApp before"):
        _switch(db, True)


def test_turning_sending_on_and_off_is_audited(db, protected):
    _save(db)
    assert _switch(db, True)["sending_enabled"] is True
    assert _switch(db, True)["sending_enabled"] is True
    assert _switch(db, False)["sending_enabled"] is False
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.action == "inbox.sending_changed").order_by(AuditEvent.id)
    ).all()
    assert [event.after_json for event in events] == [{"sending": True}, {"sending": False}]


def test_replacing_a_key_keeps_the_switch_but_a_different_number_resets_it(db, protected):
    _save(db)
    _switch(db, True)
    assert _save(db, access_token="EAAG-a-newer-access-key-7e7e")["sending_enabled"] is True
    assert _save(db, phone_number_id="999888777666555")["sending_enabled"] is False


# ── Who may be messaged ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "read"),
    [
        ("01005550188", "201005550188"),
        ("+20 100 555 0188", "201005550188"),
        ("0020 100-555-0188", "201005550188"),
        ("201005550188", "201005550188"),
        ("1005550188", "201005550188"),
        ("01505550188", "201505550188"),
        # The 0 of 010... kept after +20 (order #31857): Shopify's own page
        # shows it tidied, its API returns it as typed.
        ("+2001009156440", "201009156440"),
        ("+20 0100 555 0188", "201005550188"),
        ("00200100 555 0188", "201005550188"),
        ("2001005550188", "201005550188"),
        ("+200225550188", None),   # the same slip on a landline stays refused
        ("0225550188", None),      # a Cairo landline
        ("0100555018", None),      # one digit short
        ("010055501888", None),    # one digit long
        ("+44 7700 900123", None),  # not Egyptian
        ("", None),
        (None, None),
    ],
)
def test_how_a_phone_number_on_an_order_is_read(raw, read):
    assert sending.egyptian_mobile(raw) == read


def test_nobody_is_messaged_until_whatsapp_is_connected_and_sending_is_on(db, protected, monkeypatch):
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", True)
    assert sending.refusal(db, "201005550188") == sending.NOT_CONNECTED
    _save(db)
    assert sending.refusal(db, "201005550188") == sending.SENDING_OFF
    _switch(db, True)
    assert sending.refusal(db, "201005550188") is None


def test_a_server_not_told_it_may_message_customers_messages_only_test_numbers(
    db, protected, monkeypatch
):
    """A staging server holding real keys still cannot write to a customer.

    Staging runs with APP_ENV=production, so that is set here too: it must
    make no difference. Only the inbox's own switch does."""
    _save(db)
    _switch(db, True)
    monkeypatch.setattr("app.config.settings.app_env", "production")
    monkeypatch.setattr("app.config.settings.inbox_send_to_customers", False)
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "")
    assert sending.refusal(db, "201005550188") == sending.NOT_A_TEST_NUMBER
    monkeypatch.setattr("app.config.settings.inbox_test_numbers", "0100 555 0188, +201105550199")
    assert sending.refusal(db, "201005550188") is None
    assert sending.refusal(db, "201105550199") is None
    assert sending.refusal(db, "201205550177") == sending.NOT_A_TEST_NUMBER
    assert connection.describe_whatsapp(db)["test_numbers_only"] is True


def test_customers_are_not_messaged_unless_the_server_was_told_it_may():
    """The default, with nothing set: off."""
    from app.config import Settings

    assert Settings.model_fields["inbox_send_to_customers"].default is False


# ── Shopify, for tags ─────────────────────────────────────────────────────────


def test_the_second_app_is_saved_encrypted_when_it_may_change_orders(db, protected):
    described = _save_tags(db)
    row = db.get(ShopifyTagsConnection, 1)
    assert TAGS_SECRET not in row.client_secret_encrypted
    assert TAGS_SECRET not in json.dumps(described)
    assert described["connected"] is True
    assert described["shop_domain"] == "hba-test.myshopify.com"
    assert described["client_secret_hint"] == "c7d8"

    app = connection.tags_app(db)
    assert (app.shop_domain, app.client_id, app.client_secret) == (
        "hba-test.myshopify.com", TAGS_CLIENT_ID, TAGS_SECRET,
    )
    assert TAGS_SECRET not in repr(app)


def test_the_app_that_reads_money_is_never_saved_as_the_one_that_writes(db, protected):
    """ADR 0059, point 11, and ADR 0015: the money connection stays read-only."""
    asked = []
    with pytest.raises(connection.NotSaved, match="must stay read-only"):
        _save_tags(db, checker=lambda *args: asked.append(args), client_id=MAIN_CLIENT_ID)
    assert asked == []
    assert db.get(ShopifyTagsConnection, 1) is None


def test_an_app_that_may_not_change_orders_is_refused(db, protected):
    with pytest.raises(connection.NotSaved, match="it lacks write_orders"):
        _save_tags(db, checker=lambda *args: {"read_orders", "read_customers"})
    assert db.get(ShopifyTagsConnection, 1) is None


def test_credentials_shopify_refuses_leave_the_saved_app_as_it_was(db, protected):
    _save_tags(db)

    def refuses(*_args):
        raise ShopifyError("Shopify token exchange failed with 401")

    with pytest.raises(connection.NotSaved) as refused:
        _save_tags(db, checker=refuses, client_secret="a-wrong-secret-zzzz9999")
    assert "token exchange failed with 401" in str(refused.value)
    assert "a-wrong-secret" not in str(refused.value)
    assert connection.tags_app(db).client_secret == TAGS_SECRET


def test_the_second_app_needs_shopify_connected_first(db, protected, monkeypatch):
    monkeypatch.setattr("app.config.settings.shopify_shop_domain", "")
    with pytest.raises(connection.NotSaved, match="Connect Shopify first"):
        _save_tags(db)


def test_the_tags_audit_records_that_it_was_saved_and_no_secret(db, protected):
    _save_tags(db)
    event = db.scalar(
        select(AuditEvent).where(AuditEvent.action == "inbox.tags_connection_saved")
    )
    assert (event.before_json, event.after_json) == ({"saved": False}, {"saved": True})
