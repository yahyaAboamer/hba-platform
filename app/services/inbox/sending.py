"""Who may be messaged, and how a phone number is read (ADR 0059).

Two rules live here so that nothing which sends can skip them:

- **Sending is off until an admin turns it on.** A saved connection
  receives; it sends nothing on its own.
- **Outside production, only the listed test numbers are ever messaged**
  (``INBOX_TEST_NUMBERS``). A staging or development server holding real
  keys still cannot write to a customer.
"""

import re

from sqlalchemy.orm import Session

from app.config import settings
from app.models.inbox import InboxConnection

#: An Egyptian mobile: country code 20, then 10, 11, 12 or 15, then eight
#: digits. Stored and sent without a plus sign, as WhatsApp writes it.
_EGYPTIAN_MOBILE = re.compile(r"20(10|11|12|15)\d{8}")

NOT_CONNECTED = "WhatsApp is not connected."
SENDING_OFF = "Sending is turned off in Settings."
NOT_A_TEST_NUMBER = "This server only messages its test numbers."


def egyptian_mobile(raw: object) -> str | None:
    """``raw`` as ``2010XXXXXXXX``, or None if it is not an Egyptian mobile.

    Orders carry the number however the customer typed it: ``010…``,
    ``+20 10…``, ``0020 10…``, with spaces or dashes. Anything that is not
    one of those is refused rather than guessed at - a message sent to a
    stranger is worse than one not sent.
    """
    digits = re.sub(r"\D", "", str(raw or ""))
    if digits.startswith("0020"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "20" + digits[1:]
    elif len(digits) == 10 and digits.startswith("1"):
        digits = "20" + digits
    return digits if _EGYPTIAN_MOBILE.fullmatch(digits) else None


def allowed_test_numbers() -> frozenset[str]:
    """The numbers a server outside production may message."""
    numbers = (egyptian_mobile(part) for part in settings.inbox_test_numbers.split(","))
    return frozenset(number for number in numbers if number)


def refusal(db: Session, phone: str) -> str | None:
    """Why ``phone`` may not be messaged right now, or None if it may."""
    connection = db.get(InboxConnection, 1)
    if connection is None:
        return NOT_CONNECTED
    if not connection.sending_enabled:
        return SENDING_OFF
    if not settings.is_production and phone not in allowed_test_numbers():
        return NOT_A_TEST_NUMBER
    return None
