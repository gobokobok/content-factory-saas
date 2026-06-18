"""Telegram trigger interface (P3-S1, D049) — thin trigger layer, no business logic.

D049 rules enforced here:
- Telegram is trigger-only: parse a recognized command, hand off to a block (later
  sprints), and reply. No internal Artifact/state schema is ever serialized to chat.
- All replies are produced by format_for_chat()-style formatter functions, never by
  dumping a model's `model_dump()`/`model_dump_json()` into the chat text.
- Implemented with plain httpx (no Telegram bot SDK), mirroring the
  Deepgram/ElevenLabs client pattern.
"""

import logging
from typing import TYPE_CHECKING, Optional

import httpx

from cf_platform.core.schemas import Signal

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cf_platform.workers.script_packager import ScriptArtifact
    from cf_platform.workers.topic_selector import RankedIdeasArtifact

_TELEGRAM_API_BASE = "https://api.telegram.org"
_TOP_SIGNALS_COUNT = 5


def parse_ideas_command(text: str) -> Optional[str]:
    """Parse a `/ideas <niche>` command.

    Returns the niche text (possibly empty if no niche was given), or None if
    `text` is not an `/ideas` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/ideas" or stripped.startswith("/ideas ")):
        return None
    return stripped[len("/ideas"):].strip()


def format_signals_summary(niche: str, run_id: str, artifact_key: str, signals: list[Signal]) -> str:
    """Format a readable summary of a discovery `SignalsArtifact` for `/ideas <niche>` (D049, P3-S3).

    Lists the top `_TOP_SIGNALS_COUNT` signals (by score, descending) with their
    source and title, plus the run_id and artifact key for traceability. Plain
    string only — never serializes the artifact itself to chat.
    """
    if not signals:
        return f'No signals found for "{niche}" (run {run_id}).'

    top_signals = sorted(signals, key=lambda signal: signal.score, reverse=True)[:_TOP_SIGNALS_COUNT]
    lines = [f'Top signals for "{niche}" ({len(signals)} found, run {run_id}):']
    for signal in top_signals:
        lines.append(f"- [{signal.source}] {signal.title} (score {signal.score:g})")
    lines.append(f"Artifact: {artifact_key}")
    return "\n".join(lines)


_TOP_ALTERNATIVES_COUNT = 3


def format_ranked_ideas(niche: str, run_id: str, artifact_key: str, ranked_ideas: "RankedIdeasArtifact") -> str:
    """Format a ranked ideas reply for `/ideas <niche>` after the full block runs (D049, P4-S5).

    Shows the selected idea with its 7-axis scores and final composite score, then
    the top `_TOP_ALTERNATIVES_COUNT` alternatives by final_score. Plain string only —
    never serializes the artifact itself to chat. run_id and artifact_key are accepted
    for call-site consistency but intentionally omitted from the reply text.
    """
    sel = ranked_ideas.selected
    score_row1 = (
        f"novelty {sel.novelty:.1f} · relevance {sel.audience_relevance:.1f} · "
        f"emotion {sel.emotional_trigger:.1f} · demand {sel.search_demand:.1f}"
    )
    score_row2 = (
        f"competition {sel.competition:.1f} · evergreen {sel.evergreen_potential:.1f} · "
        f"monetize {sel.monetization_relevance:.1f}"
    )
    lines = [
        f'Ideas — "{niche}"',
        "",
        f"★ {sel.title}",
        f"",
        f"  {sel.angle}",
        f"",
        f"  Score: {sel.final_score:.2f} / 10",
        f"  {score_row1}",
        f"  {score_row2}",
    ]
    top_alts = ranked_ideas.alternatives[:_TOP_ALTERNATIVES_COUNT]
    if top_alts:
        lines.append("")
        lines.append("Runner-ups:")
        for alt in top_alts:
            lines.append(f"  • {alt.title} ({alt.final_score:.2f})")
    return "\n".join(lines)


def format_ideas_running(niche: str) -> str:
    """Format the immediate ack sent before the background graph run starts (D049)."""
    return f'Running ideas for "{niche}"... results in ~60 s.'


def format_ideas_usage() -> str:
    """Format the reply when `/ideas` is sent without a niche (D049)."""
    return "Usage: /ideas <niche> — e.g. /ideas starter homes"


def parse_script_command(text: str) -> Optional[str]:
    """Parse a `/script <idea_title>` command.

    Returns the idea title text (possibly empty if no title was given), or None if
    `text` is not a `/script` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/script" or stripped.startswith("/script ")):
        return None
    return stripped[len("/script"):].strip()


