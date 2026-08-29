"""Proof, adjustments, and recording payments over HTTP.

Phase 7 Tasks 4-6. §14, §11.5, ADR 0017, ADR 0026.

**ADR 0017 is a decision to re-read before changing anything here.** The proof
screenshot is shown to the affiliate because the business asked for it, knowing
it may expose HBA's banking details to about twenty people. The mitigations
below — EXIF stripped, size capped, owner-only, re-encoded — are the conditions
under which that risk was accepted, not niceties that came with the feature.
"""

import io
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app
from app.services.proof import MAX_UPLOAD_BYTES, ProofRejected, sanitise

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "a-long-enough-password",
}
AUGUST = "2026-08"
SEPTEMBER = "2026-09"


@pytest.fixture(autouse=True)
def _go_live(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "go_live_month", "2026-01", raising=False)


@pytest.fixture()
def client(fresh_database):
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _screenshot(size=(1200, 2400), exif=True) -> bytes:
    """A PNG standing in for a phone screenshot, with metadata attached."""
    image = Image.new("RGB", size, (240, 240, 250))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "HBA-Phone"  # Make
        data[0x9286] = "sent from Cairo"  # UserComment
        image.save(out, format="JPEG", exif=data)
    else:
        image.save(out, format="PNG")
    return out.getvalue()


def _make_account(email: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Model') RETURNING id"
            ),
            {"e": email, "p": hash_password("a-long-enough-password")},
        ).scalar_one()


def _affiliate(client, name="Nour", email="nour@example.com") -> dict:
    body = {"user_account_id": _make_account(email), "name": name}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    affiliate = response.json()
    client.post(
        f"/api/affiliates/{affiliate['id']}/compensation",
        json={
            "start_month": "2026-01",
            "compensation_type": "commission",
            "commission_rate_bp": 1000,
        },
    )
    return affiliate


def _order(affiliate_id, order_id, base, *, month=AUGUST):
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


def _owed(client, affiliate, month=AUGUST, base=2_000_000) -> int:
    """An approved month owing E£2,000. Returns the snapshot id."""
    _order(affiliate["id"], f"{affiliate['id']}-{month}", base, month=month)
    client.post(
        f"/api/payroll/{month}/approve",
        json={"affiliate_ids": [affiliate["id"]], "preview": False},
    )
    with engine.begin() as connection:
        return connection.execute(
            text(
                "SELECT active_snapshot_id FROM payroll_month "
                "WHERE affiliate_id = :a AND month = :m"
            ),
            {"a": affiliate["id"], "m": month},
        ).scalar_one()


# ── Sanitising proof ───────────────────────────────────────────────────────────


def test_exif_does_not_survive_upload(db):
    """A screenshot carries device and, on a phone, location. The image is
    **re-encoded** rather than filtered, so nothing survives by being in a
    metadata block nobody thought to remove.
    """
    raw = _screenshot(exif=True)
    assert Image.open(io.BytesIO(raw)).getexif(), "the fixture had metadata"

    cleaned, content_type = sanitise(raw)

    assert not Image.open(io.BytesIO(cleaned)).getexif()
    assert b"sent from Cairo" not in cleaned
    assert content_type == "image/jpeg"


def test_a_large_screenshot_is_shrunk(db):
    """§14's storage budget assumes ~200 KB a screenshot."""
    cleaned, _ = sanitise(_screenshot(size=(4000, 6000), exif=False))

    width, height = Image.open(io.BytesIO(cleaned)).size
    assert max(width, height) <= 1600
    assert len(cleaned) < 500_000


def test_a_file_that_is_not_an_image_is_refused(db):
    """Re-encoding is what makes this a fact rather than a guess at the
    extension - an executable renamed to .jpg never reaches storage.
    """
    with pytest.raises(ProofRejected, match="not an image"):
        sanitise(b"MZ\x90\x00\x03" + b"\x00" * 500)


