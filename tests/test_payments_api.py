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
    "password": "quiet-harbour-lantern",
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
            {"e": email, "p": hash_password("quiet-harbour-lantern")},
        ).scalar_one()


def _affiliate(client, name="Nour", email="nour@example.com") -> dict:
    body = {"user_account_id": _make_account(email), "name": name}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    affiliate = response.json()
    # **Active, because the desk is a list of people on the programme.**
    # `create_affiliate` makes an application; approving it is what puts
    # somebody on the payroll, and `on_the_desk` now models that - the
    # approved export lists `participants(month)`, which excludes an
    # application. A fixture that left her pending and then gave her pay terms
    # and orders was describing a state the product does not produce.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'active' WHERE id = :id"),
            {"id": affiliate["id"]},
        )
    client.put(
        f"/api/affiliates/{affiliate['id']}/pay-history",
        json={
            "periods": [
                {
                    "start_month": "2026-01",
                    "compensation_type": "commission",
                    "commission_rate_bp": 1000,
                }
            ],
            "outcomes": {},
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


def _commit(client, month, affiliate_id):
    """Preview, then agree what the preview said (05B)."""
    seen = client.post(
        f"/api/payroll/{month}/approve",
        json={"affiliate_ids": [affiliate_id]},
    ).json()["results"][0]
    return client.post(
        f"/api/payroll/{month}/approve",
        json={
            "affiliate_ids": [affiliate_id],
            "preview": False,
            "source_versions": {str(affiliate_id): seen["source_version"]},
        },
    )


def _owed(client, affiliate, month=AUGUST, base=2_000_000) -> int:
    """An approved month owing EGP 2,000. Returns the snapshot id."""
    _order(affiliate["id"], f"{affiliate['id']}-{month}", base, month=month)
    _commit(client, month, affiliate["id"])
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


def test_retrying_the_same_transfer_returns_the_original_record(client):
    """AC38. A timeout after commit must not turn one bank transfer into two
    ledger rows when the operator retries the same operation.
    """
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    payload = {
        "operation_key": "06a-timeout-retry-0001",
        "affiliate_id": affiliate["id"],
        "amount_piastres": 200_000,
        "allocations": [
            {"payroll_snapshot_id": snapshot, "piastres": 200_000}
        ],
        "occurred_at": "2026-09-03T12:00:00+03:00",
        "reference": "IPN-06A-1",
    }

    first = client.post("/api/payments", json=payload)
    retry = client.post("/api/payments", json=payload)

    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert first.json().get("replayed") is False
    assert retry.json().get("replayed") is True
    history = client.get(f"/api/affiliates/{affiliate['id']}/payments").json()
    recorded_at = datetime.fromisoformat(history["payments"][0]["occurred_at"])
    assert recorded_at.astimezone(timezone.utc) == datetime(
        2026, 9, 3, 9, tzinfo=timezone.utc
    )
    assert history["payments"][0]["reference"] == "IPN-06A-1"
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM payment_transaction")) == 1
        assert connection.scalar(text("SELECT count(*) FROM payment_allocation")) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM notification_outbox "
                "WHERE event = 'payment.recorded'"
            )
        ) == 1


def test_an_operation_key_cannot_be_reused_for_different_money(client):
    """An idempotency key identifies one act, not an overwrite handle."""
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    original = {
        "operation_key": "06a-collision-0001",
        "affiliate_id": affiliate["id"],
        "amount_piastres": 200_000,
        "allocations": [
            {"payroll_snapshot_id": snapshot, "piastres": 200_000}
        ],
    }
    assert client.post("/api/payments", json=original).status_code == 201

    changed = {
        **original,
        "amount_piastres": 150_000,
        "allocations": [
            {"payroll_snapshot_id": snapshot, "piastres": 150_000}
        ],
        "note": "This is deliberately a different transfer",
    }
    response = client.post("/api/payments", json=changed)

    assert response.status_code == 409
    assert "already identifies a different payment" in response.json()["detail"]
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM payment_transaction")) == 1


