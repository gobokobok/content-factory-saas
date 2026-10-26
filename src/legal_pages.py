"""The public legal pages (LEGAL-S1): /privacy and /terms, with the operator's details filled in.

The HTML files hold ``{{TOKEN}}`` markers. The values come from Settings (ENV.md, LEGAL_*), are
HTML-escaped, and an empty one is shown as a visible "to be completed" marker plus a banner at the
top of the page: an unfinished notice must never pass for a finished one.
"""

import html
from pathlib import Path

from fastapi.responses import HTMLResponse

from src.config import Settings

_STATIC_DIR = Path(__file__).parent / "static"
_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
_PAGES = {"terms": "terms.html", "privacy": "privacy.html"}


def _marker(env_name: str) -> str:
    """The visible placeholder shown while an operator detail is not set."""
    return f'<mark class="todo">[to be completed by the operator: {env_name}]</mark>'


def legal_values(settings: Settings) -> tuple[dict[str, str], list[str]]:
    """The token values for the legal pages, and the ENV names that are still unset."""
    contact = settings.LEGAL_CONTACT_EMAIL or settings.ABUSE_CONTACT_EMAIL
    raw = {
        "CONTROLLER_NAME": ("LEGAL_CONTROLLER_NAME", settings.LEGAL_CONTROLLER_NAME),
        "CONTROLLER_ADDRESS": ("LEGAL_CONTROLLER_ADDRESS", settings.LEGAL_CONTROLLER_ADDRESS),
        "CONTACT_EMAIL": ("LEGAL_CONTACT_EMAIL", contact),
        "GOVERNING_LAW": ("LEGAL_GOVERNING_LAW", settings.LEGAL_GOVERNING_LAW),
        "TRANSFER_BASIS": ("LEGAL_TRANSFER_BASIS", settings.LEGAL_TRANSFER_BASIS),
    }
    values: dict[str, str] = {}
    missing: list[str] = []
    for token, (env_name, value) in raw.items():
        if value.strip():
            values[token] = html.escape(value.strip())
        else:
            values[token] = _marker(env_name)
            missing.append(env_name)
    values["MIN_AGE"] = str(int(settings.MINIMUM_AGE))
    values["PROMPT_LOG_DAYS"] = (
        f"{int(settings.PROMPT_LOG_RETENTION_DAYS)} days" if settings.PROMPT_LOG_RETENTION_DAYS > 0 else "no fixed period"
    )
    values["SESSION_DAYS"] = str(int(settings.SESSION_TTL_DAYS))
    values["TERMS_VERSION"] = html.escape(settings.TERMS_VERSION)
    return values, missing


def render_legal_page(name: str, settings: Settings) -> HTMLResponse:
    """Render the named legal page ("terms" or "privacy") with the operator's details."""
    text = (_STATIC_DIR / _PAGES[name]).read_text(encoding="utf-8")
    values, missing = legal_values(settings)
    banner = ""
    if missing:
        banner = (
            '<p class="draft"><strong>Incomplete.</strong> The operator has not yet filled in: '
            + ", ".join(html.escape(m) for m in missing)
            + ". This notice is not final until they are set.</p>"
        )
    values["DRAFT_BANNER"] = banner
    values["STYLE"] = (_STATIC_DIR / "legal.css").read_text(encoding="utf-8")
    for token, value in values.items():
        text = text.replace("{{" + token + "}}", value)
    return HTMLResponse(text, headers=_NO_CACHE)
