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

import httpx

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

    #: The words, as plain text. **This is the source.** Every template writes
    #: this and every test asserts on it; the HTML below is derived from it, so
    #: the two can never say different things.
    body: str

    #: The same words wrapped in the brand, or `None` to send text only.
    #: Providers are given both: a client that cannot or will not render HTML
    #: falls back to the text, which is the version that was written.
    html: str | None = None


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


# -- Sending over HTTPS ------------------------------------------------------
#
# **Railway blocks outbound SMTP.** Every notification the platform queued
# failed with `OSError: [Errno 101] Network is unreachable` on the connect to
# `smtp.gmail.com:587` - not a credential problem, not a Gmail problem, and
# nothing that could be fixed by changing the password. Most hosts block ports
# 25, 465 and 587 to stop their address space being used for spam, and Railway
# is one of them.
#
# So mail goes out over port 443 instead, through a provider's HTTP API. The
# rest of the platform is unchanged: `send` still takes a `Message` and still
# raises `MailRefused` for a failure that will not fix itself.
#
# Two providers, because the right one depends on something outside this code:
#
# - **Resend** needs a domain you control. Best deliverability by a distance,
#   because the mail is genuinely signed by that domain.
# - **Brevo** will verify a single address, a Gmail one included. Worse
#   deliverability - a third party sending as `@gmail.com` cannot align DMARC,
#   because only Google can publish records for `gmail.com` - and the only
#   option when there is no domain to use.
#
# Whichever has an API key set is the one that is used. SMTP stays for local
# development and for any host that permits it.


class MailProvider:
    SMTP = "smtp"
    RESEND = "resend"
    BREVO = "brevo"


def transport() -> str:
    """Which way mail will go, decided by what is configured.

    An HTTP key wins over SMTP. On a host that blocks the ports, SMTP is not a
    fallback - it is a guaranteed failure, and a silent one.
    """
    if settings.resend_api_key.strip():
        return MailProvider.RESEND
    if settings.brevo_api_key.strip():
        return MailProvider.BREVO
    return MailProvider.SMTP


def _from_pair() -> tuple[str, str]:
    return settings.mail_from_name.strip() or "HBA", settings.mail_from_address.strip()


def _send_over_http(message: Message) -> bool:
    """Hand the message to a provider's API.

    A 4xx means the request will not become acceptable by being repeated - a
    rejected sender, a malformed address, a revoked key - so it is permanent. A
    5xx or a network error is not, and is left to the caller's retry.
    """
    provider = transport()
    name, address = _from_pair()

    if provider == MailProvider.RESEND:
        url = "https://api.resend.com/emails"
        headers = {"Authorization": f"Bearer {settings.resend_api_key.strip()}"}
        payload = {
            "from": f"{name} <{address}>",
            "to": [message.to_address],
            "subject": message.subject,
            "text": message.body,
            **({"html": message.html} if message.html else {}),
        }
    else:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {"api-key": settings.brevo_api_key.strip()}
        payload = {
            "sender": {"name": name, "email": address},
            "to": [{"email": message.to_address}],
            "subject": message.subject,
            "textContent": message.body,
            **({"htmlContent": message.html} if message.html else {}),
        }

    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.smtp_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        # Unreachable, timed out, DNS. Worth trying again.
        raise RuntimeError(f"Could not reach {provider}: {exc}") from exc

    if 400 <= response.status_code < 500:
        raise MailRefused(
            f"{provider} refused the message ({response.status_code}): "
            f"{response.text[:300]}"
        )
    if response.status_code >= 500:
        raise RuntimeError(f"{provider} returned {response.status_code}")

    return True


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

    if transport() != MailProvider.SMTP:
        return _send_over_http(message)

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