def test_a_uploaded_proof_survives_a_failed_record_and_retry(client):
    """AC39. Retry the ledger write, not the transfer or proof upload."""
    affiliate = _affiliate(client)
    snapshot = _owed(client, affiliate)
    proof = client.post(
        f"/api/affiliates/{affiliate['id']}/proof",
        files={"file": ("p.jpg", _screenshot(), "image/jpeg")},
    ).json()["proof_file_id"]
    payload = {
        "operation_key": "06a-proof-retry-0001",
        "affiliate_id": affiliate["id"],
        "amount_piastres": 150_000,
        "allocations": [
            {"payroll_snapshot_id": snapshot, "piastres": 150_000}
        ],
        "proof_file_id": proof,
    }

    refused = client.post("/api/payments", json=payload)
    recorded = client.post(
        "/api/payments",
        json={**payload, "note": "InstaPay limit; the remainder goes tomorrow"},
    )

    assert refused.status_code == 400
    assert recorded.status_code == 201, recorded.text
    assert recorded.json()["has_proof"] is True
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM proof_file")) == 1
        assert connection.scalar(text("SELECT count(*) FROM payment_transaction")) == 1


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
    """ADR 0035: the month it came from ends settled, and the month it lands
    on needs that much less sent — which is what the reconcile screen has
    always promised in words."""
    affiliate = _affiliate(client)
    august = _owed(client, affiliate, AUGUST)
    _owed(client, affiliate, SEPTEMBER, base=1_000_000)

    # A credit carries an excess, so there has to be one: EGP 2,200 against
    # EGP 2,000 agreed.
    # Pay it in full, correctly.
    paid = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": august, "piastres": 200_000}],
        },
    )
    assert paid.status_code == 201, paid.text

    # Then the excess, the way it actually arises: a second transfer against
    # a second version of the same month. The API refuses over-allocating a
    # *snapshot*, and rightly - Jana's overpayment came from two snapshots
    # after a reopen, each allocation legitimate on its own and the month
    # overpaid all the same. Written directly so this test can stay about the
    # credit rather than about the reopen.
    with engine.begin() as connection:
        payment = connection.execute(
            text(
                "INSERT INTO payment_transaction (affiliate_id, amount_piastres, "
                "occurred_at) VALUES (:a, 20000, now()) "
                "RETURNING id"
            ),
            {"a": affiliate["id"]},
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO payment_allocation (payment_transaction_id, "
                "payroll_snapshot_id, allocated_piastres) VALUES (:p, :s, 20000)"
            ),
            {"p": payment, "s": august},
        )

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
    assert august["balance_piastres"] == 0
    assert september["balance_piastres"] == 80_000


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


# ── What is outstanding, and their history ───────────────────────────────────────


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


def test_month_end_separates_forecast_approved_and_recorded_money(client):
    """AC31/AC32. Inactive debts remain; HBA's house code never enters pay."""
    inactive = _affiliate(client, "Inactive", "inactive@example.com")
    _owed(client, inactive)
    forecast = _affiliate(client, "Forecast", "forecast@example.com")
    _order(forecast["id"], "forecast-august", 2_000_000)
    house = _affiliate(client, "HBA house", "house@example.com")

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'inactive' WHERE id = :id"),
            {"id": inactive["id"]},
        )
        connection.execute(
            text("UPDATE affiliate_profile SET account_kind = 'house' WHERE id = :id"),
            {"id": house["id"]},
        )

    body = client.get(f"/api/payments/{AUGUST}").json()
    by_name = {row["name"]: row for row in body["affiliates"]}

    assert set(by_name) == {"Forecast", "Inactive"}
    assert by_name["Inactive"]["status"] == "inactive"
    assert by_name["Inactive"]["required_kind"] == "approved"
    assert by_name["Inactive"]["required_piastres"] == 200_000
    assert by_name["Forecast"]["required_kind"] == "forecast"
    assert by_name["Forecast"]["required_piastres"] == 200_000
    assert body["totals"] == {
        **body["totals"],
        "affiliates": 2,
        "required_piastres": 400_000,
        "forecast_piastres": 200_000,
        "approved_piastres": 200_000,
        "recorded_piastres": 0,
        "still_owed_affiliates": 1,
        "still_owed_piastres": 200_000,
    }


