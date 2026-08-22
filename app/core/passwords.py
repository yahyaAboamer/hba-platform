"""Password hashing using PBKDF2-HMAC-SHA256 from the standard library.

600,000 iterations follows current OWASP guidance for PBKDF2-SHA256. Using the
standard library keeps the dependency surface small and the code readable by
the person who maintains it.

The encoded form is self-describing:

    pbkdf2_sha256$600000$<base64 salt>$<base64 digest>

Storing the algorithm and iteration count alongside the digest means the cost
can be raised later without invalidating existing passwords, and an attempt to
downgrade the algorithm by editing the stored prefix is refused rather than
silently honoured.
"""

import base64
import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
MINIMUM_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    """Hash a password with a fresh random salt.

    A random salt per hash means two people choosing the same password produce
    different digests, so a leaked table cannot reveal which accounts share
    one.
    """
    if not isinstance(password, str) or len(password) < MINIMUM_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must contain at least {MINIMUM_PASSWORD_LENGTH} characters"
        )
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(
        [
            ALGORITHM,
            str(ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password in constant time.

    Fails closed: a corrupt, truncated, or tampered stored value returns False
    rather than raising, so a damaged row cannot crash a login, and an edited
    algorithm prefix cannot force a weaker scheme.
    """
    try:
        algorithm, iterations, salt_b64, digest_b64 = str(encoded).split("$")
        if algorithm != ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", (password or "").encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError, base64.binascii.Error):
        return False
    return hmac.compare_digest(candidate, expected)
