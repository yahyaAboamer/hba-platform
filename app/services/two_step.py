"""Two-step sign-in: a code after the password, on a browser not remembered.

ADR 0067, decision 5, as amended by the owner on 27 October 2026 (Phase 1
batch 1.3b). **Which code** (`sign_in_method`):

- anybody with an authenticator app on: a code from the app, or a recovery
  code - whatever their role;
- otherwise, anybody whose access needs a code by email (approving payroll or
  recording payments, not the owner) while the owner's switch is on, or any
  member of staff who turned email codes on: a six-digit code sent by email;
- otherwise nobody is asked. Models never are, and cannot turn either on.

The owner's requirement is the app (`required_method`), and only the owner can
be held by the set-up gate (`must_set_up`). A remembered browser
(`app/services/trusted_browsers.py`) skips the step for its own account.

## The authenticator

Phase 1 batch 3. The codes are the standard six-digit
ones (RFC 6238, through `pyotp`): a 30-second step, the step either side
accepted for a phone whose clock is a little off, and **each code accepted
once** - the last step used is kept, and a code for that step or an earlier one
is refused.

**Who must use it** is worked out from what a person holds, never stored: the
owner (`admin`), and anybody whose roles grant approving payroll or recording
payments. Whether they are *made* to is the owner's switch,
`TWO_STEP_ENFORCED`; see `must_set_up`.

**What is never written anywhere readable:** the secret (Fernet, the Settings
key), a code, a recovery code, a pending token. None of them is put in an
audit row, a log line or an exception message, and every refusal here says
only that something did not work - never what was expected.

## Recovery codes, and why they are hashed slowly

Ten codes of ten characters from a 31-letter alphabet with nothing that reads
as something else (no `0`/`o`, `1`/`l`/`i`): about 50 bits each. That is far
beyond guessing online - code attempts are throttled
(`app/core/throttle.py`) and a password is needed before any code is asked
for - but a plain sha256 of 50 bits is within reach of one graphics card in a
day for whoever has a copy of the table. So each is stored as PBKDF2-SHA256
with its own salt and 20,000 rounds: checking the ten together costs a person
signing in a fraction of a second and an attacker with the table some
billions of years. A server-side pepper would have done as well, but the only
server key is `SETTINGS_ENCRYPTION_KEY`, and recovery codes must keep working
on the day that key is missing - they are the way in when something is wrong.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import re
import secrets
import time
from datetime import datetime, timedelta

import pyotp
import segno
from cryptography.fernet import InvalidToken
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.businesstime import utcnow
from app.core.permissions import Permission, is_staff, permissions_of_roles
from app.core.secrets import fernet, key_problem
from app.config import settings
from app.models.identity import PendingSignIn, RecoveryCode, TwoStepSecret, UserAccount
from app.services.access import live_roles

#: The name an authenticator app shows above the codes.
ISSUER = "HBA"
STEP_SECONDS = 30
#: Steps either side of now that are still accepted: a phone a little fast or
#: slow, or a code typed just as it changed.
DRIFT_STEPS = 1

#: How long the password is good for while the code is typed.
PENDING_SECONDS = 5 * 60
#: An emailed code works for ten minutes, so its sign-in waits that long: an
#: email can take a minute to arrive, and a phone has to be found.
EMAIL_PENDING_SECONDS = 10 * 60
#: A new code may be asked for once a minute, five times per sign-in.
RESEND_SECONDS = 60
MAX_EMAIL_CODES = 5
#: However many codes are sent, a sign-in by email ends twenty minutes after
#: the password was typed.
EMAIL_SIGN_IN_LIMIT_SECONDS = 20 * 60
#: Wrong codes one sign-in takes before it stops working.
MAX_WRONG_CODES = 10
TOKEN_BYTES = 32

METHOD_AUTHENTICATOR = "authenticator"
METHOD_EMAIL = "email"

RECOVERY_CODE_COUNT = 10
#: Lower-case letters and digits, without any that read as another.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_LENGTH = 10
RECOVERY_ITERATIONS = 20_000

#: Holding either of these makes two-step sign-in required (ADR 0067). The
#: owner (`admin`) holds both; it is named as well so that it stays required
#: for the owner whatever the permissions become.
REQUIRED_PERMISSIONS = (Permission.PAYROLL_APPROVE, Permission.PAYMENTS_RECORD)
REQUIRED_ROLES = frozenset({"admin"})


class TwoStepError(Exception):
    """A refusal whose message is safe to show."""


class AlreadyOn(TwoStepError):
    pass


class NotStarted(TwoStepError):
    pass


class KeyUnavailable(TwoStepError):
    """This server cannot encrypt or read a secret. The message says why in
    words and never includes the key."""


def _timestamp() -> float:
    """Now, in seconds. A function so a test can move the clock."""
    return time.time()


def current_step(at: float | None = None) -> int:
    return int((_timestamp() if at is None else at) // STEP_SECONDS)


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


# ── Who must use it ───────────────────────────────────────────────────────────


def is_required(roles: frozenset[str]) -> bool:
    """Whether these live roles make two-step sign-in required (while the
    owner's switch is on)."""
    return required_method(roles) is not None


def required_method(roles: frozenset[str]) -> str | None:
    """What these roles are required to use: the app for the owner, a code by
    email for anybody else who can approve or pay money, nothing otherwise."""
    if roles & REQUIRED_ROLES:
        return METHOD_AUTHENTICATOR
    granted = permissions_of_roles(roles)
    if any(permission in granted for permission in REQUIRED_PERMISSIONS):
        return METHOD_EMAIL
    return None


def email_on(user: UserAccount) -> bool:
    """Whether this person turned email codes on themselves."""
    return user.two_step_email_at is not None


def sign_in_method(
    db: Session, user: UserAccount, roles: frozenset[str] | None = None
) -> str | None:
    """What a browser that is not remembered asks this person for after the
    password: `authenticator`, `email`, or None for nothing.

    The owner without the app yet, while the switch is on, is None here: the
    password signs them in and the set-up gate (`must_set_up`) then holds them
    to setting the app up, as in batch 1.3.
    """
    if is_enabled(db, user.id):
        return METHOD_AUTHENTICATOR
    roles = live_roles(db, user.id) if roles is None else roles
    return method_from(False, roles, email_on(user))


def method_from(authenticator_on: bool, roles: frozenset[str], chose_email: bool) -> str | None:
    """`sign_in_method` from facts already read - for lists of people."""
    if authenticator_on:
        return METHOD_AUTHENTICATOR
    if not is_staff(roles):
        # A model is never asked (ADR 0067). An account holding nothing - a
        # reactivated member of staff - reaches nothing to protect either.
        return None
    if chose_email:
        return METHOD_EMAIL
    if settings.two_step_enforced and required_method(roles) == METHOD_EMAIL:
        return METHOD_EMAIL
    return None


def _secret_row(db: Session, user_id: int, *, lock: bool = False) -> TwoStepSecret | None:
    query = select(TwoStepSecret).where(TwoStepSecret.user_account_id == user_id)
    if lock:
        # `populate_existing`: a row already in this session is refreshed from
        # the locked read, not served stale from the identity map - otherwise
        # the lock would guard a copy that may predate another request's write.
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def is_enabled(db: Session, user_id: int) -> bool:
    return (
        db.scalar(
            select(TwoStepSecret.id).where(
                TwoStepSecret.user_account_id == user_id,
                TwoStepSecret.enabled_at.is_not(None),
            )
        )
        is not None
    )


def enabled_account_ids(db: Session, account_ids: list[int]) -> set[int]:
    """Which of these accounts have two-step sign-in on, in one query."""
    if not account_ids:
        return set()
    return set(
        db.scalars(
            select(TwoStepSecret.user_account_id).where(
                TwoStepSecret.user_account_id.in_(account_ids),
                TwoStepSecret.enabled_at.is_not(None),
            )
        )
    )


def must_set_up(db: Session, user: UserAccount) -> bool:
    """Whether this person may do nothing but set two-step sign-in up.

    Only while the owner's switch is on. Cheap when it is off: nothing is read.
    """
    if not settings.two_step_enforced:
        return False
    roles = live_roles(db, user.id)
    return required_method(roles) == METHOD_AUTHENTICATOR and not is_enabled(db, user.id)


def status(db: Session, user: UserAccount) -> dict:
    """`two_step` in the session payload.

    `enabled` is the authenticator app; `email_on` the person's own choice of
    email codes; `method` what a new browser will ask them for now;
    `required` and `required_method` what their access needs while the
    owner's switch is on; `must_set_up` whether the set-up gate holds them
    (only ever the owner, without the app, while the switch is on).
    """
    roles = live_roles(db, user.id)
    enabled = is_enabled(db, user.id)
    needs = required_method(roles)
    return {
        "enabled": enabled,
        "required": needs is not None,
        "must_set_up": bool(
            settings.two_step_enforced and needs == METHOD_AUTHENTICATOR and not enabled
        ),
        "method": sign_in_method(db, user, roles),
        "email_on": email_on(user),
        "required_method": needs,
    }


def recovery_codes_left(db: Session, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(RecoveryCode)
            .where(RecoveryCode.user_account_id == user_id, RecoveryCode.used_at.is_(None))
        )
        or 0
    )