def test_month_end_lists_open_corrections_across_models(client):
    """05C answers per model; 06A makes every unanswered choice findable."""
    nour = _affiliate(client, "Nour", "nour-correction@example.com")
    sara = _affiliate(client, "Sara", "sara-correction@example.com")

    for affiliate in (nour, sara):
        snapshot = _owed(client, affiliate)
        paid = client.post(
            "/api/payments",
            json={
                "affiliate_id": affiliate["id"],
                "amount_piastres": 200_000,
                "allocations": [
                    {"payroll_snapshot_id": snapshot, "piastres": 200_000}
                ],
            },
        )
        assert paid.status_code == 201, paid.text

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'void' "
                "WHERE affiliate_id IN (:nour, :sara)"
            ),
            {"nour": nour["id"], "sara": sara["id"]},
        )

    body = client.get(f"/api/payments/{SEPTEMBER}").json()

    assert {(row["name"], row["month"]) for row in body["open_corrections"]} == {
        ("Nour", AUGUST),
        ("Sara", AUGUST),
    }
    assert all(row["recoverable_piastres"] == 200_000 for row in body["open_corrections"])
    assert body["totals"]["open_corrections"] == 2
    assert body["totals"]["open_corrections_piastres"] == 400_000


def test_a_carried_correction_can_leave_no_transfer_due(client):
    """D04. Zero after recovery is a valid month, including after earnings."""
    affiliate = _affiliate(client)
    august_snapshot = _owed(client, affiliate, AUGUST)
    _owed(client, affiliate, SEPTEMBER)
    paid = client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [
                {"payroll_snapshot_id": august_snapshot, "piastres": 200_000}
            ],
        },
    )
    assert paid.status_code == 201, paid.text

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'void' "
                "WHERE affiliate_id = :affiliate AND business_month = :month"
            ),
            {"affiliate": affiliate["id"], "month": AUGUST},
        )

    resolved = client.post(
        "/api/corrections",
        json={
            "affiliate_id": affiliate["id"],
            "month": AUGUST,
            "choice": "credit",
            "reason": "Recover the transfer after the order failed",
            "destination_month": SEPTEMBER,
            "expected_outstanding_piastres": 200_000,
            "operation_key": "carry-august-into-september",
        },
    )
    assert resolved.status_code == 201, resolved.text

    row = client.get(f"/api/payments/{SEPTEMBER}").json()["affiliates"][0]
    assert row["obligation_piastres"] == 200_000
    assert row["credited_piastres"] == 200_000
    assert row["paid_piastres"] == 0
    assert row["balance_piastres"] == 0
    assert row["required_piastres"] == 0
    assert row["state"] == "settled"


def test_a_month_awaiting_its_transfer_is_in_the_desk_queue(client):
    """F09/A05, over HTTP.

    An order failing between approval and payment used to leave the queue
    empty: the row was dropped because nothing was recoverable, so the one
    screen finance reads at month end said nothing had changed. Not inventing
    a debt is right; hiding the change is not.
    """
    affiliate = _affiliate(client)
    _owed(client, affiliate, AUGUST)

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'void' "
                "WHERE affiliate_id = :affiliate AND business_month = :month"
            ),
            {"affiliate": affiliate["id"], "month": AUGUST},
        )

    body = client.get(f"/api/payments/{SEPTEMBER}").json()
    row = next(
        row for row in body["open_corrections"] if row["affiliate_id"] == affiliate["id"]
    )

    assert row["outstanding_piastres"] == 200_000
    assert row["recoverable_piastres"] == 0
    assert row["needs_review"] is True
    assert row["review_reason"] == "no_transfer_recorded"
    # Nothing was advanced, so nothing is added to what she owes.
    assert body["totals"]["open_corrections_piastres"] == 0

    refused = client.post(
        "/api/corrections",
        json={
            "affiliate_id": affiliate["id"],
            "month": AUGUST,
            "choice": "credit",
            "reason": "nothing was sent",
            "destination_month": SEPTEMBER,
            "expected_outstanding_piastres": 200_000,
            "operation_key": "carry-what-was-never-sent",
        },
    )
    assert refused.status_code == 400
    assert "nothing to carry" in refused.json()["detail"]

    # R4. Absorbing it is the answer that finishes the review, and it leaves
    # the agreed figure to be paid in full.
    absorbed = client.post(
        "/api/corrections",
        json={
            "affiliate_id": affiliate["id"],
            "month": AUGUST,
            "choice": "writeoff",
            "reason": "HBA absorbs the difference and pays what was agreed",
            "expected_outstanding_piastres": 200_000,
            "operation_key": "absorb-august",
        },
    )
    assert absorbed.status_code == 201, absorbed.text
    assert absorbed.json()["type"] == "accepted"

    after = client.get(f"/api/payments/{SEPTEMBER}").json()
    assert not [
        row
        for row in after["open_corrections"]
        if row["affiliate_id"] == affiliate["id"]
    ]
    august = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0]
    assert august["obligation_piastres"] == 200_000
    assert august["balance_piastres"] == 200_000


