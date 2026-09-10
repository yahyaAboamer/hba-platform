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


def _save(client, rows, month=MONTH, revision=None):
    """PUT the grid, carrying the revision the server last handed out.

    Optimistic concurrency arrived with 04A: a save without a matching
    revision is refused, because two people run payroll and both open this
    screen at month end. Every test that saves goes through here so they keep
    testing *behaviour* rather than the calling convention - the conflict
    itself has its own tests below.
    """
    if revision is None:
        revision = _grid(client, month)["revision"]
    return client.put(
        f"/api/targets/{month}", json={"rows": rows, "revision": revision}
    )


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

    response = _save(client, [_row(nour["id"], (8, 5)), _row(sara["id"], (2, 1))], month=MONTH)

    assert response.status_code == 200
    assert response.json()["saved"] == 2
    rows = {row["affiliate_id"]: row for row in _grid(client)["rows"]}
    assert rows[nour["id"]]["required_videos"] == 8
    assert rows[sara["id"]]["required_videos"] == 2


def test_requirements_and_actuals_save_together(client):
    affiliate = _affiliate(client)

    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))], month=MONTH)

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

    _save(client, [
                _row(nothing["id"], (8, 5)),
                _row(missed["id"], (8, 5), (8, 4)),
                _row(hit["id"], (8, 5), (8, 5)),
            ])

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

    response = _save(client, [
                _row(nour["id"], (8, 5)),
                {
                    "affiliate_id": sara["id"],
                    "required_videos": 2,
                    "required_stories": 1,
                    "actual_videos": 2,
                    # stories deliberately absent
                },
            ])

    assert response.status_code == 400
    assert "Nothing saved" in response.json()["detail"]
    assert all(row["required_videos"] is None for row in _grid(client)["rows"])


def test_the_rejection_names_the_row_and_the_model(client):
    """"Row 2 is wrong" is unusable on a grid of twenty."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    sara = _affiliate(client, "Sara", "sara@example.com")

    detail = _save(client, [
                _row(nour["id"], (8, 5)),
                {
                    "affiliate_id": sara["id"],
                    "required_videos": 2,
                    "required_stories": 1,
                    "actual_stories": 1,
                },
            ]).json()["detail"]

    assert "Row 2" in detail
    assert "Sara" in detail


def test_an_unknown_affiliate_saves_nothing(client):
    nour = _affiliate(client)

    response = _save(client, [_row(nour["id"], (8, 5)), _row(99999, (1, 1))], month=MONTH)

    assert response.status_code == 400
    assert _grid(client)["rows"][0]["required_videos"] is None


def test_a_negative_number_is_refused_before_it_reaches_the_database(client):
    affiliate = _affiliate(client)

    response = _save(client, [_row(affiliate["id"], (-1, 5))], month=MONTH)

    assert response.status_code == 422


# ── Verification ───────────────────────────────────────────────────────────────


def test_verifying_unlocks_the_guarantee(client):
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))], month=MONTH)

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
    _save(client, [
                _row(nour["id"], (8, 5), (8, 5)),
                _row(sara["id"], (2, 1), (2, 1)),
            ])

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
    _save(client, [_row(nour["id"], (8, 5), (8, 5)), _row(sara["id"], (2, 1))], month=MONTH)

    response = client.post(
        f"/api/targets/{MONTH}/verify",
        json={"affiliate_ids": [nour["id"], sara["id"]]},
    )

    assert response.status_code == 400
    assert all(not row["verified"] for row in _grid(client)["rows"])


def test_a_missed_target_can_be_verified(client):
    """Verification confirms the numbers, not the outcome."""
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (1, 1))], month=MONTH)

    response = client.post(
        f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
    )

    assert response.status_code == 200
    row = _grid(client)["rows"][0]
    assert row["verified"] is True
    assert row["achieved"] is False


def test_un_verifying_needs_a_reason(client):
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))], month=MONTH)
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
    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))], month=MONTH)
    client.post(f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]})

    _save(client, [_row(affiliate["id"], (8, 5), (9, 6))], month=MONTH)

    assert _grid(client)["rows"][0]["verified"] is False


# ── Who may do what ────────────────────────────────────────────────────────────


def test_a_model_may_touch_none_of_it(client):
    """§6.5. The affiliate role holds no permissions at all."""
    affiliate = _affiliate(client)
    _demote_to("affiliate")

    assert client.get(f"/api/targets/{MONTH}").status_code == 403
    # An explicit revision, because `_save` would otherwise read the grid to
    # fetch one and be refused there instead - which would pass this test for
    # the wrong reason. The refusal being proven is the *save*.
    assert (
        _save(client, [], month=MONTH, revision="anything").status_code == 403
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
    response = _save(client, [], month=MONTH)

    assert response.status_code == 200
    assert response.json()["saved"] == 0


# ── 04A: what a save must not do ──────────────────────────────────────────────


def test_saving_a_requirement_does_not_touch_what_she_actually_did(client):
    """The completion gate, in as many words.

    Requirements and achievements are two facts recorded by two people at two
    times - marketing sets eight videos at the start of the month, somebody
    counts what appeared during it. A save of the first that quietly rewrote
    the second would be the platform inventing evidence for a figure that
    decides money.
    """
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (3, 2))])

    # Only the requirement changes. The counts are not mentioned at all.
    _save(client, [_row(affiliate["id"], (10, 6))])

    row = _grid(client)["rows"][0]
    assert row["required_videos"] == 10
    assert row["actual_videos"] == 3
    assert row["actual_stories"] == 2


def test_a_mistyped_count_can_be_taken_off_rather_than_zeroed(client):
    """A06: unrecorded and zero are different facts.

    Until `clear_actuals` existed the only way to undo a count typed against
    the wrong model was to set it to zero - which does not say *this was a
    mistake*, it says *she produced nothing*, and that is the claim that fails
    a guaranteed minimum.
    """
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))])
    assert _grid(client)["rows"][0]["achieved"] is True

    _save(
        client,
        [{**_row(affiliate["id"], (8, 5)), "clear_actuals": True}],
    )

    row = _grid(client)["rows"][0]
    assert row["actual_videos"] is None
    assert row["actual_stories"] is None
    # Not `False`. Nobody has recorded what she did, which is a different
    # answer from "she missed".
    assert row["achieved"] is None


def test_clearing_a_count_takes_its_confirmation_with_it(client):
    """The verification was of numbers that are now gone. Leaving it would let
    an empty month inherit somebody's approval."""
    affiliate = _affiliate(client)
    _save(client, [_row(affiliate["id"], (8, 5), (8, 5))])
    client.post(
        f"/api/targets/{MONTH}/verify", json={"affiliate_ids": [affiliate["id"]]}
    )
    assert _grid(client)["rows"][0]["verified"] is True

    _save(client, [{**_row(affiliate["id"], (8, 5)), "clear_actuals": True}])

    assert _grid(client)["rows"][0]["verified"] is False


