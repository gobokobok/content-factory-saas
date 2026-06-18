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
import re
from typing import TYPE_CHECKING, Optional, Tuple

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


_DURATION_FLAG_RE = re.compile(r"\s*--duration\s+(\d+)\s*$")
_DEFAULT_DURATION_SECONDS = 60


def parse_script_duration_args(args: str) -> Tuple[str, int]:
    """Split `args` (text after `/script`) into (idea_title, target_duration_seconds).

    Extracts a trailing `--duration <seconds>` flag. Defaults to 60 s when the
    flag is absent or the value is not a positive integer. The flag must appear at
    the end of the string.

    Examples:
        "Why starter homes vanished"              → ("Why starter homes vanished", 60)
        "Why starter homes vanished --duration 45" → ("Why starter homes vanished", 45)
        "Topic --duration 0"                       → ("Topic", 60)  # 0 is not positive
    """
    match = _DURATION_FLAG_RE.search(args)
    if match:
        title = args[: match.start()].strip()
        try:
            seconds = int(match.group(1))
        except ValueError:
            seconds = _DEFAULT_DURATION_SECONDS
        duration = seconds if seconds > 0 else _DEFAULT_DURATION_SECONDS
        return (title, duration)
    return (args.strip(), _DEFAULT_DURATION_SECONDS)


def format_script_running(idea_title: str) -> str:
    """Format the immediate ack sent before the background idea→script run starts (D049)."""
    return f'Writing script for "{idea_title}"... results in ~90 s.'


def format_script_usage() -> str:
    """Format the reply when `/script` is sent without an idea title (D049)."""
    return "Usage: /script <idea title> [--duration <seconds>] — e.g. /script Why starter homes vanished --duration 45"


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


def parse_produce_command(text: str) -> Optional[str]:
    """Parse a `/produce <niche>` command.

    Returns the args text (possibly empty if no niche was given), or None if
    `text` is not a `/produce` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/produce" or stripped.startswith("/produce ")):
        return None
    return stripped[len("/produce"):].strip()


_PRODUCE_DURATION_FLAG_RE = re.compile(r"\s*--duration\s+(\d+)\s*$")


def parse_produce_args(args: str) -> tuple[str, int]:
    """Split `args` (text after `/produce`) into (niche, target_duration_seconds).

    Extracts a trailing `--duration <seconds>` flag. Defaults to 60 s when the
    flag is absent or the value is not a positive integer.

    Examples:
        "american housing economics"                   → ("american housing economics", 60)
        "american housing economics --duration 45"     → ("american housing economics", 45)
        "coffee culture --duration 0"                  → ("coffee culture", 60)
    """
    match = _PRODUCE_DURATION_FLAG_RE.search(args)
    if match:
        niche = args[: match.start()].strip()
        try:
            seconds = int(match.group(1))
        except ValueError:
            seconds = _DEFAULT_DURATION_SECONDS
        duration = seconds if seconds > 0 else _DEFAULT_DURATION_SECONDS
        return (niche, duration)
    return (args.strip(), _DEFAULT_DURATION_SECONDS)


def format_produce_running(niche: str) -> str:
    """Format the immediate ack sent before the full pipeline run starts (D049)."""
    return f'Producing video for "{niche}"... this takes ~5–10 minutes.'


def format_produce_usage() -> str:
    """Format the reply when `/produce` is sent without a niche (D049)."""
    return "Usage: /produce <niche> [--duration <seconds>] — e.g. /produce american housing economics --duration 45"


_PRODUCE_URL_EXPIRY_LABEL = "24 h"


def format_produce_reply(niche: str, run_id: str, video_url: str) -> str:
    """Format the finished video reply after the full pipeline completes (D049, P6-S4).

    Shows the niche, run_id, a presigned download URL, and the URL expiry label.
    Plain string only — never serializes any internal schema to chat.
    """
    return (
        f'Video ready — "{niche}"\n'
        f"Run: {run_id}\n\n"
        f"Download (expires {_PRODUCE_URL_EXPIRY_LABEL}):\n{video_url}"
    )


_HITL_SCRIPT_PREVIEW_LIMIT = 2000


def format_script_approval_request(run_id: str, script_preview: str) -> str:
    """Format the HITL script-approval message sent when the pipeline gate fires (D049, P6-S3).

    Shows the first `_HITL_SCRIPT_PREVIEW_LIMIT` characters of the script and
    instructions for approving or rejecting. Plain string only.
    """
    if len(script_preview) > _HITL_SCRIPT_PREVIEW_LIMIT:
        preview = script_preview[:_HITL_SCRIPT_PREVIEW_LIMIT] + "..."
    else:
        preview = script_preview
    return (
        f"Script ready for approval (run {run_id}):\n\n"
        f"{preview}\n\n"
        f"Reply /approve {run_id} to continue or /reject {run_id} to cancel."
    )


def parse_hitl_decision(text: str) -> Optional[tuple[str, str]]:
    """Parse an `/approve <run_id>` or `/reject <run_id>` Telegram command.

    Returns (decision, run_id) where decision is "approve" or "reject".
    Returns None if `text` is not a complete, recognized HITL command.
    """
    stripped = text.strip()
    for decision in ("approve", "reject"):
        prefix = f"/{decision} "
        if stripped.startswith(prefix):
            run_id = stripped[len(prefix):].strip()
            if run_id:
                return (decision, run_id)
    return None


def format_hitl_approved(run_id: str) -> str:
    """Format the ack sent when the operator approves a pipeline run (D049, P6-S3)."""
    return f"Run {run_id} approved — continuing to render..."


def format_hitl_rejected(run_id: str) -> str:
    """Format the ack sent when the operator rejects a pipeline run (D049, P6-S3)."""
    return f"Run {run_id} rejected — pipeline cancelled."


def format_unrecognized_command(text: str) -> str:
    """Format the reply for any unrecognized command or message (D049)."""
    return "Sorry, I didn't understand that. Try: /ideas <niche>, /script <idea title>, or /produce <niche>"


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