def test_the_desk_refuses_a_correction_that_cannot_say_what_it_was_shown(client):
    """R2. Freshness and identity are required, not optional.

    Their absence used to mean *proceed anyway*, which made the protection
    optional for exactly the callers most likely to need it: a script, a
    retry, a second tab.
    """
    affiliate = _affiliate(client)
    _owed(client, affiliate, AUGUST)

    for missing in ("expected_outstanding_piastres", "operation_key"):
        body = {
            "affiliate_id": affiliate["id"],
            "month": AUGUST,
            "choice": "writeoff",
            "reason": "no freshness, no identity",
            "expected_outstanding_piastres": 0,
            "operation_key": "a-key-long-enough",
        }
        body.pop(missing)
        refused = client.post("/api/corrections", json=body)
        assert refused.status_code == 422, (missing, refused.text)


def test_a_repeated_correction_is_refused_rather_than_applied_twice(client):
    """Duplicate and concurrent submissions, over HTTP.

    A settlement can be partial now, so a second identical request is no
    longer harmlessly idempotent - it would carry the same money into the same
    month again. The screen sends the figure it displayed, and a request that
    no longer matches it is answered 409: look again.
    """
    affiliate = _affiliate(client)
    august = _owed(client, affiliate, AUGUST)
    _owed(client, affiliate, SEPTEMBER)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [{"payroll_snapshot_id": august, "piastres": 200_000}],
        },
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'void' "
                "WHERE affiliate_id = :affiliate AND business_month = :month"
            ),
            {"affiliate": affiliate["id"], "month": AUGUST},
        )

    shown = next(
        row
        for row in client.get(f"/api/payments/{SEPTEMBER}").json()["open_corrections"]
        if row["affiliate_id"] == affiliate["id"]
    )["outstanding_piastres"]

    request = {
        "affiliate_id": affiliate["id"],
        "month": AUGUST,
        "choice": "credit",
        "reason": "Recover the transfer after the order failed",
        "destination_month": SEPTEMBER,
        "expected_outstanding_piastres": shown,
        "operation_key": "recover-august-once",
    }

    first = client.post("/api/corrections", json=request)
    assert first.status_code == 201, first.text

    # **The retry a browser makes when it never learned the first one landed**
    # (R2). Same decision, same key: it is answered with the recovery the
    # first attempt made, not refused as a conflict it cannot interpret.
    second = client.post("/api/corrections", json=request)
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]

    # A *different* decision on a figure that has since moved is a conflict,
    # and says so.
    stale = client.post(
        "/api/corrections",
        json={**request, "operation_key": "somebody-elses-decision"},
    )
    assert stale.status_code == 409, stale.text

    # And exactly one recovery stands.
    adjustments = client.get(
        f"/api/affiliates/{affiliate['id']}/payments"
    ).json()["adjustments"]
    assert [row["amount_piastres"] for row in adjustments] == [200_000]