def enabled_at(db: Session, user_id: int) -> datetime | None:
    row = _secret_row(db, user_id)
    return row.enabled_at if row is not None else None


# ── Turning it on ─────────────────────────────────────────────────────────────


def _qr_svg(uri: str) -> str:
    """The QR code as an inline SVG, drawn here with no outside call.

    Sized by its `viewBox` so the screen decides how large it is, and on white
    so it scans in the dark theme too.

    **Written with its namespace.** The screen shows it as an image, and a
    browser draws an SVG image only if it says `xmlns`; `svg_inline` leaves
    that out, and the QR showed as a broken picture on staging (27 October).
    """
    out = io.BytesIO()
    segno.make(uri, error="m").save(
        out, kind="svg", xmldecl=False, svgns=True, nl=False,
        scale=1, border=4, omitsize=True, dark="#000", light="#fff",
        title="QR code for your authenticator app",
    )
    return out.getvalue().decode("utf-8")


def begin_setup(db: Session, user: UserAccount) -> dict:
    """A new secret to scan or type. Turns nothing on until `confirm_setup`.

    Starting again replaces a secret that was never confirmed, so a QR code
    shown on a screen somebody walked away from stops being any use.
    """
    box = fernet()
    if box is None:
        raise KeyUnavailable(key_problem() or "SETTINGS_ENCRYPTION_KEY cannot be used")
    row = _secret_row(db, user.id, lock=True)
    if row is not None and row.enabled_at is not None:
        raise AlreadyOn("Two-step sign-in is already on.")

    secret = pyotp.random_base32()
    encrypted = box.encrypt(secret.encode("ascii")).decode("ascii")
    if row is None:
        db.add(TwoStepSecret(user_account_id=user.id, secret_encrypted=encrypted))
    else:
        row.secret_encrypted = encrypted
        row.last_used_step = None
    db.flush()

    uri = pyotp.TOTP(secret, interval=STEP_SECONDS).provisioning_uri(
        name=user.email, issuer_name=ISSUER
    )
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": _qr_svg(uri)}


