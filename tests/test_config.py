"""Settings, and the one input that used to stop the platform booting.

A dashboard gives two ways to stop using a setting: delete the variable, or
clear the box. They looked equivalent and were not - clearing it handed
pydantic `''` for an `int`, `Settings()` raised at import, and because
`migrations/env.py` imports this module, **every deploy died in `alembic
upgrade head`** before the app could log a thing.

That is not hypothetical: staging went down that way on 2026-09-02, and the
traceback named pydantic rather than the variable somebody had just edited.
"""

from app.config import Settings


def _settings(monkeypatch, **env) -> Settings:
    """Settings built from a controlled environment.

    `_env_file=None` matters: a developer's own `.env` would otherwise supply
    the very values these tests are trying to leave blank, and the test would
    pass on their machine for the wrong reason.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


# ── A blank is an absent one ────────────────────────────────────────────────


def test_a_blank_number_falls_back_to_the_default(monkeypatch):
    assert _settings(monkeypatch, SMTP_PORT="").smtp_port == 587


def test_a_blank_boolean_falls_back_to_the_default(monkeypatch):
    assert _settings(monkeypatch, SMTP_USE_TLS="").smtp_use_tls is True


def test_whitespace_counts_as_blank(monkeypatch):
    """Somebody clearing a field can easily leave a space behind, and a space
    is no more parseable as an integer than an empty string is.
    """
    assert _settings(monkeypatch, SMTP_PORT="   ").smtp_port == 587


def test_every_blanked_setting_together_still_builds(monkeypatch):
    """The real failure was several at once - the deploy reported two errors,
    and would have reported more had there been more.
    """
    settings = _settings(
        monkeypatch,
        SMTP_PORT="",
        SMTP_USE_TLS="",
        SMTP_TIMEOUT_SECONDS="",
        SESSION_HOURS="",
        SHOPIFY_TIMEOUT_SECONDS="",
    )
    assert settings.smtp_port == 587
    assert settings.session_hours == 12


# ── Real values are untouched ───────────────────────────────────────────────


def test_a_real_number_is_still_read(monkeypatch):
    assert _settings(monkeypatch, SMTP_PORT="2525").smtp_port == 2525


def test_a_real_boolean_is_still_read(monkeypatch):
    assert _settings(monkeypatch, SMTP_USE_TLS="false").smtp_use_tls is False


def test_a_blank_string_setting_stays_blank(monkeypatch):
    """The fallback is deliberately narrow. `smtp_host = ""` genuinely means
    "no SMTP host" and `mail_configured` already reads it that way - turning
    that into a default would invent a host nobody configured.
    """
    assert _settings(monkeypatch, SMTP_HOST="").smtp_host == ""


def test_a_nonsense_number_is_still_refused(monkeypatch):
    """Only blankness is forgiven. `SMTP_PORT=banana` is a mistake worth
    failing on, and quietly substituting 587 would hide it.
    """
    import pytest

    with pytest.raises(Exception):
        _settings(monkeypatch, SMTP_PORT="banana")