def format_script_running(idea_title: str) -> str:
    """Format the immediate ack sent before the background idea→script run starts (D049)."""
    return f'Writing script for "{idea_title}"... results in ~90 s.'


def format_script_usage() -> str:
    """Format the reply when `/script` is sent without an idea title (D049)."""
    return "Usage: /script <idea title> — e.g. /script Why starter homes vanished"


_SCRIPT_REPLY_CHAR_LIMIT = 4000


def format_script_reply(script_artifact: "ScriptArtifact") -> str:
    """Format the finished script reply after the idea→script block runs (D049, P5-S5).

    Shows the idea title, quality score (when available), and the full script text.
    Truncates to `_SCRIPT_REPLY_CHAR_LIMIT` characters to stay within Telegram's
    4096-char limit. Plain string only — never serializes the artifact itself to chat.
    """
    header = f'Script — "{script_artifact.idea_title}"'
    if script_artifact.overall_score is not None:
        header += f"\nScore: {script_artifact.overall_score:.1f}/10"
    if getattr(script_artifact, "status", "ok") == "manual_review":
        header += "\n⚠️ Manual review required"
    lines = [header, "", script_artifact.script]
    text = "\n".join(lines)
    if len(text) > _SCRIPT_REPLY_CHAR_LIMIT:
        text = text[:_SCRIPT_REPLY_CHAR_LIMIT - 3] + "..."
    return text


def format_unrecognized_command(text: str) -> str:
    """Format the reply for any unrecognized command or message (D049)."""
    return "Sorry, I didn't understand that. Try: /ideas <niche> or /script <idea title>"


def is_chat_allowed(chat_id: int, allowed_chat_ids: str) -> bool:
    """Return True if `chat_id` may trigger replies.

    `allowed_chat_ids` is a comma-separated list of Telegram chat ids
    (TELEGRAM_ALLOWED_CHAT_IDS). An empty string means unrestricted — every
    chat is allowed. This is a temporary single-operator allowlist ahead of
    S19 multi-tenant auth.
    """
    if not allowed_chat_ids.strip():
        return True
    allowed = {int(part.strip()) for part in allowed_chat_ids.split(",") if part.strip()}
    return chat_id in allowed


class TelegramClient:
    """Thin httpx wrapper over the Telegram Bot API (D049 — no bot SDK)."""

    def __init__(self, bot_token: str) -> None:
        """Store the bot token used to build Telegram Bot API URLs."""
        self._bot_token = bot_token

    async def send_message(self, chat_id: int, text: str) -> None:
        """Send a plain-text reply to a chat via sendMessage.

        No-ops if `bot_token` is empty (D048-style fault isolation — a missing
        token must not crash the webhook handler).
        """
        if not self._bot_token:
            _logger.warning("TelegramClient.send_message called but TELEGRAM_BOT_TOKEN is not set — reply suppressed")
            return
        url = f"{_TELEGRAM_API_BASE}/bot{self._bot_token}/sendMessage"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json={"chat_id": chat_id, "text": text}, timeout=10.0
            )
            response.raise_for_status()

    async def register_webhook(self, webhook_url: str, secret_token: str) -> dict:
        """Register `webhook_url` with Telegram via setWebhook, including the shared secret token."""
        url = f"{_TELEGRAM_API_BASE}/bot{self._bot_token}/setWebhook"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"url": webhook_url, "secret_token": secret_token},
                timeout=10.0,
            )
            response.raise_for_status()
            return response.json()
