"""What a Basic account may reach (Sprint P-AUTH S6, D118).

The server, not the page, decides. Everything a Basic account may call is listed
here; **anything not listed requires Super** (deny by default), so a route added
later is closed to Basic until someone opens it on purpose. The auth middleware
(src/main.py) applies :func:`basic_may` to every request whose principal is not
Super — including the owner while *View as Basic* is on.

Pages: Basic gets the Creator (`/create`), the shared UI assets and the login page.
Calls: the Creator's own routes plus the Studio routes the Creator pages reuse,
each still scoped to the caller's own runs by the tenant guard (guards.py).
"""

import re
from collections.abc import Iterable

_ID = r"[^/]+"

# (method set or None for any, compiled path pattern). Order is irrelevant.
_BASIC_ROUTES: tuple[tuple[frozenset[str] | None, re.Pattern[str]], ...] = tuple(
    (methods, re.compile(f"^{pattern}$"))
    for methods, pattern in (
        # Pages and shared assets.
        (frozenset({"GET"}), r"/create"),
        (frozenset({"GET"}), r"/login"),
        (frozenset({"GET"}), r"/health"),
        (frozenset({"GET"}), r"/ui/.+"),
        # Session routes (view-as and the like check Super themselves).
        (None, r"/auth/.+"),
        # The Creator's own routes.
        (frozenset({"GET"}), r"/platform/creator/config"),
        (frozenset({"POST"}), r"/platform/creator/runs"),
        (frozenset({"GET"}), rf"/platform/projects/{_ID}/runs"),
        # The Studio routes the Creator pages call (creator.js).
        (frozenset({"GET"}), rf"/platform/studio/runs/{_ID}/(context|ai-spend|manifest|script|video|voice|voice/status|render/status|storyboard/status)"),
        (frozenset({"GET", "POST"}), rf"/platform/studio/runs/{_ID}/storyboard"),
        (frozenset({"GET"}), rf"/platform/studio/runs/{_ID}/images/(plan|status)"),
        (frozenset({"POST"}), rf"/platform/studio/runs/{_ID}/images/generate"),
        (frozenset({"POST"}), rf"/platform/studio/runs/{_ID}/music"),
        (frozenset({"PATCH"}), rf"/platform/studio/runs/{_ID}/storyboard/scenes/{_ID}"),
        (frozenset({"POST"}), rf"/platform/studio/runs/{_ID}/storyboard/scenes/{_ID}/(split|merge|write-prompt)"),
        (frozenset({"PUT"}), rf"/platform/studio/runs/{_ID}/storyboard/boundaries"),
        (frozenset({"POST"}), rf"/platform/studio/runs/{_ID}/storyboard/continuity"),
        (frozenset({"PATCH", "DELETE"}), rf"/platform/studio/runs/{_ID}/storyboard/continuity/{_ID}"),
        (frozenset({"POST"}), rf"/platform/studio/runs/{_ID}/scenes/{_ID}/(generate|upload|prompt-preview)"),
        # The run's own settings (the Creator reads and writes the look, cast and voice).
        (frozenset({"GET", "POST"}), rf"/runs/{_ID}/settings"),
        # The three long jobs.
        (frozenset({"POST"}), r"/platform/workers/(voice|storyboard|render)"),
    )
)

# Page paths a Basic browser navigation is sent to when it asks for a Super page.
BASIC_HOME = "/create"


def basic_may(method: str, path: str) -> bool:
    """True when a Basic account may call method on path. Everything not listed is Super-only."""
    verb = method.upper()
    if verb == "OPTIONS":
        return True
    for methods, pattern in _BASIC_ROUTES:
        if (methods is None or verb in methods) and pattern.match(path):
            return True
    return False


def basic_patterns() -> Iterable[tuple[frozenset[str] | None, str]]:
    """The allow-list as (methods, pattern text) — for tests and for documentation."""
    return ((methods, pattern.pattern) for methods, pattern in _BASIC_ROUTES)
