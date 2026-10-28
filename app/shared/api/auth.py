"""Authentication endpoints."""

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.shared.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    actor_payload,
    client_address,
    current_user,
    permission_list,
    require_permission,
    roles_of,
    signed_in,
)
from app.config import settings
from app.core.businesstime import utcnow
from app.core.password_quality import password_problem, password_strength
from app.core.passwords import MINIMUM_PASSWORD_LENGTH, hash_password
from app.core.periods import PLATFORM_START_MONTH
from app.core.permissions import (
    GRANT_REFUSED,
    VALID_ROLES,
    Permission,
    can_invite,
    is_staff,
    sorted_roles,
)
from app.core import throttle
from app.db import get_session
from app.shared.models.identity import Invitation, RoleAssignment, UserAccount
from app.shared.services.audit import record_audit
from app.shared.services import trusted_browsers, two_step
from app.shared.services.auth import (
    authenticate,
    ensure_csrf,
    issue_session,
    live_sessions,
    resolve_session,
    revoke_all_sessions,
    revoke_other_sessions,
    revoke_session,
    revoke_session_by_id,
    session_for_token,
    session_rows,
)
from app.shared.services.invitations import (
    accept_invitation,
    create_invitation,
    preview_invitation,
)
from app.shared.services.notifications import (
    invitation_link,
    invitation_sent,
    password_reset_requested,
    sign_in_code,
)
from app.shared.services.password_resets import (
    complete_reset,
    preview_reset,
    request_reset,
)
from app.modules.affiliates.services.payroll import go_live_month, working_month

router = APIRouter(prefix="/api/auth")


class BootstrapBody(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class InviteBody(BaseModel):
    email: EmailStr
    role: str
    #: Optional. The invitation email greets her by it ("Hi Sara,"), and says
    #: "Hello," without it.
    name: str = Field(default="", max_length=120)


class AcceptInviteBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    # Optional, because the screen that used to ask for it no longer does. A
    # model is asked their name once, on the details step that follows, and
    # `submit_application` writes it to the account as well - so there is one
    # name rather than two that disagree. Staff, who have no details step,
    # still send one.
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)


def _client_ip(request: Request) -> str | None:
    return client_address(request)


def _source(request: Request) -> str | None:
    """The address an attempt came from, for the sign-in limits - or None.

    None when no public visitor address is known (Railway's health check, this
    machine): keying limits on a shared address would pool every visitor into
    one, so one person's mistakes could pause everybody. Only the per-account
    limits apply then. Anything that is not an address at all (a test client's
    name) is used as it is.
    """
    host = client_address(request)
    if not host:
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    return host if address.is_global else None


def _paused(seconds: int) -> HTTPException:
    return HTTPException(
        429, throttle.try_again_message(seconds), headers={"Retry-After": str(seconds)}
    )


def _set_cookie(response: Response, token: str, csrf: str) -> None:
    """Both halves of a session, with the same lifetime.

    **They must expire together.** An earlier version set only the session
    cookie and handed the CSRF token to the page to keep in `sessionStorage` -
    which the browser throws away when the tab closes, while a twelve-hour
    cookie survives it. Reopening the tab left a live session and no token:
    every read worked, the interface showed a signed-in administrator, and
    every write failed saying authentication was required.

    So the token is a cookie too, deliberately **readable by the page** - the
    double-submit pattern. The page reads it and echoes it in a header, and
    `resolve_session` compares that header against the hash on the session row
    exactly as before.

    Readable costs nothing here. An attacker on another origin cannot read our
    cookies, and `SameSite=lax` means the session cookie is not sent on a
    cross-site POST at all, so producing the header remains something only our
    own page can do. Script already running on this origin could read
    `sessionStorage` and make credentialed same-origin requests regardless.
    """
    common = {
        "max_age": settings.session_hours * 3600,
        "secure": settings.is_production,
        "samesite": "lax",
        "path": "/",
    }
    # The session token is never readable by script. That has not changed and
    # is the half that actually authenticates.
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    _set_csrf_cookie(response, csrf)


def _set_csrf_cookie(response: Response, csrf: str) -> None:
    """The readable half, on its own.

    Separate because `/me` repairs a session that has lost it, and doing that
    must not touch the session cookie - re-issuing that would extend a session
    every time a page loaded.
    """
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.session_hours * 3600,
        secure=settings.is_production,
        samesite="lax",
        path="/",
        httponly=False,
    )


@router.get("/needs-setup")
def needs_setup(db: Session = Depends(get_session)) -> dict:
    """Whether this deployment has an administrator yet.

    Unauthenticated, because the only person who can ask is somebody looking at
    a platform with nobody in it.

    **This does disclose something**, and it is worth being clear about what:
    an anonymous caller learns whether a fresh deployment is unclaimed. That is
    already true of `POST /bootstrap`, which answers 201 or 409 to the same
    question, so this reveals nothing the endpoint it fronts did not - and it
    *shortens* the window rather than lengthening it, because the owner can now
    find the form instead of hunting for a curl command.

    The window is the exposure. A deployment is unclaimed from the moment it is
    reachable until somebody bootstraps it, and the mitigation is to do that
    immediately - which is the whole reason this endpoint exists.
    """
    return {"needs_setup": not db.scalar(select(func.count()).select_from(UserAccount))}


