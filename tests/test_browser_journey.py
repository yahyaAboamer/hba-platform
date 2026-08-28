"""The platform driven the way a browser drives it, with no shortcuts.

Every fault the business hit in production was invisible to the rest of this
suite, and they were all the same kind of invisible: **the tests knew things a
browser does not.**

- The other API tests take the CSRF token from the body of the login response
  and set it as a header for the rest of the file. A browser does not do that.
  It has a cookie jar, and whatever is not in the jar does not exist.
- They call handlers directly, so a handler registered to the wrong function
  still passed.
- They never close a tab, so a token kept in `sessionStorage` looked permanent.
- They never meet a session that was created before today's deploy.

So the client here is deliberately impoverished. It holds a cookie jar and
nothing else, and it derives the CSRF header from that jar exactly as
`frontend/src/lib/api.ts` derives it from `document.cookie`. If a real browser
could not do it, this cannot do it either.

**The rule for this file: never read a token out of a response body.** That one
shortcut is what hid a bug that made every write in the platform fail.
"""

import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from PIL import Image

from app.main import app

OWNER = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}
PASSWORD = "a-long-enough-password"
AUGUST = "2026-08"


class Browser:
    """A client that knows only what a browser knows.

    The CSRF header comes from the cookie jar, never from a response body -
    which is the whole point. `api.ts` reads `document.cookie`; this reads the
    same cookie out of the jar.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client

    @property
    def csrf(self) -> str | None:
        return self.client.cookies.get("hba_csrf")

    def get(self, path: str):
        return self.client.get(path)

    def _write(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        token = self.csrf
        # A browser sends no header when it has nothing to send, and finds out
        # the hard way. So does this.
        if token:
            headers["X-CSRF-Token"] = token
        return getattr(self.client, method)(path, headers=headers, **kwargs)

    def post(self, path: str, **kwargs):
        return self._write("post", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._write("put", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self._write("patch", path, **kwargs)

    def close_the_tab(self) -> "Browser":
        """What survives closing a tab: cookies, and nothing else.

        `sessionStorage` is gone. Anything the page was holding in memory is
        gone. The cookie jar is the same jar, because the cookies are
        persistent - which is exactly the state that stranded a live session
        with no way to write.
        """
        fresh = TestClient(app)
        fresh.cookies = self.client.cookies
        return Browser(fresh)


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture()
def browser(fresh_database):
    with TestClient(app) as client:
        yield Browser(client)


def _sign_up(browser: Browser) -> Browser:
    """Set the platform up, as the first administrator would from the screen."""
    created = browser.post("/api/auth/bootstrap", json=OWNER)
    assert created.status_code == 201, created.text
    return browser


# -- The state that broke everything -----------------------------------------


def test_a_session_from_before_today_can_still_write(browser):
    """The failure the business hit twice, and the one a fix missed.

    Their session was created before the CSRF cookie existed, so the browser
    held a valid session cookie and no token. Reads worked, the screen showed a
    signed-in administrator, and every write was refused - and a fix that only
    issued the cookie at sign-in could not help a session that was already
    open.

    Simulated by deleting the cookie a browser would not yet have, which is
    exactly what an older session looks like.
    """
    _sign_up(browser)
    browser.client.cookies.delete("hba_csrf")
    assert browser.csrf is None, "the state under test is *no token at all*"

    # One page load is all a person does. It has to be enough.
    assert browser.get("/api/auth/me").status_code == 200

    assert browser.csrf, "loading the page must leave the browser able to write"
    invited = browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )
    assert invited.status_code == 201, invited.text


def test_a_returning_tab_can_write_without_signing_in_again(browser):
    """Closing the tab keeps the cookies and loses everything else."""
    _sign_up(browser)
    returning = browser.close_the_tab()

    assert returning.get("/api/auth/me").status_code == 200
    invited = returning.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )
    assert invited.status_code == 201, invited.text


def test_signing_out_actually_ends_the_session(browser):
    """It appeared to do nothing, then appeared to bounce to the home page.

    Both were the same thing: logout is a write, the write was refused, and the
    screen redirected somebody who was still signed in back to where signed-in
    people go.
    """
    _sign_up(browser)
    returning = browser.close_the_tab()

    out = returning.post("/api/auth/logout")
    assert out.status_code == 200, out.text
    assert returning.get("/api/auth/me").status_code == 401


def test_signing_out_works_even_with_no_token_at_all(browser):
    """A person who cannot sign out is a worse outcome than a forced sign-out.

    Logout is the one write where refusing costs more than it protects: the
    attack it prevents is being signed out of your own session, and the failure
    it causes is being unable to leave one on a shared computer.
    """
    _sign_up(browser)
    browser.client.cookies.delete("hba_csrf")

    out = browser.post("/api/auth/logout")

    assert out.status_code == 200, out.text
    assert browser.get("/api/auth/me").status_code == 401


def test_a_write_with_a_wrong_token_is_still_refused(browser):
    """The control still has to work. Healing a missing token must not become
    accepting any token.
    """
    _sign_up(browser)

    refused = browser.client.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
        headers={"X-CSRF-Token": "not-the-right-token"},
    )

    assert refused.status_code == 401


def test_the_screen_is_told_the_link_was_emailed(browser, monkeypatch):
    """It said "email is not switched on" on a platform where it was.

    `invitation_sent` returned nothing at all, so the caller's
    `is not None` check was false every time. The maintainer was told to send
    the link by hand while the platform quietly emailed it anyway - which is
    the worst of both: an instruction to do redundant work, and no reason to
    trust anything the screen says about delivery.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com", raising=False)
    monkeypatch.setattr(
        settings, "mail_from_address", "hba@example.com", raising=False
    )
    _sign_up(browser)

    invited = browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )

    assert invited.status_code == 201, invited.text
    assert invited.json()["emailed"] is True


