"""What the platform tells people, and when.

§16's table. Nine phases built something correct and silent: it knows when a
month closes, when money moves, and when a payout destination is repointed at
somebody else's account, and it tells nobody. This is where that changes.

## Queued in the caller's transaction, always

`queue()` adds a row to the session it was handed and **does not commit**. The
email and the thing it announces succeed together or fail together - see
`app/models/notifications.py` for why both of the alternatives are worse.

The job that sends it is enqueued in that same transaction, so a committed
change always has both the record of what is owed and the work to deliver it.

## Every model gets email only

§16 is explicit: there is no in-platform inbox for an affiliate. That channel
belongs to the maintainer, and "notifications" is the kind of word that grows a
bell icon in the corner of every screen if nobody says so out loud.

## Nothing sensitive travels

No account number, no InstaPay address, no password, no order detail. The
standing rule for audit records and log lines applies here harder, because mail
is the one channel that leaves the building and keeps a copy on a server nobody
here controls.

**An email says a figure and links to the screen.** Phase 9 built those
screens; restating a breakdown in an email is a second place for the numbers to
disagree, and the model will be reading both.
"""

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.businesstime import utcnow
from app.core.money import format_egp
from app.models.notifications import NotificationOutbox, NotificationState
from app.services.jobs import BACKOFF_BASE_SECONDS, PermanentFailure, enqueue
from app.services.mail import MailRefused, Message, send
from app.worker import register_handler

logger = logging.getLogger(__name__)

JOB_KIND = "notification.send"

#: Five attempts, the same shape as the job queue's own retry budget. Long
#: enough to ride out a mail server restart, short enough that a genuine
#: failure is visible while somebody can still act on it.
MAX_ATTEMPTS = 5

#: Long enough to say what happened, short enough that a provider returning a
#: wall of text cannot make recording the failure fail.
MAX_ERROR = 500


class Event:
    """§16's table, as identifiers."""

    INVITATION_SENT = "invitation.sent"
    APPLICATION_SUBMITTED = "application.submitted"
    APPLICATION_RECEIVED = "application.received"
    APPLICATION_APPROVED = "application.approved"
    MONTH_APPROVED = "month.approved"
    PAYMENT_RECORDED = "payment.recorded"
    DESTINATION_CHANGED = "destination.changed"

    #: Not in §16's table. Added with the maintainer's own
    #: payout-destination screen, because that screen is the first way one
    #: person can move another person's money - and until it existed, the
    #: only mail a change produced went to the maintainer, who might be the
    #: one who made it.
    DESTINATION_CHANGED_FOR_THEM = "destination.changed_for_them"


def queue(
    db: Session,
    *,
    event: str,
    recipient_email: str | None,
    recipient_name: str | None = None,
    subject_ref: str | None = None,
    payload: dict | None = None,
) -> NotificationOutbox | None:
    """Owe somebody an email. **Does not commit.**

    Returns `None` when there is nobody to send to. An affiliate with no email
    on file is an ordinary state - they were entered by hand from a WhatsApp
    conversation - and not something that should stop a month being approved.
    """
    address = str(recipient_email or "").strip()
    if not address:
        return None

    row = NotificationOutbox(
        event=event,
        recipient_email=address,
        recipient_name=(recipient_name or "").strip() or None,
        subject_ref=subject_ref,
        payload=payload or {},
        state=NotificationState.PENDING,
    )
    db.add(row)
    # Needed before the job can name it, and safe: this is the caller's
    # transaction, so a rollback takes the row and the job together.
    db.flush()

    enqueue(db, JOB_KIND, {"outbox_id": row.id})
    return row


# -- The events, from where they happen ---------------------------------------
#
# One function per row of §16's table. Call sites stay a single line, and the
# decision about who is told what lives here rather than being spread across
# five services that would drift.


def _email_for(db: Session, affiliate) -> tuple[str | None, str]:
    """An affiliate's address and name.

    On `user_account`, not on the profile: §6.1 roots identity in the account,
    and email is their login. A profile with no account is possible in principle
    and means there is nobody to write to.
    """
    from app.models.identity import UserAccount

    if affiliate.user_account_id is None:
        return None, affiliate.name
    account = db.get(UserAccount, affiliate.user_account_id)
    return (account.email if account else None), affiliate.name


