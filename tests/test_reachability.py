"""Can every capability be reached from the interface?

Every bug the business found by *using* the deployed platform was the same
shape, and none of them was visible from a test suite:

- the email handler was registered to the wrong function, so nothing ever
  reached it
- inviting a model had no control anywhere; the whole flow existed and could
  not be started
- order history could not be imported at all, which is step 3 of the cutover
- a returning tab held a live session and no CSRF token, so every write failed

**A suite that drives the API starts one step after the button.** This is the
other step: every route the server offers, against every call the interface
makes.

Deliberately a *ratchet*, not a rule. Routes reached by something other than
our own screens are listed by name with a reason, and a new one has to be
added here on purpose — which is the moment somebody asks whether it needs a
screen. The list only ever gets shorter.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"

VERBS = {
    "get": "GET",
    "post": "POST",
    "put": "PUT",
    "patch": "PATCH",
    "upload": "POST",
}

#: Called by somebody other than our own interface, or superseded by a route
#: that is. Each needs a reason, because "nothing calls it" is otherwise
#: indistinguishable from "we forgot to build the screen".
UNREACHED_ON_PURPOSE = {
    # Shopify calls these, and Railway calls the health checks.
    ("POST", "/api/webhooks/shopify"),
    ("GET", "/api/health/live"),
    ("GET", "/api/health/ready"),
    # Superseded. The payroll screen answers the same question with the
    # blockers attached, which is what anybody actually needs.
    ("GET", "/api/earnings/{month}"),
    # Diagnostics, reached by hand when something is wrong. A screen for each
    # would be four screens nobody opens in a normal month.
    ("GET", "/api/auth/status"),
    ("GET", "/api/operations/order-facts"),
    ("GET", "/api/operations/shopify-scopes"),
    ("POST", "/api/operations/verify-code"),
    # The affiliate's own equivalent is on their payments screen; the
    # maintainer's is the destination_changed_at flag already on the payments
    # row, which is where the warning belongs (§6.4.5).
    ("GET", "/api/me/payout-destination/changed-recently"),
}

#: Gaps, not decisions. Each is a capability the platform has and the interface
#: cannot reach, found by the audit below and **not yet built**.
#:
#: Listed rather than exempted so the difference stays visible: the set above
#: is things that need no screen, and this is things that need one and do not
#: have it. The test asserts the real list matches these two exactly, so it
#: fails both when something new becomes unreachable *and* when something here
#: is finally built and should be struck off.
NOT_BUILT_YET = {
    # Cannot create a *model* without an invitation - the case of a real
    # person with no email at all, who has nobody to send a link to.
    #
    # The other half of this gap - a house account, which is not a person and
    # never had an invitation to begin with - is solved: `create_house_account`
    # gives it a `user_account` it can never sign into, exposed at
    # `POST /api/affiliates/house`. What is left is narrower than it looked:
    # not "affiliates without invitations" in general, just a model who
    # genuinely cannot receive one.
    ("POST", "/api/affiliates"),
}


def _clean(raw: str) -> str:
    """A template literal reduced to the path shape the server would match.

    A nested template - `/api/audit${query ? `?subject=...` : ""}` - cannot be
    captured whole by a regex that stops at a backtick, so whatever is left
    dangling after an unclosed interpolation is cut off. The head of the path
    is the part that identifies the route either way.
    """
    cleaned = re.sub(r"\$\{[^}]*\}", "{}", raw)
    if "${" in cleaned:
        cleaned = cleaned.split("${")[0]
    return cleaned.split("?")[0].rstrip("/")


def _normalise(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path).split("?")[0].rstrip("/")


def _served() -> set[tuple[str, str]]:
    from app.api import (
        affiliate_self,
        affiliates,
        applications,
        audit,
        auth,
        earnings,
        health,
        operations,
        orders,
        payments,
        payroll,
        policy,
        staff,
        targets,
        webhooks,
    )

    found: set[tuple[str, str]] = set()
    for module in (
        affiliate_self, affiliates, applications, audit, auth, earnings,
        health, operations, orders, payments, payroll, policy, staff, targets,
        webhooks,
    ):
        for route in module.router.routes:
            for method in getattr(route, "methods", set()):
                if method not in ("HEAD", "OPTIONS"):
                    found.add((method, route.path))
    return found


def _called() -> set[tuple[str, str]]:
    """Every (method, path) the interface asks for.

    Method matters. Comparing paths alone reported `POST /api/affiliates` as
    reachable because something did a GET on the same path — which is exactly
    the gap being looked for.
    """
    calls: set[tuple[str, str]] = set()
    # The house style puts the verb on its own line, so whitespace is
    # allowed around the dot. An earlier version required them contiguous
    # and reported a dozen screens as having no way in.
    call = re.compile(
        r"""api\s*\.\s*(get|post|put|patch|upload)\s*(?:<[^>]*>)?\s*\(\s*[`"']([^`"']*)[`"']"""
    )
    image = re.compile(r"""src=\{`(/api/[^`]*)`\}""")

    for file in FRONTEND.rglob("*.ts*"):
        text = file.read_text(encoding="utf-8")
        for verb, raw in call.findall(text):
            calls.add((VERBS[verb], _clean(raw)))
        # An <img src> is a GET the browser makes on its own.
        for raw in image.findall(text):
            calls.add(("GET", _clean(raw)))
    return calls


def test_every_capability_has_a_way_in():
    """A route nothing can reach is a feature that does not exist.

    A ratchet in both directions. It fails when something **new** becomes
    unreachable, which is the moment to build the control or say why none is
    needed — and it fails when something on `NOT_BUILT_YET` finally becomes
    reachable, so the list of known gaps cannot quietly go stale.

    The two lists say different things and stay apart: `UNREACHED_ON_PURPOSE`
    is what needs no screen, `NOT_BUILT_YET` is what needs one and has not got
    it. Collapsing them would turn a debt into a decision.
    """
    called = {(method, _normalise(path)) for method, path in _called()}
    unreachable = {
        (method, _normalise(path))
        for method, path in _served()
        if (method, _normalise(path)) not in called
    }
    accounted = {
        (method, _normalise(path))
        for method, path in UNREACHED_ON_PURPOSE | NOT_BUILT_YET
    }

    appeared = sorted(unreachable - accounted)
    assert not appeared, (
        "New capabilities with no way in from the interface:"
        + "".join(f"\n  {method:<6} {path}" for method, path in appeared)
        + "\n\nBuild the control, or record why it needs none."
    )

    built = sorted(accounted - unreachable)
    assert not built, (
        "Reachable now, so strike these off the list:"
        + "".join(f"\n  {method:<6} {path}" for method, path in built)
    )


def test_the_interface_never_calls_something_that_is_not_served():
    """A path that moved, or a typo. Either way it is a screen that fails when
    somebody presses the button, and nothing else would notice.
    """
    served_paths = {_normalise(path) for _, path in _served()}
    missing = sorted(
        path
        for _, path in _called()
        if path.startswith("/api") and path not in served_paths
    )

    assert not missing, "The interface calls paths nothing serves:\n  " + "\n  ".join(
        missing
    )


def test_the_exemption_list_is_still_honest():
    """An exemption for a route that no longer exists is a comment pretending
    to be a decision.
    """
    served = {(method, _normalise(path)) for method, path in _served()}
    stale = sorted(
        (method, path)
        for method, path in UNREACHED_ON_PURPOSE | NOT_BUILT_YET
        if (method, _normalise(path)) not in served
    )

    assert not stale, "These exemptions name routes that are gone:\n  " + "\n  ".join(
        f"{method} {path}" for method, path in stale
    )