def test_the_screen_is_told_when_it_was_not(browser, monkeypatch):
    """The other half, and the reason the flag exists.

    With no credentials the platform records what it would have sent and sends
    nothing. Saying so is what tells the maintainer the copyable link is the
    only way in - which on a development machine it always is.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    _sign_up(browser)

    invited = browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )

    assert invited.json()["emailed"] is False
    # The link still comes back. It is the only way in when nothing is sent.
    assert invited.json()["token"]


def test_an_invitation_always_queues_a_notification(browser):
    """Whether or not it can be delivered. The outbox is the record of what was
    owed, and a platform with no credentials still owes it.
    """
    from app.db import SessionLocal
    from app.models.notifications import NotificationOutbox

    _sign_up(browser)
    browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )

    with SessionLocal() as session:
        rows = list(session.scalars(select(NotificationOutbox)))

    assert [row.event for row in rows] == ["invitation.sent"]
    assert rows[0].recipient_email == "nour@example.com"


# -- The whole journey, as two people --------------------------------------


def test_the_maintainer_and_the_model_can_get_all_the_way_through(browser):
    """Every step somebody actually takes, in order, through the cookie jar.

    This is the shape of test that was missing. Each of these steps existed and
    was covered; what was not covered was doing them one after another as a
    browser, which is the only way the wiring between them gets exercised.
    """
    _sign_up(browser)

    # 1. Invite a model. The token comes back for the copy-link fallback; the
    #    browser is not allowed to use it for anything else.
    invited = browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]

    # 2. She opens the link in her own browser and chooses a password.
    with TestClient(app) as hers:
        model = Browser(hers)
        accepted = model.post(
            "/api/auth/invitations/accept",
            json={"token": token, "display_name": "Nour", "password": PASSWORD},
        )
        assert accepted.status_code == 201, accepted.text
        assert model.csrf, "accepting an invitation has to leave her able to write"

        # 3. She applies, with her own details and her own payout destination.
        applied = model.post(
            "/api/applications",
            json={
                "name": "Nour Mahmoud",
                "phone": "010 1234 5678",
                "code": "NOUR10",
                "payout_method": "instapay",
                "instapay_address_url": "https://ipn.eg/S/nour/instapay/8Xk2Qp",
                "instapay_phone": "01001234567",
            },
        )
        assert applied.status_code == 201, applied.text

        # 4. And she can see her own record straight away.
        assert model.get("/api/me").status_code == 200
        assert model.get("/api/me/months").status_code == 200

    # 5. The maintainer finds her waiting.
    roster = browser.get("/api/affiliates").json()["affiliates"]
    nour = next(row for row in roster if row["name"] == "Nour Mahmoud")
    assert nour["status"] == "pending"

    # 6. Sets what she is paid - which §6.5 keeps off her application form.
    terms = browser.post(
        f"/api/affiliates/{nour['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    assert terms.status_code == 201, terms.text

    # 7. Approving needs a code Shopify has confirmed (§10.4). Without one it
    #    refuses, and that refusal is the gate working.
    refused = browser.patch(f"/api/affiliates/{nour['id']}", json={"status": "active"})
    assert refused.status_code == 400, "an unverified code must block approval"

    _confirm_code(nour["id"], "NOUR10")

    approved = browser.patch(f"/api/affiliates/{nour['id']}", json={"status": "active"})
    assert approved.status_code == 200, approved.text

    # 8. An order arrives, and payroll can be run and agreed.
    _order(nour["id"], "1", 1_000_000)

    payroll = browser.get(f"/api/payroll/{AUGUST}").json()
    mine = next(r for r in payroll["affiliates"] if r["affiliate_id"] == nour["id"])
    assert mine["is_payable"] is True, mine["blockers"]

    agreed = browser.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [nour["id"]], "preview": False},
    )
    assert agreed.status_code == 200, agreed.text
    assert agreed.json()["results"][0]["approved"] is True

    # 9. A payment, with the screenshot §14 asks for.
    balance = browser.get(f"/api/payments/{AUGUST}").json()["affiliates"]
    owed = next(r for r in balance if r["affiliate_id"] == nour["id"])

    uploaded = browser.post(
        f"/api/affiliates/{nour['id']}/proof",
        files={"file": ("transfer.png", _screenshot(), "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text

    paid = browser.post(
        "/api/payments",
        json={
            "affiliate_id": nour["id"],
            "amount_piastres": owed["balance_piastres"],
            "allocations": [
                {
                    "payroll_snapshot_id": owed["payroll_snapshot_id"],
                    "piastres": owed["balance_piastres"],
                }
            ],
            "reference": "IPN-1",
            "proof_file_id": uploaded.json()["proof_file_id"],
        },
    )
    assert paid.status_code == 201, paid.text

    # 10. And she can see all of it, on her own screens, in her own browser.
    with TestClient(app) as hers:
        model = Browser(hers)
        model.post("/api/auth/login", json={"email": "nour@example.com", "password": PASSWORD})

        month = model.get(f"/api/me/earnings/{AUGUST}").json()
        assert month["state"] == "agreed"
        assert month["amount_piastres"] == 100_000

        payments = model.get("/api/me/payments").json()
        assert payments["outstanding_piastres"] == 0
        assert payments["payments"][0]["has_proof"] is True

        receipt = model.get(f"/api/me/payments/{payments['payments'][0]['id']}/proof")
        assert receipt.status_code == 200
        assert receipt.headers["content-type"] == "image/jpeg"


def test_a_model_cannot_reach_the_maintainers_screens(browser):
    """§6.1's two gates, driven as two browsers rather than asserted."""
    _sign_up(browser)
    invited = browser.post(
        "/api/auth/invitations",
        json={"email": "nour@example.com", "role": "affiliate"},
    )

    with TestClient(app) as hers:
        model = Browser(hers)
        model.post(
            "/api/auth/invitations/accept",
            json={
                "token": invited.json()["token"],
                "display_name": "Nour",
                "password": PASSWORD,
            },
        )

        for path in (
            "/api/affiliates",
            f"/api/payroll/{AUGUST}",
            f"/api/payments/{AUGUST}",
            "/api/staff",
            "/api/operations/attention",
        ):
            assert model.get(path).status_code == 403, path