def invitation_sent(
    db: Session, email: str, token: str, role: str
) -> NotificationOutbox | None:
    """Email somebody their invitation link. §13.

    The flow the business asked for: type an address, press send, and the link
    arrives - rather than copying twenty links into twenty emails by hand on the
    night before go-live.

    **The token is a credential**, which is why `invitations.py` stores only its
    hash. Carrying the raw value here would undo that property for as long as
    the outbox row survives, so it goes in `_secret` and is **erased the moment
    the email leaves** - see `_forget_secrets`. The row keeps its record of what
    was sent; it stops being a way in.
    """
    # **Returned, not discarded.** The caller reports to the screen whether the
    # link was emailed, and an earlier version returned nothing at all - so
    # every invitation said "email is not switched on" and told the maintainer
    # to send the link by hand, while the platform quietly emailed it anyway.
    return queue(
        db,
        event=Event.INVITATION_SENT,
        recipient_email=email,
        subject_ref=f"invitation:{email}",
        payload={"email": email, "role": role, "_secret": {"token": token}},
    )


def application_submitted(db: Session, affiliate) -> None:
    """Two emails: they know it arrived, and somebody knows to look."""
    email, name = _email_for(db, affiliate)
    queue(
        db,
        event=Event.APPLICATION_SUBMITTED,
        recipient_email=email,
        recipient_name=name,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={"email": email, "name": name},
    )
    queue(
        db,
        event=Event.APPLICATION_RECEIVED,
        recipient_email=settings.maintainer_email,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={"email": settings.maintainer_email, "name": name},
    )


def application_approved(db: Session, affiliate) -> None:
    """The one that carries the sign-in link.

    The first thing most models will ever see from the platform, and the email
    the whole go-live depends on arriving.
    """
    email, name = _email_for(db, affiliate)
    queue(
        db,
        event=Event.APPLICATION_APPROVED,
        recipient_email=email,
        recipient_name=name,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={"email": email, "name": name},
    )


def month_approved(db: Session, affiliate, snapshot, month: str) -> None:
    """§11.1's moment: a calculation became an obligation.

    Carries the reopen case too (ADR 0030). A reopen sends nothing of its own -
    reopening and re-approving happen back to back, and a heads-up at reopen
    only trains a model to skip it and eventually the real one. So this is the
    email, with two additions when `version > 1`.

    **The overpayment case is stated outright.** If the new figure is below
    what they were already paid there is no transfer to attach the news to and
    nothing will change in their bank account, so they would otherwise find out
    when next month's payment is smaller than they expected.

    What it does *not* do is name the §11.5 resolution. The spec expects one,
    and at this moment nobody has chosen: credit or write-off is a judgement
    about a person, made when the adjustment is recorded, which is a separate
    act minutes or days later. Announcing a decision that has not been taken
    would be worse than saying plainly that it is coming.
    """
    from app.core.money import format_egp as _egp
    from app.services.payments import balance_for

    email, name = _email_for(db, affiliate)
    payload = {
        "email": email,
        "name": name,
        "month": month,
        "month_name": month_in_words(month),
        "obligation_piastres": snapshot.approved_obligation_piastres,
        "version": snapshot.version,
    }

    if snapshot.version > 1:
        previous = _previous_obligation(db, snapshot)
        if previous is not None:
            payload["previous_obligation_piastres"] = previous
        reason = _reopen_reason(db, affiliate.id, month)
        if reason:
            payload["reason"] = reason

        # Already paid more than the month is now worth. §11.5 reports it and
        # refuses to decide what happens next; the email says the same.
        balance = balance_for(db, affiliate, month)
        overpaid = balance["paid_piastres"] - snapshot.approved_obligation_piastres
        if overpaid > 0:
            payload["resolution"] = (
                f"You have already been paid {_egp(balance['paid_piastres'])} "
                f"for this month, which is {_egp(overpaid)} more than the new "
                "figure. HBA will tell you whether that comes off a later "
                "payment or is written off - there is nothing for you to do."
            )

    queue(
        db,
        event=Event.MONTH_APPROVED,
        recipient_email=email,
        recipient_name=name,
        subject_ref=f"affiliate:{affiliate.id}",
        payload=payload,
    )


