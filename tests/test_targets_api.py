"""The bulk grid, over HTTP.

Phase 5 Task 5. §12.2: every model down the side, one month across, tab straight
through, single save.

The two things worth proving: **one bad row saves nothing**, and a model with no
target **appears anyway**. A partial save leaves somebody unable to see which half
landed; an absent row is a gap nobody notices until it blocks their month.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.passwords import hash_password
from app.db import engine
from app.main import app

BOOTSTRAP = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "quiet-harbour-lantern",
}
MONTH = "2026-04"


@pytest.fixture()
def anonymous(fresh_database):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def client(fresh_database):
    """Signed in as the administrator."""
    with TestClient(app) as test_client:
        response = test_client.post("/api/auth/bootstrap", json=BOOTSTRAP)
        assert response.status_code == 201, response.text
        test_client.headers["X-CSRF-Token"] = response.json()["csrf"]
        yield test_client


def _demote_to(role: str) -> None:
    with engine.begin() as connection:
        connection.execute(text("UPDATE role_assignment SET role = :r"), {"r": role})


def _make_account(email: str) -> int:
    with engine.begin() as connection:
        return connection.execute(
            text(
                "INSERT INTO user_account (email, password_hash, status, display_name) "
                "VALUES (:e, :p, 'active', 'Model') RETURNING id"
            ),
            {"e": email, "p": hash_password("quiet-harbour-lantern")},
        ).scalar_one()


def _affiliate(client, name="Nour", email="nour@example.com", **extra) -> dict:
    body = {"user_account_id": _make_account(email), "name": name, **extra}
    response = client.post("/api/affiliates", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _row(affiliate_id, required=(8, 5), actual=None) -> dict:
    row = {
        "affiliate_id": affiliate_id,
        "required_videos": required[0],
        "required_stories": required[1],
    }
    if actual is not None:
        row["actual_videos"], row["actual_stories"] = actual
    return row


def _grid(client, month=MONTH) -> dict:
    response = client.get(f"/api/targets/{month}")
    assert response.status_code == 200, response.text
    return response.json()


# ── The grid ───────────────────────────────────────────────────────────────────


def test_a_model_with_no_target_appears_anyway(client):
    """An absent row is an invisible gap, and the gap is exactly what blocks
    their month later.
    """
    affiliate = _affiliate(client)

    rows = _grid(client)["rows"]

    assert len(rows) == 1
    assert rows[0]["affiliate_id"] == affiliate["id"]
    assert rows[0]["required_videos"] is None
    assert rows[0]["achieved"] is None


def test_every_model_is_listed(client):
    _affiliate(client, "Nour", "nour@example.com")
    _affiliate(client, "Sara", "sara@example.com")

    assert len(_grid(client)["rows"]) == 2


def test_the_grid_saves_in_one_go(client):
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")

    response = client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(nour["id"], (8, 5)), _row(sara["id"], (2, 1))]},
    )

    assert response.status_code == 200
    assert response.json()["saved"] == 2
    rows = {row["affiliate_id"]: row for row in _grid(client)["rows"]}
    assert rows[nour["id"]]["required_videos"] == 8
    assert rows[sara["id"]]["required_videos"] == 2


def test_requirements_and_actuals_save_together(client):
    affiliate = _affiliate(client)

    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (8, 5))]},
    )

    row = _grid(client)["rows"][0]
    assert row["actual_videos"] == 8
    assert row["achieved"] is True


def test_the_three_answers_are_distinguishable(client):
    """`null` means nobody recorded it - which blocks their month, where missing
    the target does not.
    """
    nothing = _affiliate(client, "Nothing", "a@example.com")
    missed = _affiliate(client, "Missed", "b@example.com")
    hit = _affiliate(client, "Hit", "c@example.com")

    client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                _row(nothing["id"], (8, 5)),
                _row(missed["id"], (8, 5), (8, 4)),
                _row(hit["id"], (8, 5), (8, 5)),
            ]
        },
    )

    rows = {row["affiliate_id"]: row for row in _grid(client)["rows"]}
    assert rows[nothing["id"]]["achieved"] is None
    assert rows[missed["id"]]["achieved"] is False
    assert rows[hit["id"]]["achieved"] is True


# ── All of it, or none of it ───────────────────────────────────────────────────


def test_one_bad_row_saves_nothing(client):
    """A partial save is worse than a rejection: the person cannot see which
    half landed, and fixing it and pressing save again writes the good half
    twice.
    """
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")

    response = client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                _row(nour["id"], (8, 5)),
                {
                    "affiliate_id": sara["id"],
                    "required_videos": 2,
                    "required_stories": 1,
                    "actual_videos": 2,
                    # stories deliberately absent
                },
            ]
        },
    )

    assert response.status_code == 400
    assert "Nothing saved" in response.json()["detail"]
    assert all(row["required_videos"] is None for row in _grid(client)["rows"])


def test_the_rejection_names_the_row_and_the_model(client):
    """"Row 2 is wrong" is unusable on a grid of twenty."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")

    detail = client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                _row(nour["id"], (8, 5)),
                {
                    "affiliate_id": sara["id"],
                    "required_videos": 2,
                    "required_stories": 1,
                    "actual_stories": 1,
                },
            ]
        },
    ).json()["detail"]

    assert "Row 2" in detail
    assert "Sara" in detail