def test_their_history_shows_payments_and_adjustments(client):
    """§11.5 requires adjustments to be visible to them - a credit they cannot
    see is a credit they cannot check.
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
    assert body["payments"][0]["allocations"] == [
        {
            "month": AUGUST,
            "snapshot_id": snapshot,
            "snapshot_version": 1,
            "allocated_piastres": 190_000,
        }
    ]
    assert body["adjustments"][0]["reason"] == "transfer fee absorbed"


def test_a_recorded_destination_is_masked_in_their_history(client):
    """§6.4.4. Never the raw address, anywhere but their own screen."""
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


def test_a_model_may_not_read_the_month_end_desk(client):
    """Which is what makes the line above it safe."""
    _affiliate(client)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))

    assert client.get(f"/api/payments/{AUGUST}").status_code == 403


# ── Who may do what ────────────────────────────────────────────────────────────


def test_a_model_may_record_nothing(client):
    """§6.5. They may never touch anything determining what they are owed."""
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

    # Reopened through the service, not the route: 05B retired the route, and
    # the months this screen has to keep working for were reopened before it
    # did. What is being tested is the pay screen carrying **every** version of
    # such a month, which is exactly as true now as it was then.
    from app.db import SessionLocal
    from app.models.affiliates import AffiliateProfile
    from app.services.payroll import reopen_month

    with SessionLocal() as session:
        reopen_month(
            session,
            session.get(AffiliateProfile, affiliate["id"]),
            AUGUST,
            reason="orders arrived late",
        )
        session.commit()

    _order(affiliate["id"], "late-one", 1_000_000)
    _commit(client, AUGUST, affiliate["id"])

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


# -- The month's payment view (the approved export's vPayment) ---------------


def test_an_unagreed_month_is_an_estimate_with_a_fingerprint(client):
    """Worked out live, labelled an estimate, and carrying what an approval
    from this view has to hand back (05B)."""
    affiliate = _affiliate(client)
    _order(affiliate["id"], "st-1", 2_000_000)

    body = client.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()

    assert body["basis"] == "estimate"
    assert body["source_version"]
    assert body["version"] is None


def test_an_agreed_month_is_read_from_its_snapshot(client):
    """Once approved, the figure under *Approved amount* is the frozen one."""
    affiliate = _affiliate(client)
    _owed(client, affiliate)

    body = client.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()

    assert body["basis"] == "approved"
    assert body["total_piastres"] == 200_000
    assert body["version"] == 1
    assert body["source_version"] is None
    assert body["blockers"] == []


def test_the_lines_add_up_to_the_total(client):
    """A breakdown that does not sum to the figure beside it is the one thing
    a breakdown must never be."""
    affiliate = _affiliate(client)
    _owed(client, affiliate)

    body = client.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()

    assert (
        body["commission_piastres"]
        + body["fixed_piastres"]
        + body["guarantee_top_up_piastres"]
        == body["total_piastres"]
    )


def test_approving_from_the_payment_view_refuses_a_moved_month(client):
    """The fingerprint from the statement is what the commit is checked
    against: an order arriving after the page loaded refuses the approval."""
    affiliate = _affiliate(client)
    _order(affiliate["id"], "st-2", 2_000_000)
    seen = client.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").json()
    _order(affiliate["id"], "st-3", 500_000)

    response = client.post(
        f"/api/payroll/{AUGUST}/approve",
        json={
            "affiliate_ids": [affiliate["id"]],
            "preview": False,
            "source_versions": {str(affiliate["id"]): seen["source_version"]},
        },
    ).json()

    assert response["results"][0]["approved"] is False
    assert response["results"][0]["stale"] is True


def test_a_model_may_not_read_a_payment_statement(client):
    affiliate = _affiliate(client)
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = 'affiliate'"))

    assert (
        client.get(f"/api/payroll/{AUGUST}/statement/{affiliate['id']}").status_code
        == 403
    )


def test_a_forecast_month_reports_the_transfer_not_the_gross_earnings(client):
    """A02. One column, one meaning, on both sides of the approval line.

    A carry is accepted against a month **before** it is agreed (F07, F12), so
    a draft month can already be carrying a deduction. September is on course
    to earn EGP 3,000 and EGP 2,000 of August's overpayment is landing on it, so
    the bank movement is EGP 1,000 — and *funds required* is the question that
    column asks.

    The approved branch has always netted the deduction out. The forecast
    branch reported the gross earnings, so the same column meant two different
    things depending on a state the reader cannot see, which is the half of
    A02 that lives on the server.

    `forecast_piastres` keeps answering the other question — what the month is
    worth — because the detail screen and the header's estimate both ask it.
    """
    affiliate = _affiliate(client, "Nour", "nour-forecast@example.com")
    snapshot = _owed(client, affiliate)
    client.post(
        "/api/payments",
        json={
            "affiliate_id": affiliate["id"],
            "amount_piastres": 200_000,
            "allocations": [
                {"payroll_snapshot_id": snapshot, "piastres": 200_000}
            ],
        },
    )
    # September earns EGP 3,000 and is deliberately left unapproved.
    _order(affiliate["id"], "sep-big", 3_000_000, month=SEPTEMBER)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE attributed_order SET commission_state = 'void' "
                "WHERE affiliate_id = :affiliate AND business_month = :month"
            ),
            {"affiliate": affiliate["id"], "month": AUGUST},
        )
    carried = client.post(
        "/api/corrections",
        json={
            "affiliate_id": affiliate["id"],
            "month": AUGUST,
            "choice": "credit",
            "reason": "Recover the transfer after the order failed",
            "destination_month": SEPTEMBER,
            "expected_outstanding_piastres": 200_000,
            "operation_key": "carry-into-a-draft-september",
        },
    )
    assert carried.status_code == 201, carried.text

    row = client.get(f"/api/payments/{SEPTEMBER}").json()["affiliates"][0]
    assert row["required_kind"] == "forecast"
    # What the month is worth, and what would leave the bank.
    assert row["forecast_piastres"] == 300_000
    assert row["credited_piastres"] == 200_000
    assert row["required_piastres"] == 100_000
    # And the agreed figures stay where an unapproved month puts them.
    assert row["obligation_piastres"] == 0
    assert row["balance_piastres"] == 0


# ── ADR 0042: the payer sees the whole destination ────────────────────────────


def _instapay(affiliate_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO payout_destination (affiliate_id, method, "
                "instapay_address_url, instapay_phone, created_at) "
                "VALUES (:a, 'instapay', :u, :p, now())"
            ),
            {
                "a": affiliate_id,
                "u": "https://ipn.eg/S/nour/instapay/1111",
                "p": "01001234567",
            },
        )


def test_the_payments_row_carries_the_whole_destination(client):
    """ADR 0042. The owner's approved design puts the real number on the row.

    `InstaPay · 010 7014 2033` is what the export writes, and `…4567` is what
    the old masking wrote. A number rendered with dots cannot be typed into a
    banking app, which is what this screen exists to precede.
    """
    affiliate = _affiliate(client, "Nour", "nour-dest@example.com")
    _instapay(affiliate["id"])

    row = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0]

    assert row["destination_line"] == "InstaPay · 01001234567"
    # The masked form is still on the row beside it - it is what a log or a
    # notice may carry, and ADR 0028 is unchanged about that.
    assert row["destination"]["instapay_phone"] != "01001234567"


def test_the_detail_card_carries_the_link_she_submitted(client):
    """ADR 0042 and §13.1. The link, not a number turned into one.

    A phone hands an InstaPay payment address straight to the app, which is
    the entire reason that field is collected as a link rather than rebuilt
    from the number.
    """
    affiliate = _affiliate(client, "Nour", "nour-card@example.com")
    _instapay(affiliate["id"])

    card = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0][
        "destination_card"
    ]

    assert card["kind"] == "instapay"
    assert card["title"] == "InstaPay"
    assert [row["label"] for row in card["rows"]] == [
        "InstaPay number",
        "Payment link, as submitted",
    ]
    assert card["rows"][0]["value"] == "01001234567"
    assert card["rows"][1]["value"] == "https://ipn.eg/S/nour/instapay/1111"
    assert card["link"] == "https://ipn.eg/S/nour/instapay/1111"


def test_an_account_that_cannot_pay_sees_neither(client):
    """ADR 0042 keeps ADR 0028's gate: `payments.record`, and nothing wider.

    Marketing reads the same screen. It gets the masked sentence and no card,
    which is the whole of what changed - who sees it did not.
    """
    affiliate = _affiliate(client, "Nour", "nour-gate@example.com")
    _instapay(affiliate["id"])

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE role_assignment SET role = 'content_manager' "
                "WHERE user_account_id = 1 AND revoked_at IS NULL"
            )
        )

    row = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0]

    assert row["destination_line"] is None
    assert row["destination_card"] is None
    # And the masked form is still there, so the screen still says where it goes.
    assert row["destination"]["method"] == "instapay"


def test_the_profile_carries_the_same_card_as_the_desk(client):
    """ADR 0042, on the model's own profile. A03.

    The card was on the payments desk and the profile one click away still
    printed `InstaPay · …4567` - the same fact, to the same person, with the
    same permission, written two different ways. The approved export draws the
    same card in both places, and it is the same job in both: somebody with a
    banking app open cannot type a number made of dots.
    """
    affiliate = _affiliate(client, "Nour", "nour-profile-card@example.com")
    _instapay(affiliate["id"])

    profile = client.get(f"/api/affiliates/{affiliate['id']}").json()
    desk = client.get(f"/api/payments/{AUGUST}").json()["affiliates"][0]

    assert profile["payout_destination_card"] == desk["destination_card"]
    assert profile["payout_destination_card"]["rows"][0]["value"] == "01001234567"
    # Masked beside it, still, for everything that writes a record down.
    assert profile["payout_destination"]["instapay_phone"] != "01001234567"


def test_a_profile_reader_who_cannot_pay_sees_no_card(client):
    """The same gate, on the same permission, from the other screen.

    Marketing may read a profile - that is what `affiliates.view` is for - and
    may not send money. Widening the card to everybody who can open a profile
    would have quietly undone ADR 0028's gate while claiming to obey 0042.
    """
    affiliate = _affiliate(client, "Nour", "nour-profile-gate@example.com")
    _instapay(affiliate["id"])

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE role_assignment SET role = 'content_manager' "
                "WHERE user_account_id = 1 AND revoked_at IS NULL"
            )
        )

    profile = client.get(f"/api/affiliates/{affiliate['id']}").json()

    assert profile["payout_destination_card"] is None
    assert profile["payout_destination"]["method"] == "instapay"


def test_an_application_is_not_on_the_payments_desk(client):
    """The export lists `participants(month)`, which excludes an application.

    Somebody who applied and has not been taken on is owed nothing by
    construction: no terms, no code, no month. Listing her as *Terms missing*
    put her in the awaiting-approval count and on the sidebar badge, which
    read 22 over a list of 19. Her application is handled on Models, where the
    design puts it.
    """
    taken_on = _affiliate(client, "Nour", "nour-participant@example.com")
    applied = _affiliate(client, "Habiba", "habiba-applied@example.com")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'pending' WHERE id = :id"),
            {"id": applied["id"]},
        )

    listed = {
        row["affiliate_id"] for row in client.get(f"/api/payments/{AUGUST}").json()["affiliates"]
    }

    assert taken_on["id"] in listed
    assert applied["id"] not in listed


def test_a_month_before_she_started_is_not_on_the_desk(client):
    """The export's `started(m, month)`, in the one direction the desk needs.

    A model taken on in a later month has no August, and an August row reading
    *Terms missing* asks somebody to fix something that is not broken.
    """
    later = _affiliate(client, "Zeina", "zeina-later@example.com")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE affiliate_profile SET collaboration_start_month = '2026-12' "
                "WHERE id = :id"
            ),
            {"id": later["id"]},
        )

    listed = {
        row["affiliate_id"] for row in client.get(f"/api/payments/{AUGUST}").json()["affiliates"]
    }

    assert later["id"] not in listed


def test_the_sidebar_badge_counts_the_people_the_desk_lists(client):
    """One rule, two readers. The disagreement this prevents was live.

    The badge counted every payable affiliate and the desk listed
    participants, so the sidebar said 22 above a screen showing 19 - the
    "second answer waiting to disagree" that the counts route's own docstring
    warns about, arriving by exactly the route it predicted.
    """
    _affiliate(client, "Nour", "nour-badge@example.com")
    applied = _affiliate(client, "Habiba", "habiba-badge@example.com")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE affiliate_profile SET status = 'pending' WHERE id = :id"),
            {"id": applied["id"]},
        )

    from app.services.payroll import working_month

    desk = client.get(f"/api/payments/{working_month()}").json()["affiliates"]
    awaiting = sum(1 for row in desk if row["state"] == "not_approved")
    badge = client.get("/api/operations/counts").json()["payments_awaiting_approval"]

    assert badge == awaiting