def payment_recorded(db: Session, affiliate, transaction) -> None:
    """§14. Money moved, with the receipt on their payments screen."""
    email, name = _email_for(db, affiliate)
    queue(
        db,
        event=Event.PAYMENT_RECORDED,
        recipient_email=email,
        recipient_name=name,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={
            "email": email,
            "name": name,
            "amount_piastres": transaction.amount_piastres,
            "has_proof": transaction.proof_file_id is not None,
        },
    )


def destination_changed(db: Session, affiliate, masked: dict | None) -> None:
    """§6.4.5. The one email here that is a security control.

    A compromised account that can silently repoint an InstaPay address can
    redirect an entire payout. This is what makes it not silent - and it goes
    to the maintainer, because the person who did it already knows.

    **Masked**, like every other representation of a destination outside its
    owner's own screen. The point is that somebody notices a change happened,
    not that an account number ends up sitting in an inbox.
    """
    _, name = _email_for(db, affiliate)
    shown = ""
    if masked:
        shown = str(
            masked.get("instapay_address_url")
            or masked.get("bank_account_number")
            or masked.get("wallet_phone")
            or ""
        )
    queue(
        db,
        event=Event.DESTINATION_CHANGED,
        recipient_email=settings.maintainer_email,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={
            "email": settings.maintainer_email,
            "name": name,
            "masked": shown or None,
        },
    )


def destination_changed_for_them(db: Session, affiliate, masked: dict | None):
    """Tell the model that somebody else moved where their money goes.

    **The one email the owner of the money has to get.** A maintainer
    correcting a destination is a real and necessary act - a model who cannot
    reach their own screen still has to be paid - and it is indistinguishable,
    from the outside, from somebody quietly redirecting a payout. What
    separates them is whether the person whose money it is finds out.

    Masked, like everywhere else (§6.4.4). The point is that they notice a
    change happened, not that an account number ends up in an inbox.
    """
    email, name = _email_for(db, affiliate)
    if not email:
        return None

    shown = ""
    if masked:
        shown = str(
            masked.get("instapay_address_url")
            or masked.get("bank_account_number")
            or masked.get("wallet_phone")
            or ""
        )
    return queue(
        db,
        event=Event.DESTINATION_CHANGED_FOR_THEM,
        recipient_email=email,
        recipient_name=name,
        subject_ref=f"affiliate:{affiliate.id}",
        payload={"email": email, "name": name, "masked": shown or None},
    )


def month_in_words(month: str) -> str:
    """`2026-08` -> `August 2026`. The frontend has this; email has no frontend."""
    names = (
        "January February March April May June July August September October "
        "November December"
    ).split()
    year, _, index = month.partition("-")
    try:
        return f"{names[int(index) - 1]} {year}"
    except (ValueError, IndexError):
        return month


def _previous_obligation(db: Session, snapshot) -> int | None:
    """What the month was agreed at before it was reopened."""
    from app.models.payroll import PayrollSnapshot

    return db.scalar(
        select(PayrollSnapshot.approved_obligation_piastres)
        .where(PayrollSnapshot.payroll_month_id == snapshot.payroll_month_id)
        .where(PayrollSnapshot.version < snapshot.version)
        .order_by(PayrollSnapshot.version.desc())
        .limit(1)
    )


def _reopen_reason(db: Session, affiliate_id: int, month: str) -> str | None:
    """The written reason from the most recent reopen of this month.

    Read from the audit trail because that is where §11.5 requires it to be
    written, and a second copy on the payroll month would be a second thing
    that can disagree with it.
    """
    from app.models.audit import AuditEvent

    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.action == "payroll.reopened")
        .where(AuditEvent.subject == f"affiliate:{affiliate_id}")
        .order_by(AuditEvent.id.desc())
        .limit(5)
    )
    for row in rows:
        before = row.before_json or {}
        if before.get("month") == month:
            return row.reason
    return None