def test_an_unknown_affiliate_saves_nothing(client):
    nour = _affiliate(client)

    response = client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(nour["id"], (8, 5)), _row(99999, (1, 1))]},
    )

    assert response.status_code == 400
    assert _grid(client)["rows"][0]["required_videos"] is None


def test_a_negative_number_is_refused_before_it_reaches_the_database(client):
    affiliate = _affiliate(client)

    response = client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (-1, 5))]},
    )

    assert response.status_code == 422


# ── Verification ───────────────────────────────────────────────────────────────


def test_verifying_unlocks_the_guarantee(client):
    affiliate = _affiliate(client)
    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (8, 5))]},
    )

    response = client.post(
        f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
    )

    assert response.status_code == 200
    row = _grid(client)["rows"][0]
    assert row["verified"] is True
    assert row["verified_at"] is not None


def test_verifying_several_at_once(client):
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    client.put(
        f"/api/targets/{MONTH}",
        json={
            "rows": [
                _row(nour["id"], (8, 5), (8, 5)),
                _row(sara["id"], (2, 1), (2, 1)),
            ]
        },
    )

    response = client.post(
        f"/api/targets/{MONTH}/verify",
        json={"affiliate_ids": [nour["id"], sara["id"]]},
    )

    assert response.json()["verified"] == 2
    assert all(row["verified"] for row in _grid(client)["rows"])


def test_verifying_an_unrecorded_month_verifies_nothing(client):
    """Confirming numbers nobody entered would unlock a guarantee on an empty
    month - and the rest of the batch must not slip through with it.
    """
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")
    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(nour["id"], (8, 5), (8, 5)), _row(sara["id"], (2, 1))]},
    )

    response = client.post(
        f"/api/targets/{MONTH}/verify",
        json={"affiliate_ids": [nour["id"], sara["id"]]},
    )

    assert response.status_code == 400
    assert all(not row["verified"] for row in _grid(client)["rows"])


def test_a_missed_target_can_be_verified(client):
    """Verification confirms the numbers, not the outcome."""
    affiliate = _affiliate(client)
    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (1, 1))]},
    )

    response = client.post(
        f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
    )

    assert response.status_code == 200
    row = _grid(client)["rows"][0]
    assert row["verified"] is True
    assert row["achieved"] is False


def test_un_verifying_needs_a_reason(client):
    affiliate = _affiliate(client)
    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (8, 5))]},
    )
    client.post(f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]})

    assert (
        client.post(
            f"/api/targets/{MONTH}/unverify",
            json={"affiliate_ids": [affiliate["id"]], "reason": ""},
        ).status_code
        == 422
    )

    response = client.post(
        f"/api/targets/{MONTH}/unverify",
        json={
            "affiliate_ids": [affiliate["id"]],
            "reason": "Sara counted last month's posts",
        },
    )
    assert response.status_code == 200
    assert _grid(client)["rows"][0]["verified"] is False


def test_re_saving_actuals_clears_the_verification(client):
    """The confirmation was of the old numbers. Letting a correction inherit it
    would unlock a guarantee nobody agreed to.
    """
    affiliate = _affiliate(client)
    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (8, 5))]},
    )
    client.post(f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]})

    client.put(
        f"/api/targets/{MONTH}",
        json={"rows": [_row(affiliate["id"], (8, 5), (9, 6))]},
    )

    assert _grid(client)["rows"][0]["verified"] is False


# ── Who may do what ────────────────────────────────────────────────────────────


def test_a_model_may_touch_none_of_it(client):
    """§6.5. The affiliate role holds no permissions at all."""
    affiliate = _affiliate(client)
    _demote_to("affiliate")

    assert client.get(f"/api/targets/{MONTH}").status_code == 403
    assert (
        client.put(f"/api/targets/{MONTH}", json={"rows": []}).status_code == 403
    )
    assert (
        client.post(
            f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
        ).status_code
        == 403
    )


def test_signing_out_closes_everything(anonymous):
    assert anonymous.get(f"/api/targets/{MONTH}").status_code == 401
    assert anonymous.put(f"/api/targets/{MONTH}", json={"rows": []}).status_code == 401


# ── Bad input ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("month", ["2026-13", "not-a-month", "2026", "2026-00"])
def test_a_month_that_is_not_a_month_is_refused(client, month):
    assert client.get(f"/api/targets/{month}").status_code == 400


def test_an_empty_grid_is_allowed(client):
    """Opening the screen and saving without typing is not an error."""
    response = client.put(f"/api/targets/{MONTH}", json={"rows": []})

    assert response.status_code == 200
    assert response.json()["saved"] == 0
