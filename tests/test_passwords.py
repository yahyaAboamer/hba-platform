"""Password hashing."""

import pathlib

import pytest

from app.core import passwords
from app.core.passwords import (
    MINIMUM_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)


def test_correct_password_verifies():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", encoded) is True


def test_wrong_password_fails():
    encoded = hash_password("correct horse battery staple")
    assert verify_password("incorrect horse battery staple", encoded) is False


def test_same_password_produces_different_hashes():
    # A random salt per hash means identical passwords never collide, so a
    # leaked table cannot reveal which accounts share a password.
    assert hash_password("a-long-enough-password") != hash_password("a-long-enough-password")


def test_the_password_never_appears_in_the_hash():
    secret = "a-long-enough-password"
    assert secret not in hash_password(secret)


def test_short_passwords_are_rejected():
    with pytest.raises(ValueError):
        hash_password("a" * (MINIMUM_PASSWORD_LENGTH - 1))


def test_minimum_length_is_accepted():
    encoded = hash_password("a" * MINIMUM_PASSWORD_LENGTH)
    assert verify_password("a" * MINIMUM_PASSWORD_LENGTH, encoded) is True


def test_empty_and_none_passwords_are_rejected():
    with pytest.raises(ValueError):
        hash_password("")
    with pytest.raises(ValueError):
        hash_password(None)


def test_long_passwords_are_accepted():
    # No silent truncation: a 200-character passphrase verifies in full.
    long_password = "x" * 200
    encoded = hash_password(long_password)
    assert verify_password(long_password, encoded) is True
    assert verify_password("x" * 199, encoded) is False


def test_unicode_passwords_round_trip():
    passphrase = "كلمة-السر-الطويلة-جدا"
    encoded = hash_password(passphrase)
    assert verify_password(passphrase, encoded) is True


def test_malformed_hash_returns_false_rather_than_raising():
    # A corrupt or truncated column must fail closed, never crash a login.
    for bad in [
        "",
        "nonsense",
        "pbkdf2_sha256$notanumber$salt$hash",
        "pbkdf2_sha256$600000$only-three-parts",
        "$$$",
        None,
    ]:
        assert verify_password("anything", bad) is False


def test_unknown_algorithm_is_refused():
    # Prevents a downgrade to a weaker scheme by editing the stored prefix.
    encoded = hash_password("a-long-enough-password")
    tampered = encoded.replace("pbkdf2_sha256", "md5", 1)
    assert verify_password("a-long-enough-password", tampered) is False


def test_encoded_format_is_self_describing():
    """algorithm$iterations$salt$digest.

    The cost is stored **with** each hash, which is what lets it be raised
    later without invalidating existing passwords - and what lets this suite
    hash cheaply while production hashes properly.

    This asserts the *shape*. What the shipped cost actually is belongs to
    `test_the_shipped_password_cost_is_not_this_one`, which reads the source:
    checking the running value here would only confirm whatever the test
    session had set.
    """
    algorithm, iterations, salt, digest = hash_password(
        "a-long-enough-password"
    ).split("$")

    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) == passwords.ITERATIONS, (
        "the count written is the count used"
    )
    assert salt and digest


def test_a_hash_verifies_at_whatever_cost_it_was_made_with():
    """The property the self-describing format exists for. A password hashed
    at the old cost keeps working after the cost is raised - so raising it is
    a one-line change rather than a migration that logs everybody out.
    """
    from app.core import passwords

    original = passwords.ITERATIONS
    try:
        passwords.ITERATIONS = 1_000
        cheap = hash_password("a-long-enough-password")
        passwords.ITERATIONS = 50_000
        dearer = hash_password("a-long-enough-password")
    finally:
        passwords.ITERATIONS = original

    assert verify_password("a-long-enough-password", cheap)
    assert verify_password("a-long-enough-password", dearer)
    assert cheap.split("$")[1] != dearer.split("$")[1]


def test_the_shipped_password_cost_is_not_this_one():
    """The suite lowers the iteration count so it does not spend a minute a
    file hashing passwords nobody attacks. **That must never lower it in
    production.**

    Asserted from the source rather than the running value, because the running
    value is exactly what the test session has patched - checking it would
    confirm the patch rather than the shipped default, and pass no matter what
    was released.

    600,000 PBKDF2-SHA256 iterations is current OWASP guidance. Raising it
    later is safe: the count is stored in each digest, so existing passwords
    keep verifying at the cost they were made with.
    """
    source = pathlib.Path("app/core/passwords.py").read_text(encoding="utf-8")

    assert "ITERATIONS = 600_000" in source, (
        "The shipped password cost has changed. If that is deliberate, update "
        "this test and say why in the commit - it is a security parameter, not "
        "a tuning knob."
    )