# -- What each one says -------------------------------------------------------


def _link(path: str) -> str:
    """A link into the platform, or nothing at all.

    An unset base URL produces **no link rather than a broken one**. A sign-in
    link pointing at localhost is worse than no email: it teaches twenty people
    that mail from HBA does not work, and that lesson is expensive to unteach.
    """
    base = settings.public_base_url.strip().rstrip("/")
    return f"{base}{path}" if base else ""


def _sign_off() -> str:
    return "\n\nHBA Aesthetics"


def _with_link(body: str, path: str, invitation: str) -> str:
    link = _link(path)
    if not link:
        return body + _sign_off()
    return f"{body}\n\n{invitation}\n{link}" + _sign_off()


def render(event: str, payload: dict) -> Message | None:
    """One notification, as the words that will arrive.

    Returns `None` for an event with no template, which is a programming error
    rather than a runtime one - the caller fails the job permanently and says
    so, instead of sending an empty message.
    """
    name = str(payload.get("name") or "").strip()
    first = name.split(" ")[0] if name else "there"

    if event == Event.INVITATION_SENT:
        # §13: invited, accepted, and inside the tool in one step. The link is
        # the whole email - anything else in it competes with the one thing they
        # are meant to do.
        token = (payload.get("_secret") or {}).get("token", "")
        link = _link(f"/accept-invitation?token={token}") if token else ""
        body = (
            "Hi,\n\n"
            "HBA Aesthetics has set up an account for you on the affiliate "
            "platform. It is where you will see what you have earned, the "
            "orders behind it, and everything you have been paid."
        )
        if link:
            body += (
                "\n\nOpen this link to choose a password and get started. It "
                "works once, and it expires in three days:\n" + link
            )
        return Message(
            to_address=payload["email"],
            to_name=None,
            subject="Your HBA affiliate account",
            body=body + _sign_off(),
        )

    if event == Event.APPLICATION_SUBMITTED:
        return Message(
            to_address=payload["email"],
            to_name=name or None,
            subject="We have your application",
            body=(
                f"Hi {first},\n\n"
                "Thank you - we have your application. Someone at HBA is "
                "checking your discount code against the shop, and you will "
                "hear from us once that is done. There is nothing else for you "
                "to do right now."
            )
            + _sign_off(),
        )

    if event == Event.APPLICATION_RECEIVED:
        return Message(
            to_address=payload["email"],
            to_name=None,
            subject=f"New application: {name}",
            body=_with_link(
                f"{name} has applied to the programme"
                + (f" with the code {payload['code']}." if payload.get("code") else ".")
                + "\n\nThe code needs checking against Shopify before "
                "the application can be approved.",
                "/affiliates",
                "Review it here:",
            ),
        )

    if event == Event.APPLICATION_APPROVED:
        # The one that carries the sign-in link, and the first thing most
        # models will ever see from the platform.
        return Message(
            to_address=payload["email"],
            to_name=name or None,
            subject="You are on the HBA programme",
            body=_with_link(
                f"Hi {first},\n\n"
                "You are on the programme - your code is live and your sales "
                "are being counted from now on.\n\n"
                "You can see what you have earned, the orders behind it, and "
                "everything you have been paid, whenever you like.",
                "/",
                "Sign in here:",
            ),
        )

    if event == Event.MONTH_APPROVED:
        # §11.1. The moment a figure stops being a calculation and becomes an
        # obligation - which is exactly the moment worth an email.
        agreed = format_egp(int(payload.get("obligation_piastres") or 0))
        month = str(payload.get("month_name") or payload.get("month") or "")
        reopened = int(payload.get("version") or 1) > 1

        opening = (
            f"Hi {first},\n\n{month} is closed and agreed at {agreed}."
            if not reopened
            else f"Hi {first},\n\n{month} has been looked at again and is now "
            f"agreed at {agreed}."
        )

        detail = ""
        if reopened:
            # ADR 0030: no email at reopen, and the re-approval carries the
            # difference and the reason, in plain language rather than copied
            # from the audit log.
            if payload.get("previous_obligation_piastres") is not None:
                was = format_egp(int(payload["previous_obligation_piastres"]))
                detail += f"\n\nIt was {was} before."
            if payload.get("reason"):
                detail += f"\n\nWhy it changed: {payload['reason']}"
            if payload.get("resolution"):
                # The figure fell below what was already paid. There is no
                # transfer to attach this to and nothing will change in their
                # bank account, so it has to be said outright.
                detail += f"\n\n{payload['resolution']}"

        return Message(
            to_address=payload["email"],
            to_name=name or None,
            subject=f"{month} is agreed",
            body=_with_link(
                opening + detail,
                "/",
                "The orders behind it are here:",
            ),
        )

    if event == Event.PAYMENT_RECORDED:
        amount = format_egp(int(payload.get("amount_piastres") or 0))
        proof = (
            "\n\nThe transfer confirmation is on your payments page."
            if payload.get("has_proof")
            else ""
        )
        return Message(
            to_address=payload["email"],
            to_name=name or None,
            subject=f"{amount} sent",
            body=_with_link(
                f"Hi {first},\n\n{amount} has been sent to you." + proof,
                "/payments",
                "Your payments are here:",
            ),
        )

    if event == Event.DESTINATION_CHANGED:
        # §6.4.5, and the one email here that is a security control rather than
        # a courtesy. A compromised account that can silently repoint an
        # InstaPay address can redirect an entire payout; this is what makes it
        # not silent.
        #
        # **Masked, like everywhere else.** The point is that somebody notices
        # a change happened, not that they can read the new account number out
        # of an inbox.
        return Message(
            to_address=payload["email"],
            to_name=None,
            subject=f"{name} changed where the money goes",
            body=_with_link(
                f"{name} has changed where payments go.\n\n"
                f"It now ends {payload.get('masked') or 'unknown'}.\n\n"
                "If that was not expected, check with them before the next "
                "payment run.",
                "/payments",
                "The payments screen flags it too:",
            ),
        )

    if event == Event.DESTINATION_CHANGED_FOR_THEM:
        # Addressed to the model. Says who to argue with, because the whole
        # value of this mail is that they can.
        return Message(
            to_address=payload["email"],
            to_name=payload.get("name"),
            subject="Where your HBA payments go has changed",
            body=_with_link(
                f"Hi {first},\n\n"
                "Somebody at HBA has changed where your payments are sent.\n\n"
                f"They now go to the account ending {payload.get('masked') or 'unknown'}.\n\n"
                "If you asked for this, nothing more is needed. **If you did "
                "not, reply to this email before the next payment run** - it "
                "has not been paid yet.",
                "/me/details",
                "You can see and change it yourself here:",
            ),
        )

    return None