@router.post("/bootstrap", status_code=201)
def bootstrap(
    body: BootstrapBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Create the very first administrator.

    Refused once any account exists, so it cannot be used to add a second
    admin later. There is no default password: the first administrator
    chooses their own, and nobody else ever sees it.
    """
    if db.scalar(select(func.count()).select_from(UserAccount)):
        raise HTTPException(409, "An account already exists")

    # The very first administrator, and the account with the most reach in the
    # platform. The same rules everybody else gets - there is no argument for
    # holding the owner to a lower standard than the people they pay.
    problem = password_problem(
        body.password, personal=(str(body.email), body.display_name)
    )
    if problem is not None:
        raise HTTPException(422, problem)

    user = UserAccount(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        status="active",
        display_name=body.display_name.strip(),
    )
    db.add(user)
    db.flush()
    db.add(RoleAssignment(user_account_id=user.id, role="admin"))

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.bootstrap",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after={"email": user.email, "role": "admin"},
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, csrf)
    return {"actor": actor_payload(db, user), "csrf": csrf}


@router.get("/status")
def status(db: Session = Depends(get_session)) -> dict:
    """Whether the platform still needs its first administrator."""
    return {
        "setup_required": not db.scalar(select(func.count()).select_from(UserAccount))
    }


@router.post("/login")
def login(
    body: LoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    # Checked before the password, and the right password is refused while
    # paused: otherwise a pause only slows a guess (security audit, Oct 2026).
    # Counted before the password is checked, so attempts arriving together
    # cannot all slip under the limit.
    email = str(body.email).strip().lower()
    source = _source(request)
    checks = [(throttle.LOGIN_PER_ACCOUNT, email)]
    if source is not None:
        checks += [
            (throttle.LOGIN_PER_PAIR, f"{email}|{source}"),
            (throttle.LOGIN_PER_SOURCE, source),
        ]
    wait = throttle.acquire_all(checks)
    if wait:
        raise _paused(wait)

    user = authenticate(db, str(body.email), body.password, record_login=False)
    if user is None:
        # One message for both causes. Distinguishing them would confirm which
        # email addresses have accounts.
        raise HTTPException(401, "Incorrect email or password")
    # It worked, so it was never a failed attempt.
    throttle.LOGIN_PER_ACCOUNT.clear(email)
    if source is not None:
        throttle.LOGIN_PER_PAIR.clear(f"{email}|{source}")
        throttle.LOGIN_PER_SOURCE.release(source)

    roles = roles_of(db, user)
    method = two_step.sign_in_method(db, user, roles)
    if method is None:
        return _sign_in(db, request, response, user)
    # A browser this account remembered skips the code - never the password,
    # and never for anybody else's account (ADR 0067, decision 5).
    if trusted_browsers.use(
        db,
        user.id,
        request.cookies.get(trusted_browsers.COOKIE),
        method_now=method,
        roles=roles,
    ):
        return _sign_in(db, request, response, user, after={"remembered_browser": True})
    return _code_owed(db, request, user, method)


def _count_code_email(user: UserAccount) -> None:
    """Count one sign-in code email against the account's send limits, or
    refuse before anything is written or sent."""
    key = f"user:{user.id}"
    wait = throttle.acquire_all(
        [(throttle.SIGN_IN_CODE_SENDS, key), (throttle.SIGN_IN_CODE_SENDS_DAY, key)]
    )
    if wait:
        raise _paused(wait)


def _code_owed(db: Session, request: Request, user: UserAccount, method: str) -> dict:
    """Half of it: the password was right and a code is owed. **No session
    and no cookie** - the token returned is good only for exchanging, with a
    code, at `/login/two-step`, once. Not audited as a sign-in, because it is
    not one.

    For an emailed code the code is made and queued here, in this
    transaction, and only a keyed hash of it is kept.
    """
    if method == two_step.METHOD_EMAIL:
        # Before the sign-in exists: past the limit there is no pending row
        # and no email.
        _count_code_email(user)
    pending = two_step.start_pending(db, user.id, _client_ip(request), method)
    answer = {
        "two_step": "code",
        "method": method,
        "pending": pending,
        "expires_in": two_step.pending_seconds(method),
    }
    if method == two_step.METHOD_EMAIL:
        row = two_step.live_pending(db, pending)
        sign_in_code(db, user, two_step.new_email_code(db, row, pending))
        answer["sent_to"] = two_step.masked_address(user.email)
    db.commit()
    return answer


def _set_trusted_cookie(response: Response, token: str) -> None:
    """`hba_trusted`: HttpOnly, SameSite=Lax, Secure as the session cookie
    is, the whole site, 30 days - the life of the row it names."""
    response.set_cookie(
        trusted_browsers.COOKIE,
        token,
        max_age=trusted_browsers.DAYS * 24 * 3600,
        secure=settings.is_production,
        httponly=True,
        samesite="lax",
        path="/",
    )


def _drop_trusted_cookie(response: Response) -> None:
    response.delete_cookie(trusted_browsers.COOKIE, path="/")


def _this_browser(db: Session, request: Request, user_id: int) -> int | None:
    """The remembered-browser row this request's cookie names for this
    account, if it is live."""
    row = trusted_browsers.live_for(db, user_id, request.cookies.get(trusted_browsers.COOKIE))
    return row.id if row is not None else None


forget_browsers = trusted_browsers.forget_audited


def _sign_in(
    db: Session,
    request: Request,
    response: Response,
    user: UserAccount,
    *,
    after: dict | None = None,
) -> dict:
    """Issue the session, record the sign-in, set both cookies.

    `auth.login` is written here and only here, once a session actually
    exists - a right password still waiting on its code is not a sign-in.
    """
    user.last_login_at = utcnow()
    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.login",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after=after,
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, csrf)
    return {"actor": actor_payload(db, user), "csrf": csrf}


#: The words of the two-step refusals. The screens show them as they are.
SIGN_IN_TOO_SLOW = "Sign-in took too long. Start again."
CODE_DID_NOT_WORK = "That code did not work."
CODE_DID_NOT_WORK_CHECK_TIME = (
    "That code did not work. Check the time on your phone and try again."
)
TWO_STEP_UNAVAILABLE = "Two-step sign-in is unavailable right now. Try again shortly."
#: The tenth wrong code for one sign-in ends it.
TOO_MANY_WRONG_CODES = "Too many wrong codes. Start again."
#: The words of the password re-check, as before a payout destination changes
#: (`app/api/affiliate_self.py`).
PASSWORD_NOT_RIGHT = "That password is not right"
REQUIRED_CANNOT_TURN_OFF = (
    "Your access needs two-step sign-in. If you lost your phone, the owner can reset it."
)


class TwoStepLoginBody(BaseModel):
    pending: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=40)
    #: *Remember this browser for 30 days*. The screen ticks it by default;
    #: absent means no.
    remember: bool = False


@router.post("/login/two-step")
def login_two_step(
    body: TwoStepLoginBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """The second step: the pending token from `/login` and a code - from the
    authenticator app, or one of the recovery codes.

    **A wrong code leaves the pending sign-in usable** until it expires or the
    limits stop it, so a mistyped digit does not send somebody back to the
    password. Guessing is limited per account and per account-and-address
    (`throttle.TWO_STEP_*`), and only somebody who typed the right password
    ever reaches it.

    Expired, already used and unknown all read alike (410): the person's next
    move is the same, and nothing here says which tokens ever existed.
    """
    pending = two_step.live_pending(db, body.pending)
    if pending is None:
        raise HTTPException(410, SIGN_IN_TOO_SLOW)
    user = db.get(UserAccount, pending.user_account_id)
    by_email = pending.method == two_step.METHOD_EMAIL
    if (
        user is None
        or user.status != "active"
        or (not by_email and not two_step.is_enabled(db, user.id))
    ):
        # Suspended, or two-step reset, since the password was typed: the
        # sign-in it was part of is over. Starting again is the right answer
        # in every case.
        pending.used_at = utcnow()
        db.commit()
        raise HTTPException(410, SIGN_IN_TOO_SLOW)

    # Counted before the code is checked, and the right code is refused while
    # paused - the same reasoning as the password's.
    account = f"user:{user.id}"
    source = _source(request)
    short = [(throttle.TWO_STEP_PER_ACCOUNT, account)]
    if source is not None:
        short.append((throttle.TWO_STEP_PER_PAIR, f"{account}|{source}"))
    # **The day's ceiling holds six digits only** - an emailed code is six
    # digits too, so it counts. Somebody who already has
    # the password could otherwise spend the owner's fifty and keep them out
    # for a day, with nobody able to lift it (an owner cannot reset their
    # own). A recovery code is 50 bits - not guessable at the short limits in
    # any lifetime - so it stays the way in when the ceiling is reached.
    daily = (
        [(throttle.TWO_STEP_PER_DAY, account)]
        if two_step.is_authenticator_code(body.code)
        else []
    )
    checks = daily + short
    wait = throttle.acquire_all(checks)
    if wait:
        raise _paused(wait)

    try:
        if by_email:
            # Only the emailed code: a recovery code belongs to the app.
            used = (
                "email"
                if two_step.check_email_code(pending, body.pending, body.code)
                else None
            )
        else:
            used = two_step.check_code(db, user.id, body.code)
    except two_step.KeyUnavailable:
        # The server cannot read the secret: the code was never judged, so
        # it does not count against them. A recovery code still works.
        #
        # **Generic words here**: this person is not signed in yet, and why
        # the server's key cannot be used is the owner's business, not
        # theirs. The signed-in `/two-step/start` still says it exactly.
        db.rollback()
        for limit, key in checks:
            limit.release(key)
        raise HTTPException(503, TWO_STEP_UNAVAILABLE) from None
    if used is None:
        # Counted against this sign-in as well as the limits above; the
        # tenth ends it (nothing else was changed by a wrong code, so this
        # commit writes only the count).
        ended = two_step.count_wrong_code(pending)
        db.commit()
        if ended:
            raise HTTPException(410, TOO_MANY_WRONG_CODES)
        raise HTTPException(401, CODE_DID_NOT_WORK)

    # Right, so the day's count takes its attempt back - it counts wrong
    # codes only - and the short limits start afresh.
    for limit, key in daily:
        limit.release(key)
    for limit, key in short:
        limit.clear(key)
    pending.used_at = utcnow()

    left = None
    if used == "recovery":
        left = two_step.recovery_codes_left(db, user.id)
        record_audit(
            db,
            action="auth.two_step.recovery_used",
            subject=f"user:{user.id}",
            actor_id=user.id,
            actor_email=user.email,
            after={"recovery_codes_left": left},
            ip_address=_client_ip(request),
        )
    after = {"two_step": used}
    remembered = None
    if body.remember:
        remembered = trusted_browsers.remember(
            db,
            user.id,
            request.headers.get("user-agent"),
            _client_ip(request),
            # A recovery code belongs to the app.
            two_step.METHOD_EMAIL if used == "email" else two_step.METHOD_AUTHENTICATOR,
        )
        after["remembered"] = True
    payload = _sign_in(db, request, response, user, after=after)
    if remembered is not None:
        _set_trusted_cookie(response, remembered)
    if left is not None:
        payload["recovery_codes_left"] = left
    return payload


class ResendBody(BaseModel):
    pending: str = Field(min_length=1, max_length=200)


#: Refused when a sign-in waiting on the app is asked to email a code.
NOT_AN_EMAIL_SIGN_IN = "This sign-in does not use a code by email."
#: Refused after the fifth code for one sign-in.
NO_MORE_CODES = "That is as many codes as one sign-in can send. Start again."


@router.post("/login/resend")
def resend_sign_in_code(
    body: ResendBody,
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """*Send a new code*: the old one stops working. Once a minute, five per
    sign-in; the sign-in then has ten minutes from the new code."""
    pending = two_step.live_pending(db, body.pending)
    if pending is None:
        raise HTTPException(410, SIGN_IN_TOO_SLOW)
    user = db.get(UserAccount, pending.user_account_id)
    if user is None or user.status != "active":
        pending.used_at = utcnow()
        db.commit()
        raise HTTPException(410, SIGN_IN_TOO_SLOW)
    if pending.method != two_step.METHOD_EMAIL:
        raise HTTPException(409, NOT_AN_EMAIL_SIGN_IN)
    waiting = two_step.resend_wait(pending)
    if waiting is not None:
        why, seconds = waiting
        detail = NO_MORE_CODES if why == "spent" else throttle.try_again_message(seconds)
        raise HTTPException(429, detail, headers={"Retry-After": str(seconds)})
    _count_code_email(user)
    sign_in_code(db, user, two_step.new_email_code(db, pending, body.pending))
    db.commit()
    return {
        "sent_to": two_step.masked_address(user.email),
        # Ten minutes, or less once the sign-in nears its twenty.
        "expires_in": max(1, int((pending.expires_at - utcnow()).total_seconds())),
    }


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """End the session. **Deliberately not behind the CSRF check.**

    Every other write on the platform requires the token. This one does not,
    and the reasoning is worth stating because it looks like a hole and is not.

    What CSRF protection buys on a logout is preventing somebody being signed
    out of their own session by a page they did not mean to visit. That is a
    nuisance: it reads nothing, changes nothing, and moves no money.

    What enforcing it costs is somebody who **cannot sign out** - which the
    platform did twice in production, once leaving a live administrator session
    on a machine after the person had asked to leave it. On a shared computer
    that is a real exposure, and it is strictly worse than the attack it was
    guarding against.

    So this resolves the session itself rather than depending on
    `current_user`, and revokes it whatever the browser managed to send.

    **Idempotent.** Signing out of a session that is already gone is not an
    error; it is the outcome the person asked for. The cookies are cleared
    either way, so a browser holding something stale does not keep it.
    """
    token = request.cookies.get(SESSION_COOKIE, "")
    # No CSRF argument: this is the one route that does not check it.
    user = resolve_session(db, token) if token else None

    revoke_session(db, token)
    if user is not None:
        record_audit(
            db,
            action="auth.logout",
            subject=f"user:{user.id}",
            actor_id=user.id,
            actor_email=user.email,
            ip_address=_client_ip(request),
        )
    db.commit()

    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"success": True}


@router.get("/me")
def me(
    request: Request,
    response: Response,
    # Not behind the two-step gate: somebody who must set it up still needs
    # to know who they are, and the screen reads `two_step` from here.
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """Who is signed in, and what they may do.

    **It also repairs a session that cannot write.** The page loads this first,
    so it is the one place guaranteed to run before anything is attempted - and
    a session holding no usable CSRF token is exactly the state that made every
    write fail while the interface looked perfectly healthy.

    `ensure_csrf` rotates only when the token is missing or wrong, so a second
    tab does not invalidate the first.
    """
    issued = ensure_csrf(db, request.cookies.get(SESSION_COOKIE, ""), request.cookies.get(CSRF_COOKIE))
    if issued is not None:
        db.commit()
        _set_csrf_cookie(response, issued)

    return {
        "actor": actor_payload(db, user),
        "permissions": permission_list(db, user),
        "platform": {
            "working_month": working_month(),
            "go_live_month": go_live_month() or None,
            # The first month anything can be known in. The admin's month
            # control offers every month from here, so the browser is told
            # rather than keeping a second copy of the constant.
            "start_month": PLATFORM_START_MONTH,
        },
    }


@router.post("/invitations", status_code=201)
def invite(
    body: InviteBody,
    request: Request,
    actor: UserAccount = Depends(require_permission(Permission.INVITATIONS_SEND)),
    db: Session = Depends(get_session),
) -> dict:
    """Invite somebody and choose their role.

    **Emails the link, and still returns the token.** The email is the flow
    that matters - twenty invitations on the night before go-live should be
    twenty presses, not twenty copy-pastes into a mail client. The token comes
    back anyway because the platform runs perfectly well with no mail
    credentials, and on a machine in that state the copyable link is the only
    way in.

    Queued in this transaction, like every other notification (§16), so an
    invitation that commits always carries the email that delivers it.
    """
    if body.role not in VALID_ROLES:
        raise HTTPException(422, f"Unknown role: {body.role}")
    # An invitation is a grant: nobody may give access they do not hold.
    # Against everything the inviter holds together (ADR 0067).
    held = roles_of(db, actor)
    if not can_invite(held, body.role):
        raise HTTPException(403, GRANT_REFUSED)
    # Inviting replaces any live invitation for the address, so it must not
    # be a way to cancel one for access this person could not have given.
    live = db.scalars(
        select(Invitation.role).where(
            func.lower(Invitation.email) == str(body.email).strip().lower(),
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > utcnow(),
        )
    ).all()
    if any(not can_invite(held, other) for other in live):
        raise HTTPException(
            403,
            "This address already has a live invitation that only somebody with "
            "more access can replace.",
        )

    try:
        token, invitation = create_invitation(
            db, str(body.email), body.role, actor.id, name=body.name
        )
    except ValueError as exc:
        # Already a model, or already has an account. Both are ordinary
        # mistakes with readable answers, not server errors.
        raise HTTPException(409, str(exc)) from exc
    # §13, and the reason `create_invitation` keeps only the hash: the raw
    # token is a credential. It is erased from the outbox the moment the email
    # goes out - see `_forget_secrets`.
    queued = invitation_sent(db, invitation.email, token, body.role, invitation.name)

    record_audit(
        db,
        action="invitation.create",
        subject=f"invitation:{body.email}",
        actor_id=actor.id,
        actor_email=actor.email,
        after={"email": str(body.email).lower(), "role": body.role},
        ip_address=_client_ip(request),
    )
    db.commit()
    return {
        "invitation": {
            "email": invitation.email,
            "role": invitation.role,
            "expires_at": invitation.expires_at.isoformat(),
        },
        "token": token,
        # **Built here, not by the screen.** The screen used to assemble its
        # own link from the browser's address bar while the email assembled a
        # different one from PUBLIC_BASE_URL - and on 2026-09-02 they differed,
        # so the maintainer saw a working link and the model received a dead
        # one. Empty means the platform does not know its own address, which
        # the screen reports rather than hiding.
        "link": invitation_link(token),
        # Whether the platform will actually send it: a notification was
        # queued, and there are credentials to send it with. The screen shows
        # the copyable link either way - a link that was emailed is still worth
        # having when somebody says it never arrived - but it must not claim to
        # have sent an email it only queued into a void, nor deny sending one
        # it did send.
        "emailed": queued is not None and settings.mail_configured,
    }


class PasswordCheckBody(BaseModel):
    password: str = Field(max_length=256)
    #: Their own address, when the screen knows it. The accept page does; the
    #: bootstrap form does too.
    email: str = Field(default="", max_length=320)
    name: str = Field(default="", max_length=120)


@router.post("/password-quality")
def password_quality(body: PasswordCheckBody) -> dict:
    """How strong this password is, and why it might be refused.

    **A POST, and never a GET.** The password is in the body because a query
    string is written to every access log it passes through; that is the whole
    reason this is not the obvious `?password=` route.

    **Unauthenticated by necessity** - it is called before an account exists,
    which is the moment it is needed. It touches no database and hashes
    nothing, so there is nothing here to exhaust.

    ## Why the server answers this at all

    The meter could have been written in the browser and saved a round trip.
    It would then be a second implementation of the rules, and the day it
    drifted the symptom would be a green bar over a password the server
    refuses - a screen telling somebody they are fine while the button does
    not work. This codebase already carries a comment about two copies of a
    filter ending in a model paid for somebody else's orders. Same class of
    problem, so: one implementation, and the meter asks it.
    """
    personal = tuple(part for part in (body.email, body.name) if part.strip())
    return {
        "strength": password_strength(body.password, personal=personal),
        "problem": password_problem(body.password, personal=personal),
        "minimum": MINIMUM_PASSWORD_LENGTH,
    }


class ResetRequestBody(BaseModel):
    email: EmailStr


class ResetBody(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=MINIMUM_PASSWORD_LENGTH, max_length=256)


@router.post("/password-reset/request", status_code=202)
def request_password_reset(
    body: ResetRequestBody,
    request: Request,
    db: Session = Depends(get_session),
) -> dict:
    """Ask for a link back into an account.

    **202 always, whatever happened.** An address with no account, a suspended
    one, and a live one all get the same answer. Anything else would make this
    a way to ask "is this person on the programme" - and the people on this
    programme are named individuals whose association with HBA is theirs to
    disclose, not this endpoint's.

    The person who genuinely owns the address learns the answer the only way
    that matters: an email arrives, or it does not.
    """
    # Limited per address, never per account alone: a stranger must not be able
    # to use up the owner's reset emails, or the way back in could be blocked
    # (security audit, October 2026).
    # Past a cap nothing is sent and the answer is still "sent": a refusal here
    # would say the address is real.
    source = _source(request)
    email = str(body.email).strip().lower()
    if source is not None:
        wait = throttle.RESET_PER_SOURCE.acquire(source)
        if wait:
            raise _paused(wait)
        if throttle.RESET_PER_PAIR.acquire(f"{email}|{source}"):
            return {"sent": True}
    elif throttle.RESET_PER_ACCOUNT.acquire(email):
        # Only the proxy's address is visible, so the limit falls back to the
        # email alone rather than switching off.
        return {"sent": True}

    started = request_reset(db, str(body.email), ip_address=_client_ip(request))
    if started is not None:
        token, account = started
        password_reset_requested(db, account, token)
        record_audit(
            db,
            action="auth.password_reset_requested",
            subject=f"user:{account.id}",
            actor_id=account.id,
            actor_email=account.email,
            ip_address=_client_ip(request),
        )
    db.commit()
    return {"sent": True}


@router.get("/password-reset/preview")
def preview_password_reset(token: str, db: Session = Depends(get_session)) -> dict:
    """Whose link this is, without spending it.

    Checked on load rather than on submit, for the reason the invitation
    screen is: a dead link that renders a whole form makes somebody choose a
    password before telling them it was never going to work.
    """
    try:
        account = preview_reset(db, token)
    except ValueError as exc:
        raise HTTPException(410, str(exc)) from exc
    return {"email": account.email}


@router.post("/password-reset")
def complete_password_reset(
    body: ResetBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Set the new password, and sign them in.

    **Every other session ends here.** If the password was reset because
    somebody else had it, the sessions they opened with it must not outlive
    the change - and the person doing the resetting has no way to know which
    of those two situations they are in.

    Signed straight in afterwards, because the alternative is a sign-in form
    asking for the password they typed ten seconds ago.
    """
    try:
        account = complete_reset(db, body.token, body.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    ended = revoke_all_sessions(db, account.id)
    # A sign-in half done with the old password must not be finished either.
    two_step.cancel_pending(db, account.id)
    # They have just proved they own the address, so a pause from somebody
    # else's guessing must not keep them out.
    owner = account.email.strip().lower()
    throttle.LOGIN_PER_ACCOUNT.clear(owner)
    source = _source(request)
    if source is not None:
        throttle.LOGIN_PER_PAIR.clear(f"{owner}|{source}")
    throttle.PASSWORD_RECHECK.clear(f"user:{account.id}")
    # **The code limits are not cleared.** A reset proves the mailbox, which
    # is exactly what the second step must be more than: clearing them here
    # would give whoever reads the mail a fresh round of guesses per reset.
    record_audit(
        db,
        action="auth.password_reset",
        subject=f"user:{account.id}",
        actor_id=account.id,
        actor_email=account.email,
        after={"sessions_ended": ended},
        ip_address=_client_ip(request),
    )
    # Every remembered browser too: if the password was somebody else's, so
    # may a remembered browser be.
    forget_browsers(
        db, account, actor=account, why="password_reset", ip_address=_client_ip(request)
    )

    if two_step.is_enabled(db, account.id):
        # **A reset link is not the app's code.** It proves somebody can read
        # the mailbox; for somebody whose second step is the app, signing
        # straight in here would make it worth no more than the email
        # account, so they are asked for their code, exactly as at sign-in,
        # with the new password already set.
        #
        # For somebody whose second step *is* the mailbox (a code by email),
        # the reset link has just proved exactly that, so they are signed in
        # below as before (ADR 0067, decision 5 as amended).
        return _code_owed(db, request, account, two_step.METHOD_AUTHENTICATOR)

    token, csrf, _ = issue_session(
        db, account.id, _client_ip(request), request.headers.get("user-agent")
    )
    db.commit()
    _set_cookie(response, token, csrf)
    return {"actor": actor_payload(db, account), "csrf": csrf}


@router.get("/invitations/preview")
def preview(token: str, db: Session = Depends(get_session)) -> dict:
    """Is this link still good, and who is it for?

    Unauthenticated by necessity - the person opening it has no account yet,
    which is the entire point of the link. The token is the credential, exactly
    as it is for accepting, and the same three checks apply.

    Two problems this solves at once:

    - **A dead link used to render the whole form.** Somebody withdrawn hours
      earlier still chose a name and a password before being refused, and
      withdrawing looked like it had done nothing.
    - **The first screen could not name the account.** It asked for a password
      with no indication of which address it belonged to, which reads as a
      form arriving out of nowhere.

    Returning the address is safe: whoever holds the link was sent it.
    """
    try:
        invitation = preview_invitation(db, token)
    except ValueError as exc:
        # 410, not 404: the link was real and is now spent. The screen shows
        # this message verbatim, so it has to read as a sentence.
        raise HTTPException(410, str(exc)) from exc
    return {"email": invitation.email, "role": invitation.role, "name": invitation.name}


@router.post("/invitations/accept", status_code=201)
def accept(
    body: AcceptInviteBody,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
) -> dict:
    """Turn an invitation into an account, then sign the new person in."""
    try:
        user = accept_invitation(db, body.token, body.password, body.display_name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="invitation.accept",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        # Every role the acceptance gave, so the trail shows the Inbox an
        # operations manager's invitation brings with it (ADR 0067).
        after={"email": user.email, "roles": sorted_roles(roles_of(db, user))},
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, csrf)
    return {"actor": actor_payload(db, user), "csrf": csrf}


# ── Two-step sign-in for the signed-in person (ADR 0067, decision 5) ─────────
#
# Behind `signed_in`, not `current_user`: these are what somebody who must set
# two-step sign-in up is allowed to reach while the gate holds everything else.
# Every change asks for a code first, limited per account
# (`throttle.TWO_STEP_RECHECK`), so an unattended open session cannot quietly
# turn it off or read out fresh recovery codes.


class CodeBody(BaseModel):
    code: str = Field(min_length=1, max_length=40)


def _recheck(user: UserAccount) -> str:
    """Count one code typed by a signed-in person, against their short limit
    and their day's ceiling (`throttle.TWO_STEP_PER_DAY`) together."""
    key = f"user:{user.id}"
    wait = throttle.acquire_all(
        [(throttle.TWO_STEP_PER_DAY, key), (throttle.TWO_STEP_RECHECK, key)]
    )
    if wait:
        raise _paused(wait)
    return key


def _recheck_not_judged(key: str) -> None:
    """The code was never judged (no key to read it with, nothing to check it
    against): take the attempt back from both limits."""
    throttle.TWO_STEP_RECHECK.release(key)
    throttle.TWO_STEP_PER_DAY.release(key)


def _recheck_passed(key: str) -> None:
    """A right code: the day counts wrong ones only, the short limit restarts."""
    throttle.TWO_STEP_PER_DAY.release(key)
    throttle.TWO_STEP_RECHECK.clear(key)


def _key_unavailable(db: Session, exc: Exception) -> HTTPException:
    db.rollback()
    return HTTPException(503, str(exc))


def _two_step_body(db: Session, user: UserAccount) -> dict:
    when = two_step.enabled_at(db, user.id)
    return {
        **two_step.status(db, user),
        "enabled_at": when.isoformat() if when else None,
        "recovery_codes_left": two_step.recovery_codes_left(db, user.id),
    }


def _audit_self(
    db: Session, request: Request, action: str, user: UserAccount, after: dict | None = None
) -> None:
    record_audit(
        db,
        action=action,
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after=after,
        ip_address=_client_ip(request),
    )


@router.get("/two-step")
def my_two_step(
    user: UserAccount = Depends(signed_in), db: Session = Depends(get_session)
) -> dict:
    return _two_step_body(db, user)


class PasswordBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


#: Refused to an account that is only a model's: models are never asked for
#: a second step and cannot turn one on (ADR 0067, decision 5).
STAFF_ONLY = "Two-step sign-in is for staff accounts."
#: Refused when somebody whose access needs email codes tries to turn them off.
EMAIL_REQUIRED_CANNOT_TURN_OFF = (
    "Your access needs a code by email on a new browser, so it cannot be turned off."
)


def _staff_only(db: Session, user: UserAccount) -> None:
    if not is_staff(roles_of(db, user)):
        raise HTTPException(403, STAFF_ONLY)


def _password_again(db: Session, user: UserAccount, password: str) -> None:
    """The password re-check, as before a payout destination changes."""
    recheck = f"user:{user.id}"
    wait = throttle.PASSWORD_RECHECK.acquire(recheck)
    if wait:
        raise _paused(wait)
    if authenticate(db, user.email, password, record_login=False) is None:
        raise HTTPException(400, PASSWORD_NOT_RIGHT)
    throttle.PASSWORD_RECHECK.clear(recheck)


@router.post("/two-step/start")
def start_two_step(
    body: PasswordBody,
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """A new secret, as a QR code and as text. Nothing is on until a code
    from it is confirmed; starting again replaces it.

    **Asks for the password again first**, as changing where a model is paid
    does. Whoever finds a session left open must not be able to put their own
    phone on somebody's account - and once it is on, a person whose access
    needs it cannot take it off again.
    """
    _staff_only(db, user)
    _password_again(db, user, body.password)

    try:
        shown = two_step.begin_setup(db, user)
    except two_step.AlreadyOn as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from None
    except two_step.KeyUnavailable as exc:
        raise _key_unavailable(db, exc) from None
    db.commit()
    return shown


@router.post("/two-step/confirm")
def confirm_two_step(
    body: CodeBody,
    request: Request,
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """Turn it on with one code, and hand out the ten recovery codes - the
    only time they are ever readable."""
    key = _recheck(user)
    try:
        codes = two_step.confirm_setup(db, user, body.code)
    except (two_step.AlreadyOn, two_step.NotStarted) as exc:
        db.rollback()
        _recheck_not_judged(key)
        raise HTTPException(409, str(exc)) from None
    except two_step.KeyUnavailable as exc:
        _recheck_not_judged(key)
        raise _key_unavailable(db, exc) from None
    if codes is None:
        db.rollback()
        raise HTTPException(400, CODE_DID_NOT_WORK_CHECK_TIME)
    _recheck_passed(key)
    _audit_self(db, request, "auth.two_step.enabled", user)
    db.commit()
    return {"recovery_codes": codes}


def _require_on(db: Session, user: UserAccount) -> None:
    if not two_step.is_enabled(db, user.id):
        raise HTTPException(409, "Two-step sign-in is not on.")


def _check_own_code(db: Session, user: UserAccount, code: str) -> str:
    """An authenticator or recovery code of the signed-in person's own, or
    refuse. Returns which it was."""
    key = _recheck(user)
    try:
        used = two_step.check_code(db, user.id, code)
    except two_step.KeyUnavailable as exc:
        _recheck_not_judged(key)
        raise _key_unavailable(db, exc) from None
    if used is None:
        db.rollback()
        raise HTTPException(400, CODE_DID_NOT_WORK_CHECK_TIME)
    _recheck_passed(key)
    return used


@router.post("/two-step/recovery-codes")
def renew_recovery_codes(
    body: CodeBody,
    request: Request,
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """Ten new recovery codes. Every earlier one, used or not, stops working."""
    _require_on(db, user)
    used = _check_own_code(db, user, body.code)
    codes = two_step.new_recovery_codes(db, user.id)
    _audit_self(db, request, "auth.two_step.recovery_renewed", user, {"with": used})
    db.commit()
    return {"recovery_codes": codes}


@router.post("/two-step/turn-off")
def turn_off_two_step(
    body: CodeBody,
    request: Request,
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """Turn the app off, with a code. **Refused to the owner**, whose access
    needs it whether or not the switch is on yet. Somebody whose access needs
    a code by email may turn the app off: a new browser then emails them a
    code instead. Every remembered browser is forgotten."""
    if two_step.required_method(roles_of(db, user)) == two_step.METHOD_AUTHENTICATOR:
        raise HTTPException(403, REQUIRED_CANNOT_TURN_OFF)
    if not two_step.is_enabled(db, user.id):
        # Nothing on to turn off. A setup never confirmed is dropped.
        two_step.turn_off(db, user.id)
        db.commit()
        return {"enabled": False}
    used = _check_own_code(db, user, body.code)
    two_step.turn_off(db, user.id)
    _audit_self(db, request, "auth.two_step.turned_off", user, {"with": used})
    forget_browsers(db, user, actor=user, why="turned_off", ip_address=_client_ip(request))
    db.commit()
    return {"enabled": False}


class EmailCodesBody(BaseModel):
    on: bool
    password: str = Field(min_length=1, max_length=256)


@router.post("/two-step/email")
def email_codes(
    body: EmailCodesBody,
    request: Request,
    user: UserAccount = Depends(signed_in),
    db: Session = Depends(get_session),
) -> dict:
    """Turn codes by email on or off for yourself, with your password.

    Staff only. Turning them off is refused to whoever's access needs them;
    turning them off forgets every remembered browser, as turning the app off
    does. Answers what `GET /two-step` answers.
    """
    _staff_only(db, user)
    _password_again(db, user, body.password)
    if body.on:
        if user.two_step_email_at is None:
            user.two_step_email_at = utcnow()
            _audit_self(db, request, "auth.two_step.email_on", user)
    else:
        if two_step.required_method(roles_of(db, user)) == two_step.METHOD_EMAIL:
            raise HTTPException(403, EMAIL_REQUIRED_CANNOT_TURN_OFF)
        if user.two_step_email_at is not None:
            user.two_step_email_at = None
            _audit_self(db, request, "auth.two_step.email_off", user)
            forget_browsers(
                db, user, actor=user, why="turned_off", ip_address=_client_ip(request)
            )
    db.commit()
    return _two_step_body(db, user)


# ── Signed in on (ADR 0067, decision 6) ──────────────────────────────────────


def _current_session_id(db: Session, request: Request) -> int | None:
    row = session_for_token(db, request.cookies.get(SESSION_COOKIE, ""))
    return row.id if row is not None else None


@router.get("/sessions")
def my_sessions(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    return {
        "sessions": session_rows(
            live_sessions(db, user.id), _current_session_id(db, request)
        )
    }


@router.post("/sessions/end-others")
def end_my_other_sessions(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """*Sign out everywhere else*: every live session but this one, and every
    remembered browser but this one."""
    ended = revoke_other_sessions(db, user.id, _current_session_id(db, request))
    if ended:
        _audit_self(
            db, request, "auth.sessions.ended", user, {"ended": ended, "kept_current": True}
        )
    forget_browsers(
        db,
        user,
        actor=user,
        why="signed_out_elsewhere",
        ip_address=_client_ip(request),
        keep_id=_this_browser(db, request, user.id),
    )
    db.commit()
    return {"ended": ended}


@router.post("/sessions/{session_id}/end")
def end_my_session(
    session_id: int,
    request: Request,
    response: Response,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """End one of **your own** sessions. Anybody else's, or one already over,
    is 404 - the same answer, so this says nothing about other people's."""
    if not revoke_session_by_id(db, user.id, session_id):
        raise HTTPException(404, "No such session")
    _audit_self(
        db, request, "auth.sessions.ended", user, {"ended": 1, "session_id": session_id}
    )
    db.commit()
    if session_id == _current_session_id(db, request):
        # The one in use: this browser is signed out, so its cookies go too.
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ended": True}


# ── Remembered browsers (ADR 0067, decision 5 as amended) ────────────────────


@router.get("/trusted-browsers")
def my_trusted_browsers(
    request: Request,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    return {
        "browsers": trusted_browsers.rows(
            trusted_browsers.live_rows(db, user.id), _this_browser(db, request, user.id)
        )
    }


@router.post("/trusted-browsers/forget-all")
def forget_my_trusted_browsers(
    request: Request,
    response: Response,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """*Forget every browser*, this one included: the next sign-in anywhere
    asks for a code."""
    forgotten = forget_browsers(
        db, user, actor=user, why="by_hand", ip_address=_client_ip(request)
    )
    db.commit()
    _drop_trusted_cookie(response)
    return {"forgotten": forgotten}


@router.post("/trusted-browsers/{browser_id}/forget")
def forget_my_trusted_browser(
    browser_id: int,
    request: Request,
    response: Response,
    user: UserAccount = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Forget one of **your own** remembered browsers. Anybody else's, or one
    already forgotten or expired, is 404."""
    current = _this_browser(db, request, user.id)
    if not trusted_browsers.forget_one(db, user.id, browser_id):
        raise HTTPException(404, "No such browser")
    record_audit(
        db,
        action="auth.trusted_browser.forgotten",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        after={"forgotten": 1, "why": "by_hand", "browser_id": browser_id},
        ip_address=_client_ip(request),
    )
    db.commit()
    if browser_id == current:
        _drop_trusted_cookie(response)
    return {"forgotten": True}
