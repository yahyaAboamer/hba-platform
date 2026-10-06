"""The key that encrypts secrets saved from Settings.

The Shopify client secret (ADR 0045) and the Bosta and E-stebdal keys
(ADR 0057) are stored encrypted with Fernet, keyed by
``SETTINGS_ENCRYPTION_KEY``. Without a usable key nothing is saved, rather
than a secret stored under something that cannot protect it.
"""

from cryptography.fernet import Fernet

from app.config import settings


def fernet() -> Fernet | None:
    """This server's Fernet, or None if it has no usable key."""
    key = (settings.settings_encryption_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        # A malformed key is a configuration fault; saying so beats storing a
        # secret under something that is not a key.
        return None


def key_problem() -> str | None:
    """Why this server cannot use its key, in words - or None if it can.

    *Not set* and *not a valid key* are told apart: the second is the one
    somebody meets after pasting half a key, and being told the variable is
    missing sends them looking in the wrong place. Never includes the key.
    """
    if not (settings.settings_encryption_key or "").strip():
        return "SETTINGS_ENCRYPTION_KEY is not set"
    if fernet() is None:
        return (
            "SETTINGS_ENCRYPTION_KEY is set but is not a valid key "
            "(it must be a Fernet key: 44 characters of URL-safe base64)"
        )
    return None