# -- Sending ------------------------------------------------------------------


def _forget_secrets(row: NotificationOutbox) -> None:
    """Drop anything in the payload that was only needed to send it once.

    An invitation token is a credential until it is used, and
    `invitations.py` keeps only its hash for exactly that reason. The outbox
    has to hold the raw value long enough to put it in an email and **not one
    moment longer** - a queue table that quietly accumulates working sign-in
    links is a second copy of the thing the hashing was protecting.

    Called on every terminal state, including failure: an email that was never
    delivered still leaves a live token sitting in a row somebody can read.
    """
    if not isinstance(row.payload, dict) or "_secret" not in row.payload:
        return
    # Reassigned rather than mutated: SQLAlchemy does not track in-place edits
    # to a JSONB dict, so mutating it would leave the token on disk.
    row.payload = {k: v for k, v in row.payload.items() if k != "_secret"}


@register_handler(JOB_KIND)
def send_notification(db: Session, payload: dict) -> None:
    """Send one queued email.

    **Idempotent**, as every handler must be: a lease can expire and hand the
    same job to a second worker, and a row that is no longer pending is left
    exactly as it is rather than sent twice. A duplicate payroll email is a
    model asking whether they are being paid twice.

    ## Delivery failures are recorded, not raised

    The worker rolls a handler's transaction back when it raises, which is
    correct and is exactly why this cannot raise on a failed send: the
    `attempts` count and the error would be rolled back with it, the row would
    sit at `pending` forever, and the retry budget would live on the job while
    the operational view read the outbox. An email nobody will ever receive
    would be invisible from the one table that exists to track it.

    So a delivery failure is written to the row and the retry is re-queued by
    hand, with the same doubling backoff the job queue uses. The handler
    returns normally and the worker commits both.

    **A programming error still raises.** A missing template is not a delivery
    problem, retrying cannot fix it, and it belongs in the failed-jobs view
    where somebody looks for broken deploys. The split is deliberate:
    *delivery* failures go to the outbox, *code* failures go to the queue.
    """
    outbox_id = payload.get("outbox_id")
    if outbox_id is None:
        raise PermanentFailure("The job names no notification")

    row = db.get(NotificationOutbox, outbox_id)
    if row is None:
        raise PermanentFailure(f"Notification {outbox_id} no longer exists")

    if row.state != NotificationState.PENDING:
        return

    message = render(row.event, dict(row.payload or {}))
    if message is None:
        # A code failure, not a delivery one. Loud, and in the failed-jobs view.
        raise PermanentFailure(f"No template for {row.event!r}")

    row.attempts += 1

    try:
        delivered = send(message)
    except MailRefused as exc:
        # A bad address or a refused sender will be refused next minute too.
        # Retrying four more times only delays somebody noticing.
        row.state = NotificationState.FAILED
        row.last_error = str(exc)[:MAX_ERROR]
        logger.warning(
            "notification %s (%s) refused: %s", row.id, row.event, row.last_error
        )
        _forget_secrets(row)
        return
    except Exception as exc:  # noqa: BLE001 - recorded on the row, see above
        row.last_error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR]
        if row.attempts >= MAX_ATTEMPTS:
            row.state = NotificationState.FAILED
            logger.warning(
                "notification %s (%s) gave up after %s attempts: %s",
                row.id,
                row.event,
                row.attempts,
                row.last_error,
            )
            # Even undelivered. An email that never went out still leaves a
            # live invitation token sitting in a row somebody can read.
            _forget_secrets(row)
            return

        # Doubling, like the job queue: 30s, 60s, 120s, 240s. Retrying a
        # struggling mail server at a fixed interval is how a blip becomes an
        # outage.
        enqueue(
            db,
            JOB_KIND,
            {"outbox_id": row.id},
            run_after=utcnow()
            + timedelta(seconds=BACKOFF_BASE_SECONDS * (2 ** (row.attempts - 1))),
        )
        logger.info(
            "notification %s (%s) attempt %s failed, retrying: %s",
            row.id,
            row.event,
            row.attempts,
            row.last_error,
        )
        return

    if not delivered:
        # No credentials configured. Not a failure - a development machine and
        # the test suite are both in this state permanently, and marking it
        # `skipped` keeps "nobody set this up" distinguishable from "we tried
        # and could not".
        row.state = NotificationState.SKIPPED
        logger.info(
            "notification %s (%s) skipped: no mail credentials", row.id, row.event
        )
        _forget_secrets(row)
        return

    row.state = NotificationState.SENT
    row.sent_at = utcnow()
    _forget_secrets(row)


def pending_count(db: Session) -> int:
    """How many emails are owed and not yet sent."""
    return len(
        list(
            db.scalars(
                select(NotificationOutbox.id).where(
                    NotificationOutbox.state == NotificationState.PENDING
                )
            )
        )
    )


def failed(db: Session, limit: int = 50) -> list[NotificationOutbox]:
    """Emails that will not be delivered, newest first.

    For the operational view. A model who was never told what they are owed is
    invisible from every other screen in the platform.
    """
    return list(
        db.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.state == NotificationState.FAILED)
            .order_by(NotificationOutbox.id.desc())
            .limit(limit)
        )
    )
