"""Handing an email to a mail server.

One function with one job. Everything about *what* to say lives in
`notifications.py`; this only knows how to put it on the wire.

## Plain text, deliberately

No HTML. Three reasons, in order of how much they matter here:

**Deliverability.** These emails carry sign-in links to about twenty people, on
a domain nobody has ever received mail from before. That is the exact profile a
spam filter is trained on, and an HTML message with a styled button is
noticeably more of it than a short plain-text note.

**Nothing to render wrongly.** A mail client is not a browser, every one of
them is a different subset of HTML, and a payroll figure that reflows badly on
somebody's phone is a figure they will ask about.

**It reads as written by a person.** For twenty models who know Sara, that is
the right register - a marketing template is not.

If HTML is ever wanted it is one more function here, and nothing else changes.

## Configured or not

Blank credentials are the normal state of a development machine and of the test
suite, so they are not an error. `send` reports that it did nothing and the
caller records the notification as **skipped** rather than failed - the two look
identical to a recipient and mean completely different things to whoever is
looking into it.

## Refused is not the same as unreachable

A mailbox that does not exist will not exist next minute either. Retrying it
four more times only delays somebody noticing the address is wrong, so those
raise `MailRefused` and the caller gives up at once. A timeout or a dropped
connection raises normally and is retried.
"""

import smtplib
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage

from app.config import settings


#: A display name is data somebody else typed. These are the characters
#: that would turn one into a second header.
LINE_BREAKS = (chr(13), chr(10))


class MailRefused(Exception):
    """The server refused this message and will refuse it again.

    A bad address, a rejected sender, a mailbox that is gone. Retrying cannot
    help, so the caller stops rather than repeating the same failure.
    """


@dataclass(frozen=True)
class Message:
    """One email, ready to send."""

    to_address: str
    to_name: str | None
    subject: str
    body: str


def _address(name: str | None, email: str) -> str:
    """A display name and an address, encoded safely.

    Built through `email.headerregistry` rather than by string formatting: a
    name containing a comma or a newline would otherwise become a second
    recipient or an injected header, and a model's name is data somebody else
    typed.

    Line breaks are **stripped rather than refused.** `Address` raises on them,
    which is safe and is the wrong failure here: a name with a stray newline
    would make delivery throw, get retried five times, and end up recorded as a
    mail-server problem. The injection is impossible either way; this just
    keeps the email going out.
    """
    clean = "".join(c for c in (name or "") if c not in LINE_BREAKS).strip()
    local, _, domain = email.strip().rpartition("@")
    return str(Address(display_name=clean, username=local, domain=domain))


def build(message: Message) -> EmailMessage:
    """The message, as it will go over the wire. Separated so a test can read it."""
    mail = EmailMessage()
    mail["Subject"] = message.subject
    mail["From"] = _address(settings.mail_from_name, settings.mail_from_address)
    mail["To"] = _address(message.to_name, message.to_address)
    # Nothing generated here should be replied to by a machine, and an
    # auto-responder answering a payroll notification would queue a second one.
    mail["Auto-Submitted"] = "auto-generated"
    mail.set_content(message.body)
    return mail


def send(message: Message) -> bool:
    """Send it. Returns whether anything was actually sent.

    `False` means the platform has no mail credentials - not a failure. `True`
    means the server accepted it, which is as far as any sender can know.

    Raises `MailRefused` where retrying cannot help, and anything else where it
    can.
    """
    if not settings.mail_configured:
        return False

    if not str(message.to_address or "").strip():
        # An affiliate with no email on file. Permanent by definition: no
        # number of retries will invent an address.
        raise MailRefused("There is no email address to send to")

    try:
        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
        ) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(build(message))
    except (
        smtplib.SMTPRecipientsRefused,
        smtplib.SMTPSenderRefused,
        smtplib.SMTPNotSupportedError,
    ) as exc:
        raise MailRefused(str(exc)) from exc
    except smtplib.SMTPAuthenticationError as exc:
        # Wrong credentials will be wrong next minute too. Loud and permanent,
        # because the alternative is every email in the queue quietly retrying
        # against a password somebody rotated.
        raise MailRefused(f"The mail account was refused: {exc}") from exc

    return True
