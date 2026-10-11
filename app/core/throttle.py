"""How often somebody may try a password, or ask for a reset email.

Added by the security audit of October 2026: nothing limited either.

**Kept in this process's memory, deliberately.** The service runs one uvicorn
process on one replica (`railway.json`, `docker-entrypoint.sh`), so a counter
here sees every request. A deploy clears it, which gives an attacker back at
most one window - not worth a table and a migration. If the service ever runs
more than one process, this has to move to the database.

**Nobody may use a limit to lock somebody else out.** The strict limits are
keyed on an email *and* the address the attempt came from, so a stranger
guessing at an account pauses only their own attempts at it. The account-wide
limit is far higher and is cleared by a completed password reset, and reset
emails are never limited per account alone - so the owner can always get back
in. An email with no account is counted exactly like one with an account, so
a pause never says which addresses are real.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class Throttle:
    """At most `limit` attempts per key within a sliding `window` of seconds."""

    def __init__(self, limit: int, window: int, *, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window = window
        # Bounded, so a flood of invented addresses cannot grow it without end:
        # the key unused for longest is forgotten first.
        self._max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def acquire(self, key: str) -> int:
        """Count one attempt and return 0, or count nothing and return the
        seconds until `key` may try again.

        Checking and counting are one step under the lock: two requests
        arriving together cannot both see the last free slot.
        """
        now = time.monotonic()
        with self._lock:
            events = self._events.get(key)
            if events is None:
                events = self._events[key] = deque()
            while events and events[0] <= now - self.window:
                events.popleft()
            self._events.move_to_end(key)
            if len(events) >= self.limit:
                return max(1, int(events[0] + self.window - now) + 1)
            events.append(now)
            while len(self._events) > self._max_keys:
                self._events.popitem(last=False)
            return 0

    def release(self, key: str) -> None:
        """Take back the most recent attempt - it did not count after all."""
        with self._lock:
            events = self._events.get(key)
            if events:
                events.pop()

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def reset(self) -> None:
        """Forget everything. For tests."""
        with self._lock:
            self._events.clear()


def acquire_all(checks: list[tuple[Throttle, str]]) -> int:
    """Acquire every limit, or none of them: the first refusal takes back the
    attempts already counted and returns its wait."""
    taken: list[tuple[Throttle, str]] = []
    for limit, key in checks:
        wait = limit.acquire(key)
        if wait:
            for counted, counted_key in taken:
                counted.release(counted_key)
            return wait
        taken.append((limit, key))
    return 0


#: Wrong passwords for one email from one address. The right password is
#: refused too while paused - otherwise a pause only slows a guess.
LOGIN_PER_PAIR = Throttle(limit=10, window=15 * 60)

#: Wrong passwords for one email from anywhere. Far higher than the pair limit,
#: so only guessing from many addresses at once meets it, and a completed reset
#: clears it.
LOGIN_PER_ACCOUNT = Throttle(limit=100, window=15 * 60)

#: Wrong passwords from one address, across every email. Generous, and a sign-in
#: that works is taken back off it, so people signing in normally never meet it.
LOGIN_PER_SOURCE = Throttle(limit=50, window=15 * 60)

#: Reset emails for one email from one address. Past it the request still
#: answers "sent" and nothing is sent, so the cap says nothing about whether
#: the address is real - and a stranger cannot use up the owner's allowance.
RESET_PER_PAIR = Throttle(limit=3, window=60 * 60)

#: Reset requests from one address, across every email.
RESET_PER_SOURCE = Throttle(limit=20, window=60 * 60)

#: Reset emails for one email, used **only** when the visitor's address cannot
#: be seen (just the proxy's): the limit falls back to the email rather than
#: switching off. In that state a stranger could use up this allowance for an
#: hour - the price of never sending reset emails without end.
RESET_PER_ACCOUNT = Throttle(limit=5, window=60 * 60)

#: Wrong passwords at the re-check before a payout destination changes. Keyed on
#: the signed-in account, which only that account's sessions can reach.
PASSWORD_RECHECK = Throttle(limit=5, window=15 * 60)

ALL = (
    LOGIN_PER_PAIR,
    LOGIN_PER_ACCOUNT,
    LOGIN_PER_SOURCE,
    RESET_PER_PAIR,
    RESET_PER_SOURCE,
    RESET_PER_ACCOUNT,
    PASSWORD_RECHECK,
)


def try_again_message(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))
    return f"Too many attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."