def confirm_setup(db: Session, user: UserAccount, code: str) -> list[str] | None:
    """Turn it on with one code from the new secret. Returns the ten recovery
    codes, to be shown once - or None when the code did not work."""
    row = _secret_row(db, user.id, lock=True)
    if row is None:
        raise NotStarted("Start setting up two-step sign-in first.")
    if row.enabled_at is not None:
        raise AlreadyOn("Two-step sign-in is already on.")
    if not _accept_authenticator_code(row, code):
        return None
    row.enabled_at = utcnow()
    db.flush()
    return new_recovery_codes(db, user.id)


def turn_off(db: Session, user_id: int) -> None:
    """Forget the secret and every recovery code, and cancel any sign-in
    still waiting on a code."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_account_id == user_id))
    db.execute(delete(TwoStepSecret).where(TwoStepSecret.user_account_id == user_id))
    cancel_pending(db, user_id)
    db.flush()


# ── Checking a code ───────────────────────────────────────────────────────────


def _six_digits(code: str | None) -> str | None:
    """Spaces are ignored (apps show `123 456`); anything else is not a code."""
    digits = re.sub(r"\s+", "", str(code or ""))
    return digits if re.fullmatch(r"\d{6}", digits) else None


def _decrypt(row: TwoStepSecret) -> str:
    box = fernet()
    if box is None:
        raise KeyUnavailable(key_problem() or "SETTINGS_ENCRYPTION_KEY cannot be used")
    try:
        return box.decrypt(row.secret_encrypted.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError):
        # Never the key, never the ciphertext.
        raise KeyUnavailable(
            "The two-step secret cannot be read with this server's "
            "SETTINGS_ENCRYPTION_KEY. Was the key changed?"
        ) from None


def _accept_authenticator_code(row: TwoStepSecret, code: str | None) -> bool:
    """Whether `code` is right for a step near now that has not been used.

    Every candidate step is compared, in constant time, whatever the earlier
    ones answered. The step it matched becomes the last one used, so neither
    this code nor any earlier one works again.
    """
    digits = _six_digits(code)
    if digits is None:
        return False
    totp = pyotp.TOTP(_decrypt(row), interval=STEP_SECONDS)
    now = current_step()
    matched: int | None = None
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        right = hmac.compare_digest(totp.generate_otp(step).encode(), digits.encode())
        fresh = row.last_used_step is None or step > row.last_used_step
        if right and fresh and matched is None:
            matched = step
    if matched is None:
        return False
    row.last_used_step = matched
    return True


def check_authenticator_code(db: Session, user_id: int, code: str | None) -> bool:
    """A code from the app, for somebody who has two-step sign-in on."""
    row = _secret_row(db, user_id, lock=True)
    if row is None or row.enabled_at is None:
        return False
    accepted = _accept_authenticator_code(row, code)
    if accepted:
        db.flush()
    return accepted


def is_authenticator_code(code: str | None) -> bool:
    """Whether this is shaped like the app's six digits rather than a
    recovery code. Only six digits can be guessed in a lifetime; a recovery
    code cannot."""
    return _six_digits(code) is not None


def check_code(db: Session, user_id: int, code: str | None) -> str | None:
    """An authenticator code or a recovery code. Returns which was used -
    `"code"` or `"recovery"` - or None when neither worked.

    A recovery code is spent by being accepted. It needs no key, so it still
    works on a server whose `SETTINGS_ENCRYPTION_KEY` has gone wrong.
    """
    if _six_digits(code) is not None:
        return "code" if check_authenticator_code(db, user_id, code) else None
    if not is_enabled(db, user_id):
        return None
    return "recovery" if _spend_recovery_code(db, user_id, code) else None


# ── Recovery codes ────────────────────────────────────────────────────────────


def _recovery_form(code: str | None) -> str | None:
    """With or without the dash, any case, spaces ignored."""
    plain = re.sub(r"[\s-]+", "", str(code or "")).lower()
    if len(plain) != RECOVERY_LENGTH or any(c not in RECOVERY_ALPHABET for c in plain):
        return None
    return plain


def _hash_recovery(plain: str, salt: bytes | None = None, iterations: int = RECOVERY_ITERATIONS) -> str:
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", plain.encode("ascii"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _recovery_matches(plain: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        expected = _hash_recovery(plain, bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(expected.rsplit("$", 1)[1], digest)


def new_recovery_codes(db: Session, user_id: int) -> list[str]:
    """Ten fresh codes, replacing every earlier one, spent or not. Returned
    readable this once; only their hashes are kept."""
    db.execute(delete(RecoveryCode).where(RecoveryCode.user_account_id == user_id))
    codes: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        plain = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        codes.append(f"{plain[:5]}-{plain[5:]}")
        db.add(RecoveryCode(user_account_id=user_id, code_hash=_hash_recovery(plain)))
    db.flush()
    return codes


def _spend_recovery_code(db: Session, user_id: int, code: str | None) -> bool:
    plain = _recovery_form(code)
    if plain is None:
        return False
    # Locked, so two requests with the same code cannot both spend it.
    unused = db.scalars(
        select(RecoveryCode)
        .where(RecoveryCode.user_account_id == user_id, RecoveryCode.used_at.is_(None))
        .order_by(RecoveryCode.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    found = None
    for row in unused:
        if _recovery_matches(plain, row.code_hash) and found is None:
            found = row
    if found is None:
        return False
    found.used_at = utcnow()
    db.flush()
    return True


# ── Half-way through signing in ───────────────────────────────────────────────


def start_pending(
    db: Session, user_id: int, ip_address: str | None, method: str = METHOD_AUTHENTICATOR
) -> str:
    """The right password, with the code still owed. Returns the raw token,
    which only the caller ever holds; its hash is stored.

    **Clears out what is spent on the way**, so the table holds only sign-ins
    that can still be finished plus a day's worth of the rest: this account's
    used or expired rows, and anybody's that expired more than a day ago. A
    day is kept for everybody else so a right password followed by wrong
    codes can still be traced the morning after.
    """
    now = utcnow()
    db.execute(
        delete(PendingSignIn).where(
            or_(
                and_(
                    PendingSignIn.user_account_id == user_id,
                    or_(PendingSignIn.used_at.is_not(None), PendingSignIn.expires_at <= now),
                ),
                PendingSignIn.expires_at <= now - timedelta(days=1),
            )
        )
    )
    token = secrets.token_urlsafe(TOKEN_BYTES)
    lives = EMAIL_PENDING_SECONDS if method == METHOD_EMAIL else PENDING_SECONDS
    db.add(
        PendingSignIn(
            user_account_id=user_id,
            token_hash=_hash_token(token),
            expires_at=utcnow() + timedelta(seconds=lives),
            ip_address=ip_address,
            method=method,
        )
    )
    db.flush()
    return token


def pending_seconds(method: str | None) -> int:
    return EMAIL_PENDING_SECONDS if method == METHOD_EMAIL else PENDING_SECONDS


# ── Codes by email ────────────────────────────────────────────────────────────


def _email_code_hash(token: str, code: str) -> str:
    """HMAC-SHA256 of the code, keyed by the raw pending token.

    Six digits are only a million possibilities, so a plain hash of one is
    reversed from a copy of the table at once. The key here is the token the
    browser holds and the table does not (it keeps only the token's sha256),
    so whoever reads the table still cannot tell which code is live.
    """
    return hmac.new(token.encode("utf-8"), code.encode("ascii"), hashlib.sha256).hexdigest()


def new_email_code(db: Session, row: PendingSignIn, token: str) -> str:
    """A fresh six-digit code for this sign-in. The previous one, if any,
    stops working, and the sign-in has ten minutes from now. Returns the code
    for the email; only its keyed hash is kept."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = utcnow()
    row.email_code_hash = _email_code_hash(token, code)
    row.email_code_sent_at = now
    row.email_codes_sent = (row.email_codes_sent or 0) + 1
    # Ten minutes from this code, but never past twenty from the password:
    # resending must not keep one sign-in open for an hour.
    row.expires_at = min(
        now + timedelta(seconds=EMAIL_PENDING_SECONDS),
        row.created_at + timedelta(seconds=EMAIL_SIGN_IN_LIMIT_SECONDS),
    )
    db.flush()
    return code


def count_wrong_code(row: PendingSignIn) -> bool:
    """Note one wrong code against this sign-in. Returns True when that was
    the tenth: the sign-in is then over, and going on needs the password
    again (and, by email, a new email the inbox's owner sees)."""
    row.wrong_codes = (row.wrong_codes or 0) + 1
    if row.wrong_codes >= MAX_WRONG_CODES:
        row.used_at = utcnow()
        return True
    return False


def resend_wait(row: PendingSignIn) -> tuple[str, int] | None:
    """Why a new code cannot be sent yet, and for how many seconds - or None.

    `("minute", s)` within a minute of the last one; `("spent", s)` once five
    have gone, with `s` the time this sign-in has left.
    """
    now = utcnow()
    if (row.email_codes_sent or 0) >= MAX_EMAIL_CODES:
        return "spent", max(1, int((row.expires_at - now).total_seconds()))
    if row.email_code_sent_at is not None:
        ready = row.email_code_sent_at + timedelta(seconds=RESEND_SECONDS)
        if ready > now:
            return "minute", max(1, int((ready - now).total_seconds()) + 1)
    return None


def check_email_code(row: PendingSignIn, token: str, code: str | None) -> bool:
    """Whether `code` is the code last emailed for this sign-in. Compared in
    constant time; works once, because the sign-in itself does."""
    digits = _six_digits(code)
    if digits is None or not row.email_code_hash:
        return False
    return hmac.compare_digest(row.email_code_hash, _email_code_hash(token, digits))


def masked_address(email: str) -> str:
    """`y•••@gmail.com`: enough for the person to know which inbox, not
    enough to read the address off a shoulder-surfed screen."""
    local, _, domain = str(email).partition("@")
    return f"{local[:1]}•••@{domain}" if domain else "•••"


def live_pending(db: Session, token: str | None) -> PendingSignIn | None:
    """The waiting sign-in this token names, locked - or None if it is
    unknown, spent or past its five minutes. All three read the same."""
    if not token or len(token) > 200:
        return None
    row = db.scalar(
        select(PendingSignIn)
        .where(PendingSignIn.token_hash == _hash_token(token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        return None
    return row


def cancel_pending(db: Session, user_id: int) -> int:
    """Every sign-in still waiting on a code for this account stops working.
    For a password reset, a suspension and a reset of two-step itself."""
    result = db.execute(
        update(PendingSignIn)
        .where(PendingSignIn.user_account_id == user_id, PendingSignIn.used_at.is_(None))
        .values(used_at=utcnow())
    )
    return int(result.rowcount or 0)
