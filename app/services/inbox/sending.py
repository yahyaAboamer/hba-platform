"""Who may be messaged, and how a phone number is read (ADR 0059).

Two rules live here so that nothing which sends can skip them:

- **Sending is off until an admin turns it on.** A saved connection
  receives; it sends nothing on its own.
- **A server messages customers only if it has been told it may**
  (``INBOX_SEND_TO_CUSTOMERS``, set on production alone). Every other server
  messages only its listed test numbers (``INBOX_TEST_NUMBERS``), so a
  staging or development server holding real keys still cannot write to a
  customer. The switch is its own variable because staging also runs with
  ``APP_ENV=production``.
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


#: Calling codes for the countries the store ships to, by the code Shopify
#: gives a shipping address. A number written the local way from a country
#: missing here is refused, never guessed at (ADR 0062, point 5).
CALLING_CODES = {
    # The Gulf, the Levant, Iraq and North Africa.
    "SA": "966", "AE": "971", "KW": "965", "QA": "974", "BH": "973", "OM": "968",
    "JO": "962", "LB": "961", "PS": "970", "SY": "963", "IQ": "964", "YE": "967",
    "LY": "218", "TN": "216", "DZ": "213", "MA": "212", "SD": "249", "TR": "90",
    # Europe.
    "GB": "44", "IE": "353", "FR": "33", "DE": "49", "NL": "31", "BE": "32",
    "LU": "352", "CH": "41", "AT": "43", "IT": "39", "ES": "34", "PT": "351",
    "SE": "46", "NO": "47", "DK": "45", "FI": "358", "PL": "48", "CZ": "420",
    "GR": "30", "CY": "357", "RO": "40", "HU": "36",
    # North America and elsewhere.
    "US": "1", "CA": "1", "AU": "61", "NZ": "64", "MY": "60", "SG": "65",
    "ZA": "27", "NG": "234", "KE": "254", "PK": "92", "IN": "91",
}

#: The shortest and longest a full international number can be (ITU E.164).
_INTERNATIONAL = re.compile(r"[1-9]\d{7,14}")


def international_mobile(raw: object, country: str | None) -> str | None:
    """``raw`` as a full international number without the plus, or None.

    For a payment request only (ADR 0062, point 5), whose order ships to
    ``country``:

    - written with ``+`` or ``00``, it is taken as written;
    - already starting with the country's code, it is taken as written;
    - otherwise it is local: a leading ``0`` is dropped and the country's
      code put in front - unless it is shaped like an Egyptian mobile
      written the Egyptian way, which could be either and is refused.

    An Egyptian number must still be a valid Egyptian mobile. Anything that
    does not come out as 8 to 15 digits is refused.
    """
    text = str(raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    code = CALLING_CODES.get(str(country or "").upper())
    if text.startswith("+"):
        full = digits
    elif digits.startswith("00"):
        full = digits[2:]
    elif code and digits.startswith(code):
        # ``3931234567`` on an order to Italy is either an Italian mobile
        # written locally or one with its code: ten digits or fewer could be
        # either, so it is refused. Longer, it can only be the code.
        if len(digits) <= 10 or len(digits) - len(code) < 8:
            return None
        full = digits
    elif code and digits.startswith("01") and egyptian_mobile(digits):
        # ``010…`` on an order to Saudi Arabia is an Egyptian mobile written
        # the Egyptian way - or a local number that happens to look like one.
        # Which, the platform cannot tell, so it messages neither.
        return None
    elif code and len(digits.removeprefix("0")) >= 7:
        full = code + digits.removeprefix("0")
    else:
        # No code for the country, or too short to be anybody's number.
        return None
    if full.startswith("20"):
        return egyptian_mobile(full)
    return full if _INTERNATIONAL.fullmatch(full) else None


def allowed_test_numbers() -> frozenset[str]:
    """The numbers a server that may not message customers still may."""
    numbers = (egyptian_mobile(part) for part in settings.inbox_test_numbers.split(","))
    return frozenset(number for number in numbers if number)


def refusal(db: Session, phone: str) -> str | None:
    """Why ``phone`` may not be messaged right now, or None if it may."""
    connection = db.get(InboxConnection, 1)
    if connection is None:
        return NOT_CONNECTED
    if not connection.sending_enabled:
        return SENDING_OFF
    if not settings.inbox_send_to_customers and phone not in allowed_test_numbers():
        return NOT_A_TEST_NUMBER
    return None
