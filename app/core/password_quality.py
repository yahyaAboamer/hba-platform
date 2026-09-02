"""Whether a password is worth accepting, beyond being long enough.

**Length is the rule; this is the floor under it.** Modern guidance
(NIST SP 800-63B) is explicit that mandatory character-composition rules -
one capital, one digit, one symbol - should *not* be imposed, because in
practice they produce `Password1!`: a predictable substitution the owner then
writes down or reuses. Twelve characters already beats that.

What length alone cannot catch is a password that is long *and* famous.
`qwertyuiop123`, `iloveyouforever` and `hbaaesthetics` all clear twelve
characters and would be tried within the first few thousand guesses.

## Why a bundled list rather than an online check

The obvious alternative is Have I Been Pwned's range API, which is genuinely
privacy-preserving - only the first five characters of the hash leave. It was
rejected here for one reason: **it puts a network call in the middle of
setting a password.** If it is required, a provider outage means nobody can
accept an invitation. If it fails open, it is a check that quietly stops
checking, which is worse than not having it - a guard nobody can rely on is
one people stop thinking about.

A bundled list always works, is identical on every machine, and needs no
outbound request from a container that should not need one. It catches less,
and what it catches is what twenty people would actually choose.

The list is deliberately short and specific rather than a scraped top-10,000:
the common shapes, plus the words this particular business makes likely.
"""

import re
import unicodedata

#: Passwords refused outright, and the shapes they are generated from.
#:
#: Compared after normalising, so `P@ssw0rd123!` and `password123` collapse to
#: the same entry - the substitutions people make are the ones attackers try
#: first, and treating them as distinct would defeat the whole list.
_COMMON = frozenset(
    {
        # The perennials, at twelve or more characters.
        "password",
        "passwordpassword",
        "passw0rdpassword",
        "letmeinletmein",
        "qwertyuiop",
        "qwertyuiopasdfgh",
        "qwerty123456",
        "asdfghjkl",
        "zxcvbnmasdfgh",
        "1234567890",
        "123456789012",
        "111111111111",
        "000000000000",
        "abcdefghijkl",
        "iloveyou",
        "iloveyouforever",
        "trustnoone",
        "welcomewelcome",
        "adminadmin",
        "administrator",
        "changeme",
        "changemenow",
        "secretsecret",
        "monkeymonkey",
        "dragondragon",
        "footballfootball",
        "princess",
        "sunshine",
        # Words this business makes likely. Somebody setting a password for a
        # payroll dashboard reaches for the dashboard's own name first.
        "hbaaesthetics",
        "hbaplatform",
        "hbawear",
        "hbaaffiliate",
        "affiliate",
        "commission",
        "instapay",
        "egyptegypt",
        "cairocairo",
    }
)

#: Substitutions people make believing they add strength. They do not: every
#: guessing tool tries them, so they are undone before comparing. Applied only
#: to the *word* form - undoing them on a numeric password turns "123456"
#: into "ieeasa" and hides it from every numeric entry in the list, which is
#: exactly the hole the first version of this had.
_LEETSPEAK = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"}
)

#: Below this, a common word appearing inside a longer password is more likely
#: coincidence than the password being built from it.
_MEANINGFUL = 6


def _forms(password: str) -> tuple[str, str]:
    """The two shapes a password has to be checked in.

    Two, not one, because they catch different things and each blinds the
    other. The **alphanumeric** form keeps digits, so a numeric password still
    looks numeric. The **word** form undoes leetspeak and drops digits, so
    `P@ssw0rd1234` and `password` are recognised as the same idea.
    """
    folded = unicodedata.normalize("NFKD", password).casefold()
    alnum = re.sub(r"[^a-z0-9]", "", folded)
    word = re.sub(r"[^a-z]", "", folded.translate(_LEETSPEAK))
    return alnum, word


def _is_one_repeated_thing(text: str) -> bool:
    """`abcabcabcabc` and `aaaaaaaaaaaa` are one short password wearing a long
    one's length. Anything built from a block of four or fewer characters,
    repeated three times or more to fill the space.
    """
    for size in range(1, 5):
        block = text[:size]
        if block and len(text) >= size * 3 and block * (len(text) // size) == text:
            return True
    return False


def _is_a_run(text: str) -> bool:
    """`abcdefghijkl` - each character one step from the last, the whole way."""
    if len(text) < 6:
        return False
    steps = {ord(b) - ord(a) for a, b in zip(text, text[1:])}
    return steps in ({1}, {-1})


def password_problem(password: str, *, personal: tuple[str, ...] = ()) -> str | None:
    """Why this password should not be accepted, or `None` if it is fine.

    Returns a sentence for the person choosing it, not an error code: they are
    mid-task, and the only useful answer is what to do instead.

    ``personal`` carries what the platform already knows about them - their
    email address and their name. A password containing their own address is
    guessable by anyone who has ever received an email from them.
    """
    alnum, word = _forms(password)

    if not alnum:
        return "That is only punctuation. Use some letters or numbers too."

    # Digits alone, however many. Twelve digits is a phone number or a date,
    # and both are things other people know.
    if alnum.isdigit():
        return "That is only numbers. Add some words - a phone number or a date is something other people know."

    if _is_one_repeated_thing(alnum) or _is_one_repeated_thing(word):
        return "That repeats one short pattern. Length only helps when it is not the same thing over and over."

    if _is_a_run(alnum) or _is_a_run(word):
        return "That is a straight run of keys. Choose something less predictable."

    # **Substring, not equality.** The first version compared whole strings,
    # so `password123456` sailed through a list containing `password` - which
    # is the single most likely password anybody would actually type.
    for common in _COMMON:
        if len(common) < _MEANINGFUL:
            continue
        if common in word or common in alnum:
            return "That is built from one of the most commonly used passwords. Choose another."

    for known in personal:
        _, known_word = _forms(str(known or ""))
        if len(known_word) >= _MEANINGFUL and known_word in word:
            return "That contains your own name or email address, which is the first thing anybody would try."

    return None


def password_strength(
    password: str, *, personal: tuple[str, ...] = ()
) -> int:
    """A score from 0 to 4, for the meter beside the field.

    **Feedback, never a gate.** What is enforced is length and
    `password_problem`; this exists so somebody can watch their password get
    stronger as they type, which is what actually makes people lengthen one. A
    meter that blocked would be a composition rule wearing a friendlier face.

    It takes ``personal`` for one reason: a meter that reads "good" on a
    password the server is about to refuse is worse than no meter at all.
    Anything `password_problem` would reject scores zero here.
    """
    if not password or password_problem(password, personal=personal) is not None:
        return 0

    score = 0
    if len(password) >= 12:
        score += 1
    if len(password) >= 16:
        score += 1
    if len(password) >= 20:
        score += 1

    kinds = sum(
        bool(re.search(pattern, password))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
    if kinds >= 3 and len(password) >= 12:
        score += 1

    return min(score, 4)
