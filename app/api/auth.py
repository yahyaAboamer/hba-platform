"""Authentication endpoints."""

import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    actor_payload,
    client_address,
    current_user,
    permission_list,
    require_permission,
    roles_of,
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
    sorted_roles,
)
from app.core import throttle
from app.db import get_session
from app.models.identity import Invitation, RoleAssignment, UserAccount
from app.services.audit import record_audit
from app.services.auth import (
    authenticate,
    ensure_csrf,
    issue_session,
    resolve_session,
    revoke_all_sessions,
    revoke_session,
)
from app.services.invitations import (
    accept_invitation,
    create_invitation,
    preview_invitation,
)
from app.services.notifications import (
    invitation_link,
    invitation_sent,
    password_reset_requested,
)
from app.services.password_resets import (
    complete_reset,
    preview_reset,
    request_reset,
)
from app.services.payroll import go_live_month, working_month

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

    user = authenticate(db, str(body.email), body.password)
    if user is None:
        # One message for both causes. Distinguishing them would confirm which
        # email addresses have accounts.
        raise HTTPException(401, "Incorrect email or password")
    # It worked, so it was never a failed attempt.
    throttle.LOGIN_PER_ACCOUNT.clear(email)
    if source is not None:
        throttle.LOGIN_PER_PAIR.clear(f"{email}|{source}")
        throttle.LOGIN_PER_SOURCE.release(source)

    token, csrf, _ = issue_session(
        db, user.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.login",
        subject=f"user:{user.id}",
        actor_id=user.id,
        actor_email=user.email,
        ip_address=_client_ip(request),
    )
    db.commit()
    _set_cookie(response, token, csrf)
    return {"actor": actor_payload(db, user), "csrf": csrf}


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
    user: UserAccount = Depends(current_user),
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
    # They have just proved they own the address, so a pause from somebody
    # else's guessing must not keep them out.
    owner = account.email.strip().lower()
    throttle.LOGIN_PER_ACCOUNT.clear(owner)
    source = _source(request)
    if source is not None:
        throttle.LOGIN_PER_PAIR.clear(f"{owner}|{source}")
    throttle.PASSWORD_RECHECK.clear(f"user:{account.id}")
    token, csrf, _ = issue_session(
        db, account.id, _client_ip(request), request.headers.get("user-agent")
    )
    record_audit(
        db,
        action="auth.password_reset",
        subject=f"user:{account.id}",
        actor_id=account.id,
        actor_email=account.email,
        after={"sessions_ended": ended},
        ip_address=_client_ip(request),
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