def test_an_enormous_file_is_refused_before_it_is_decoded(db):
    """An uncapped upload is an uncapped bill, and decoding a huge file to find
    out it is huge is the expensive way to refuse it.
    """
    with pytest.raises(ProofRejected, match="limit is"):
        sanitise(b"\x00" * (MAX_UPLOAD_BYTES + 1))


def test_an_empty_file_is_refused(db):
    with pytest.raises(ProofRejected):
        sanitise(b"")


def test_a_transparent_screenshot_does_not_come_out_black(db):
    """JPEG has no alpha channel, so a PNG with transparency would otherwise
    get a black background wherever it was see-through.
    """
    image = Image.new("RGBA", (400, 400), (255, 255, 255, 0))
    out = io.BytesIO()
    image.save(out, format="PNG")

    cleaned, _ = sanitise(out.getvalue())

    assert Image.open(io.BytesIO(cleaned)).getpixel((10, 10)) == (255, 255, 255)


# ── Proof over HTTP ────────────────────────────────────────────────────────────


def test_uploading_proof_returns_an_id_to_record_with(client):
    """Uploaded **before** the payment, because payment_transaction is
    append-only and attaching later would mean updating a row the trigger
    refuses.
    """
    affiliate = _affiliate(client)

    response = client.post(
        f"/api/affiliates/{affiliate['id']}/proof",
        files={"file": ("proof.jpg", _screenshot(), "image/jpeg")},
    )

    assert response.status_code == 201
    assert len(response.json()["proof_file_id"]) == 64


def test_the_same_screenshot_twice_is_stored_once(client):
    """Keyed by content hash. Somebody unsure whether the first attempt worked
    uploads it again, and that should not double the storage.
    """
    affiliate = _affiliate(client)
    raw = _screenshot()

    first = client.post(
        f"/api/affiliates/{affiliate['id']}/proof",
        files={"file": ("p.jpg", raw, "image/jpeg")},
    ).json()
    second = client.post(
        f"/api/affiliates/{affiliate['id']}/proof",
        files={"file": ("p.jpg", raw, "image/jpeg")},
    ).json()

    assert first["proof_file_id"] == second["proof_file_id"]
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM proof_file")).scalar() == 1


def test_a_payment_can_be_recorded_with_its_proof(client):
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    proof = client.post(
        f"/api/affiliates/{affiliate['id']}/proof",
        files={"file": ("p.jpg", _screenshot(), "image/jpeg")},
    ).json()["proof_file_id"]

    response = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 200_000}],
            "proof_file_id": proof,
        },
    )

    assert response.status_code == 201
    assert response.json()["has_proof"] is True


def test_proof_is_served_only_for_the_payment_it_belongs_to(client):
    """§14. A URL is not a permission - the check is against the session, in
    the same place as every other permission check.
    """
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    snapshot = _owed(client, nour)
    proof = client.post(
        f"/api/affiliates/{nour['id']}/proof",
        files={"file": ("p.jpg", _screenshot(), "image/jpeg")},
    ).json()["proof_file_id"]
    payment = client.post(
        "/api/payments",
        json={
            "affiliate_id": nour["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 200_000}],
            "proof_file_id": proof,
        },
    ).json()

    assert client.get(f"/api/payments/{payment['id']}/proof").status_code == 200

    # The same file, pointed at from a payment belonging to somebody else.
    with engine.begin() as connection:
        stolen = connection.execute(
            text(
                "INSERT INTO payment_transaction (affiliate_id, amount_piastres, "
                "proof_file_id) VALUES (:a, 1, :p) RETURNING id"
            ),
            {"a": sara["id"], "p": proof},
        ).scalar_one()

    assert client.get(f"/api/payments/{stolen}/proof").status_code == 404


def test_a_payment_with_no_proof_is_not_an_error(client):
    """A bank transfer with a reference number is still a payment."""
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)

    response = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 200_000}],
            "reference": "IPN-99312",
        },
    )

    assert response.status_code == 201
    assert response.json()["has_proof"] is False


