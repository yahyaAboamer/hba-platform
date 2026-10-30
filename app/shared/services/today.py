"""What one department says is waiting, for Today (Phase 2, batch 2.2).

Each department builds these in its own ``today.py`` and offers them through
its ``public.py``; ``app.shared.api.today`` gathers them. The shape is here so
the three departments and the page agree on it without importing each other.

**Every number comes from the function the department's own screen uses**, so
Today and the screen it opens can never disagree.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

#: How the page writes the time column (see the frontend's Today page).
ELAPSED = "elapsed"  # "4 h 43 m", "3 days", counted from ``since``
SINCE = "since"  # "since 10:05", "since yesterday", "since 26 Oct"
DEADLINE = "deadline"  # "7 days left", counted to ``due``


@dataclass(frozen=True)
class Item:
    """One thing waiting for somebody, with where it is done."""

    key: str
    department: str
    what: str
    detail: str
    go_label: str
    go_to: str
    broken: bool = False
    late: bool = False
    since: datetime | None = None
    due: date | None = None
    when: str | None = None

    def body(self) -> dict:
        return {
            "key": self.key,
            "department": self.department,
            "broken": self.broken,
            "late": self.late,
            "what": self.what,
            "detail": self.detail,
            "since": self.since.isoformat() if self.since else None,
            "due": self.due.isoformat() if self.due else None,
            "when": self.when,
            "go": {"label": self.go_label, "to": self.go_to},
        }


@dataclass
class Look:
    """Everything one department says for one person: its items, and the
    sidebar's numbers from the same reads.

    ``counts`` holds a key only for a number that was read; ``failures`` is
    Operations' sources whose latest read failed, each with its last clean
    read (ISO) or None.
    """

    items: list[Item] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    failures: dict[str, str | None] = field(default_factory=dict)
