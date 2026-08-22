"""Password hashing."""

import pytest

from app.core.passwords import MINIMUM_PASSWORD_LENGTH, hash_password, verify_password


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
    # algorithm$iterations$salt$digest — the cost is stored with the hash, so
    # iterations can be raised later without invalidating existing passwords.
    algorithm, iterations, salt, digest = hash_password("a-long-enough-password").split("$")
    assert algorithm == "pbkdf2_sha256"
    assert int(iterations) >= 600_000
    assert salt and digest
