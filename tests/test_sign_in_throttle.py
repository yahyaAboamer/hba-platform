"""Sign-in throttling (security audit, October 2026).

Nothing stopped somebody trying password after password, or asking for reset
emails without end. These pin the limits and, as much, what they must not do:
reveal which addresses have accounts, let a stranger lock the owner out, or
keep the real owner out once they have proved who they are.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from app.core import throttle
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
WRONG = "not-the-password-at-all"
OWNER = BOOTSTRAP["email"]


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        yield test_client


@pytest.fixture()
def mailed(monkeypatch):
    """The reset links that would have been emailed, in order."""
    tokens: list[str] = []
    monkeypatch.setattr(
        "app.api.auth.password_reset_requested",
        lambda db, account, token: tokens.append(token),
    )
    return tokens


def _from(address: str) -> TestClient:
    """A visitor at a given public address."""
    return TestClient(app, client=(address, 50000))


def _login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _ask_for_reset(client, email):
    return client.post("/api/auth/password-reset/request", json={"email": email})


# ── Signing in ─────────────────────────────────────────────────────────────────


def test_repeated_wrong_passwords_pause_that_address(client):
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        assert _login(client, OWNER, WRONG).status_code == 401

    paused = _login(client, OWNER, BOOTSTRAP["password"])

    assert paused.status_code == 429, "the right password must not get through a pause"
    assert int(paused.headers["Retry-After"]) > 0
    assert "Try again" in paused.json()["detail"]


def test_a_successful_sign_in_clears_the_count(client):
    for _ in range(throttle.LOGIN_PER_PAIR.limit - 1):
        _login(client, OWNER, WRONG)
    assert _login(client, OWNER, BOOTSTRAP["password"]).status_code == 200

    for _ in range(throttle.LOGIN_PER_PAIR.limit - 1):
        _login(client, OWNER, WRONG)
    assert _login(client, OWNER, BOOTSTRAP["password"]).status_code == 200


def test_an_address_with_no_account_is_paused_the_same_way(client):
    """Otherwise the pause itself would say which addresses have accounts."""
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        assert _login(client, "nobody@example.com", WRONG).status_code == 401

    assert _login(client, "nobody@example.com", WRONG).status_code == 429


def test_one_paused_address_does_not_pause_another(client):
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        _login(client, "nobody@example.com", WRONG)

    assert _login(client, OWNER, BOOTSTRAP["password"]).status_code == 200


def test_a_stranger_cannot_pause_the_owner_signing_in_from_elsewhere(client):
    stranger, owner = _from("41.33.0.20"), _from("41.33.0.10")
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        _login(stranger, OWNER, WRONG)
    assert _login(stranger, OWNER, WRONG).status_code == 429

    assert _login(owner, OWNER, BOOTSTRAP["password"]).status_code == 200


def test_guessing_across_many_addresses_from_one_place_is_paused(client):
    for n in range(throttle.LOGIN_PER_SOURCE.limit):
        assert _login(client, f"guess{n}@example.com", WRONG).status_code == 401

    assert _login(client, "another@example.com", WRONG).status_code == 429


def test_guessing_one_account_from_many_places_meets_the_account_limit(client):
    per_place = throttle.LOGIN_PER_PAIR.limit
    places = -(-throttle.LOGIN_PER_ACCOUNT.limit // per_place)
    for place in range(places):
        visitor = _from(f"41.34.{place}.1")
        for _ in range(per_place):
            _login(visitor, OWNER, WRONG)

    assert _login(_from("41.35.0.1"), OWNER, WRONG).status_code == 429


def test_a_proxy_address_does_not_pool_every_visitor(client):
    """When the app sees the proxy rather than the visitor, limits keyed on
    that address would make one person's mistakes pause everybody."""
    proxy = _from("100.64.0.12")
    for _ in range(throttle.LOGIN_PER_PAIR.limit + 2):
        _login(proxy, OWNER, WRONG)

    assert _login(proxy, OWNER, BOOTSTRAP["password"]).status_code == 200


def test_an_unknown_address_costs_a_full_password_check(client, monkeypatch):
    """It used to return before hashing anything, so it answered quickly and
    the speed said the address had no account."""
    from app.services import auth

    checked = []
    real = auth.verify_password

    def counting(password, stored):
        checked.append(stored)
        return real(password, stored)

    monkeypatch.setattr(auth, "verify_password", counting)

    _login(client, "nobody@example.com", WRONG)

    assert checked, "no password check ran for an address with no account"