# -- Fixtures written straight in -------------------------------------------


def _screenshot() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 600), (240, 240, 250)).save(out, format="PNG")
    return out.getvalue()


def _confirm_code(affiliate_id: int, code: str) -> None:
    """Mark her code confirmed, the way a Shopify check would.

    Done directly because §10.4's verification calls Shopify, and this file is
    about the journey rather than about that call.
    """
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE discount_code_period SET shopify_verified_at = now(), "
                "start_month = '2025-01' WHERE affiliate_id = :a AND upper(code) = :c"
            ),
            {"a": affiliate_id, "c": code.upper()},
        )


def _order(affiliate_id: int, order_id: str, base: int, month: str = AUGUST) -> None:
    from sqlalchemy import text

    from app.db import engine

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO order_index (shopify_order_id, order_number, placed_at, "
                "business_month, discount_codes, subtotal_piastres, total_piastres, "
                "shipping_piastres, tax_piastres, currency) "
                "VALUES (:i, :n, now(), :m, ARRAY['NOUR10'], :b, :b, 0, 0, 'EGP')"
            ),
            {"i": order_id, "n": f"#{order_id}", "m": month, "b": base},
        )
        connection.execute(
            text(
                "INSERT INTO attributed_order (shopify_order_id, affiliate_id, "
                "business_month, commission_base_piastres, commission_state) "
                "VALUES (:i, :a, :m, :b, 'earned')"
            ),
            {"i": order_id, "a": affiliate_id, "m": month, "b": base},
        )
