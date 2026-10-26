"""A browser's user-agent header, said the way a person would say it.

For Settings → Me → *Signed in on* (ADR 0067, decision 6): "Chrome on Windows",
"Safari on iPhone". Worked out here from the header the session already keeps
(`auth_session.user_agent`), with no outside lookup and no library - the
header is the visitor's own words, so this only ever reads it and never trusts
it for anything but a label.

**The order of the checks is the point.** Browsers name each other for
compatibility: Edge's header says Chrome and Safari, Chrome's says Safari, and
Chrome on an iPhone says Safari as well. So the most specific names are looked
for first, and Safari is what is left.
"""

from __future__ import annotations

import re

UNKNOWN = "Unknown browser"

#: (pattern, name), most specific first.
_BROWSERS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name)
    for pattern, name in (
        (r"\bEdg(e|A|iOS)?/", "Edge"),
        (r"\b(OPR|OPT)/|\bOpera\b", "Opera"),
        (r"\bSamsungBrowser/", "Samsung Internet"),
        (r"\b(Firefox|FxiOS)/", "Firefox"),
        (r"\bCriOS/", "Chrome"),
        (r"\bChrom(e|ium)/", "Chrome"),
        (r"\bVersion/[\d.]+.*\bSafari/", "Safari"),
    )
)

_SYSTEMS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), name)
    for pattern, name in (
        (r"\biPhone\b", "iPhone"),
        (r"\biPad\b", "iPad"),
        (r"\bAndroid\b", "Android"),
        (r"\bCrOS\b", "ChromeOS"),
        (r"\bWindows\b", "Windows"),
        (r"\bMac OS X\b|\bMacintosh\b", "Mac"),
        (r"\bLinux\b", "Linux"),
    )
)


def _first(table: tuple[tuple[re.Pattern[str], str], ...], text: str) -> str | None:
    for pattern, name in table:
        if pattern.search(text):
            return name
    return None


def device_label(user_agent: str | None) -> str:
    """"Chrome on Windows", "Firefox", "Unknown browser on Android" - or
    "Unknown browser" when the header says nothing recognisable."""
    text = str(user_agent or "")[:400]
    browser = _first(_BROWSERS, text)
    system = _first(_SYSTEMS, text)
    if browser and system:
        return f"{browser} on {system}"
    if browser:
        return browser
    if system:
        return f"{UNKNOWN} on {system}"
    return UNKNOWN