def test_attempts_sent_together_cannot_all_slip_under_the_limit():
    """Checking and counting are one step, so a burst gets exactly the limit."""
    limit = throttle.Throttle(limit=10, window=60)
    let_in = []
    start = threading.Barrier(40)

    def attempt():
        start.wait()
        if limit.acquire("one@example.com") == 0:
            let_in.append(1)

    threads = [threading.Thread(target=attempt) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(let_in) == 10


# ── Password resets ────────────────────────────────────────────────────────────


def test_reset_emails_from_one_place_are_capped_without_saying_so(client, mailed):
    for _ in range(throttle.RESET_PER_PAIR.limit + 2):
        assert _ask_for_reset(client, OWNER).status_code == 202

    assert len(mailed) == throttle.RESET_PER_PAIR.limit


def test_a_stranger_cannot_use_up_the_owners_reset_emails(client, mailed):
    stranger = _from("41.33.0.20")
    for _ in range(throttle.RESET_PER_PAIR.limit + 2):
        _ask_for_reset(stranger, OWNER)
    sent_to_stranger = len(mailed)

    _ask_for_reset(_from("41.33.0.10"), OWNER)

    assert len(mailed) == sent_to_stranger + 1, "the owner's own request was swallowed"


def test_reset_requests_from_one_place_are_paused(client, mailed):
    for n in range(throttle.RESET_PER_SOURCE.limit):
        assert _ask_for_reset(client, f"someone{n}@example.com").status_code == 202

    assert _ask_for_reset(client, "one-more@example.com").status_code == 429


def test_completing_a_reset_lets_the_owner_straight_back_in(client, mailed):
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        _login(client, OWNER, WRONG)
    assert _login(client, OWNER, BOOTSTRAP["password"]).status_code == 429

    _ask_for_reset(client, OWNER)
    fresh = "a-fresh-quiet-lantern-harbour"
    done = client.post("/api/auth/password-reset", json={"token": mailed[0], "password": fresh})
    assert done.status_code == 200, done.text

    assert _login(client, OWNER, fresh).status_code == 200


def test_reset_emails_stay_capped_when_the_visitor_address_is_unknown(client, mailed):
    """When only the proxy's address is visible, the per-address limits cannot
    apply - so a per-email cap stands in rather than the limit switching off."""
    proxy = _from("100.64.0.12")
    for _ in range(throttle.RESET_PER_ACCOUNT.limit + 2):
        assert _ask_for_reset(proxy, OWNER).status_code == 202

    assert len(mailed) == throttle.RESET_PER_ACCOUNT.limit


# ── Which address a visitor has (measured on staging, 11 October 2026) ────────


def _via_railway(real_ip: str, forwarded_for: str | None = None) -> TestClient:
    """A visitor as Railway delivers them: the connection from its private
    proxy, their own address in X-Real-IP, X-Forwarded-For ending in the edge
    node's address."""
    visitor = TestClient(app, client=("100.64.0.12", 50000))
    visitor.headers["X-Real-IP"] = real_ip
    if forwarded_for:
        visitor.headers["X-Forwarded-For"] = forwarded_for
    return visitor


def test_behind_railway_the_visitor_is_read_from_x_real_ip(client):
    stranger = _via_railway("41.33.0.20", "41.33.0.20, 79.127.178.81")
    owner = _via_railway("41.33.0.10", "41.33.0.10, 79.127.178.81")
    for _ in range(throttle.LOGIN_PER_PAIR.limit):
        _login(stranger, OWNER, WRONG)
    assert _login(stranger, OWNER, WRONG).status_code == 429

    # Same edge node, different visitor: not pooled with the stranger.
    assert _login(owner, OWNER, BOOTSTRAP["password"]).status_code == 200


def test_a_caller_cannot_rename_themselves_with_the_header(client):
    """Only Railway's proxy is believed. A direct caller sending X-Real-IP is
    still counted at its own address."""
    caller = _from("41.33.0.20")
    for n in range(throttle.LOGIN_PER_PAIR.limit):
        caller.headers["X-Real-IP"] = f"41.36.0.{n + 1}"
        _login(caller, OWNER, WRONG)
    caller.headers["X-Real-IP"] = "41.36.1.1"

    assert _login(caller, OWNER, WRONG).status_code == 429


def test_a_sign_in_records_the_visitors_own_address(client):
    from sqlalchemy import text

    from app.db import engine

    owner = _via_railway("41.33.0.10", "41.33.0.10, 79.127.178.81")
    assert _login(owner, OWNER, BOOTSTRAP["password"]).status_code == 200

    with engine.connect() as connection:
        recorded = connection.execute(
            text("SELECT ip_address FROM auth_session ORDER BY id DESC LIMIT 1")
        ).scalar_one()
    assert recorded == "41.33.0.10"