# ── The note (§14) ─────────────────────────────────────────────────────────────


def test_paying_a_different_amount_without_a_note_is_refused(client):
    """A refusal, not a warning. The note is the only thing separating a
    deliberate partial payment from a typo, and only the person recording it
    knows which.
    """
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)

    response = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 150_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 150_000}],
        },
    )

    assert response.status_code == 400
    assert "needs a short note" in response.json()["detail"]


def test_paying_a_different_amount_with_a_note_is_allowed(client):
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)

    response = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 150_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 150_000}],
            "note": "InstaPay daily limit - the rest goes tomorrow",
        },
    )

    assert response.status_code == 201


def test_paying_exactly_what_is_owed_needs_no_note(client):
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)

    response = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 200_000}],
        },
    )

    assert response.status_code == 201


# ── Adjustments (§11.5) ────────────────────────────────────────────────────────


def test_a_write_off_clears_what_is_left(client):
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 190_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 190_000}],
            "note": "transfer fee came off",
        },
    )

    response = client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "writeoff",
            "source_month": AUGUST,
            "amount_piastres": 10_000,
            "reason": "transfer fee absorbed",
        },
    )

    assert response.status_code == 201
    body = client.get(f"/api/payments/{AUGUST}").json()
    assert body["affiliates"][0]["state"] == "settled"


def test_a_credit_needs_somewhere_to_land(client):
    """To absorb it instead, record a write-off. A credit with nowhere to go is
    a write-off that has not said so.
    """
    affiliate = _affiliate(client)
    _owed(client, affiliate)

    response = client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "credit",
            "source_month": AUGUST,
            "amount_piastres": 10_000,
            "reason": "overpaid",
        },
    )

    assert response.status_code == 400
    assert "needs a month to land on" in response.json()["detail"]


def test_a_credit_moves_the_money_forward(client):
    affiliate = _affiliate(client)
    _owed(client, affiliate, AUGUST)
    _owed(client, affiliate, SEPTEMBER, base=1_000_000)

    client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "credit",
            "source_month": AUGUST,
            "destination_month": SEPTEMBER,
            "amount_piastres": 20_000,
            "reason": "August was reopened to a lower figure",
        },
    )

    august = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0]
    september = client.get(f"/api/payments/{SEPTEMBER}").json()["affiliates"][0]
    assert august["balance_piastres"] == 180_000
    assert september["balance_piastres"] == 120_000


def test_an_adjustment_needs_a_reason(client):
    affiliate = _affiliate(client)
    _owed(client, affiliate)

    response = client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "writeoff",
            "source_month": AUGUST,
            "amount_piastres": 10_000,
            "reason": "",
        },
    )

    assert response.status_code == 422


def test_a_credit_cannot_land_on_the_month_it_came_from(client):
    """That is a write-off, and calling it a credit would make the ledger say
    money moved somewhere when it did not.
    """
    affiliate = _affiliate(client)
    _owed(client, affiliate)

    response = client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "credit",
            "source_month": AUGUST,
            "destination_month": AUGUST,
            "amount_piastres": 10_000,
            "reason": "rounding",
        },
    )

    assert response.status_code == 400


# ── What is outstanding, and her history ───────────────────────────────────────


def test_the_month_shows_who_is_still_owed(client):
    paid = _affiliate(client, "Paid", "paid@example.com")
    unpaid = _affiliate(client, "Unpaid", "unpaid@example.com")
    snapshot = _owed(client, paid)
    _owed(client, unpaid)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": paid["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 200_000}],
        },
    )

    body = client.get(f"/api/payments/{AUGUST}").json()

    assert body["totals"]["still_owed_affiliates"] == 1
    assert body["totals"]["still_owed_piastres"] == 200_000