def test_clearing_and_recording_at_once_is_refused(client):
    affiliate = _affiliate(client)

    response = _save(
        client,
        [{**_row(affiliate["id"], (8, 5), (8, 5)), "clear_actuals": True}],
    )

    assert response.status_code == 400
    assert "clear" in response.text


# ── 04A: two people, one month ────────────────────────────────────────────────


def test_a_save_built_on_somebody_elses_figures_is_refused(client):
    """Two people run payroll and both open this screen at month end.

    Without this the second save silently overwrites the first, and the losing
    edit is invisible: no error, no conflict, and no way to notice except by
    re-reading a number you already believed.
    """
    affiliate = _affiliate(client)
    stale = _grid(client)["revision"]

    # Somebody else saves in the meantime.
    _save(client, [_row(affiliate["id"], (8, 5))])

    response = _save(client, [_row(affiliate["id"], (2, 1))], revision=stale)

    assert response.status_code == 409
    assert "changed this month" in response.text
    # And nothing of theirs was lost.
    assert _grid(client)["rows"][0]["required_videos"] == 8


def test_a_save_with_no_revision_at_all_is_refused(client):
    """Absence is not agreement. A caller that sends nothing is one that has
    not been taught to check."""
    affiliate = _affiliate(client)

    response = client.put(
        f"/api/targets/{MONTH}", json={"rows": [_row(affiliate["id"], (8, 5))]}
    )

    assert response.status_code == 409


def test_a_save_returns_the_new_revision_so_two_in_a_row_work(client):
    """Saving twice should not need a reload between them."""
    affiliate = _affiliate(client)

    first = _save(client, [_row(affiliate["id"], (8, 5))])
    assert first.status_code == 200

    second = _save(
        client,
        [_row(affiliate["id"], (9, 6))],
        revision=first.json()["revision"],
    )

    assert second.status_code == 200
    assert _grid(client)["rows"][0]["required_videos"] == 9


def test_a_model_added_mid_edit_counts_as_a_change(client):
    """`updated_at` alone would miss it: a row *added* since the load changes
    no existing timestamp, and putting a model on the programme mid-month is an
    ordinary thing to do."""
    nour = _affiliate(client, "Nour", "nour@example.com")
    _save(client, [_row(nour["id"], (8, 5))])
    stale = _grid(client)["revision"]

    sara = _affiliate(client, "Sara", "sara@example.com")
    _save(client, [_row(sara["id"], (2, 1))])

    response = _save(client, [_row(nour["id"], (3, 3))], revision=stale)

    assert response.status_code == 409