def test_her_history_shows_payments_and_adjustments(client):
    """§11.5 requires adjustments to be visible to her - a credit she cannot
    see is a credit she cannot check.
    """
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 190_000,
            "allocations": [{"payroll_snapshot_id": snapshot, "piastres": 190_000}],
            "note": "fee",
        },
    )
    client.post(
        "/api/adjustments",
        json={
            "affiliate_id": affiliate["id"],
            "type": "writeoff",
            "source_month": AUGUST,
            "amount_piastres": 10_000,
            "reason": "transfer fee absorbed",
        },
    )

    body = client.get(f"/api/affiliates/{affiliate['id']}/payments").json()

    assert len(body["payments"]) == 1
    assert len(body["adjustments"]) == 1
    assert body["adjustments"][0]["reason"] == "transfer fee absorbed"


def test_a_recorded_destination_is_masked_in_her_history(client):
    """§6.4.4. Never the raw address, anywhere but her own screen."""
    affiliate = _affiliate(client)
    client.put(
        f"/api/affiliates/{affiliate['id']}/payout-destination",
        json={
            "method": "instapay",
            "instapay_address_url": "https://ipn.eg/nour-abdelrahman-2291",
        },
    )
    _owed(client, affiliate)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
        },
    )

    body = client.get(f"/api/affiliates/{affiliate['id']}/payments").json()

    assert "nour-abdelrahman" not in str(body)


# ── Who may do what ────────────────────────────────────────────────────────────


def test_a_model_may_record_nothing(client):
    """§6.5. She may never touch anything determining what she is owed."""
    affiliate = _affiliate(client)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))

    assert (
        client.post(
            "/api/payments",
            json={"affiliate_id": affiliate["id"], "amount_piastres": 1000},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/adjustments",
            json={
                "affiliate_id": affiliate["id"],
                "type": "writeoff",
                "source_month": AUGUST,
                "amount_piastres": 1,
                "reason": "no",
            },
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/affiliates/{affiliate['id']}/proof",
            files={"file": ("p.jpg", _screenshot(), "image/jpeg")},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("month", ["2026-13", "not-a-month"])
def test_a_month_that_is_not_a_month_is_refused(client, month):
    assert client.get(f"/api/payments/{month}").status_code == 400


def test_the_pay_screen_carries_every_version_of_a_reopened_month(client):
    """What the business could not see, and needed to.

    Paying what the screen said before this would have sent the whole new
    figure to somebody already paid most of it.
    """
    def balance():
        rows = client.get(f"/api/payments/{AUGUST}").json()["affiliates"]
        return next(r for r in rows if r["affiliate_id"] == affiliate["id"])

    affiliate = _affiliate(client)
    snapshot_id = _owed(client, affiliate)

    first = balance()
    assert len(first["versions"]) == 1

    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": first["balance_piastres"],
            "allocations": [
                {
                    "payroll_snapshot_id": snapshot_id,
                    "piastres": first["balance_piastres"],
                }
            ],
        },
    )
    assert balance()["balance_piastres"] == 0

    reopened = client.post(
        f"/api/payroll/{AUGUST}/reopen",
        json={"affiliate_ids": [affiliate["id"]], "reason": "orders arrived late"},
    )
    assert reopened.status_code == 200, reopened.text
    _order(affiliate["id"], "late-one", 1_000_000)
    client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={"affiliate_ids": [affiliate["id"]], "preview": False},
    )

    after = balance()
    already = first["balance_piastres"]

    assert [v["version"] for v in after["versions"]] == [1, 2]
    assert after["versions"][0]["paid_piastres"] == already
    assert after["versions"][0]["is_current"] is False
    assert after["versions"][1]["paid_piastres"] == 0
    assert after["versions"][1]["is_current"] is True

    # And the figure somebody would act on is the difference, not the whole.
    assert after["paid_piastres"] == already
    assert after["paid_earlier_versions_piastres"] == already
    assert after["balance_piastres"] == after["obligation_piastres"] - already
