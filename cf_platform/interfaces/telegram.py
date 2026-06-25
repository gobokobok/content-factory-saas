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
    from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

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


_IDEAS_TOP_N = 5


def format_ranked_ideas(niche: str, run_id: str, artifact_key: str, ranked_ideas: "RankedIdeasArtifact") -> str:
    """Format a ranked ideas reply for `/ideas <niche>` after the full block runs (D049, P7-S1).

    Shows up to `_IDEAS_TOP_N` ideas numbered 1–N (selected first, then alternatives)
    with title, angle, and composite score. Includes the run_id and a `/pick` call-to-action
    so the operator can select an idea for production. Plain string only — never serializes
    the artifact itself to chat.
    """
    all_ideas = [ranked_ideas.selected] + list(ranked_ideas.alternatives)
    top_ideas = all_ideas[:_IDEAS_TOP_N]

    lines = [f'Ideas — "{niche}" (run {run_id})', ""]
    for i, idea in enumerate(top_ideas, start=1):
        lines.append(f"{i}. {idea.title}")
        lines.append(f"   {idea.angle}")
        lines.append(f"   Score: {idea.final_score:.2f} / 10")
        if i < len(top_ideas):
            lines.append("")
    lines.append("")
    lines.append(f"Pick one: /pick {run_id} <n>")
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


_FORMAT_FLAG_RE = re.compile(r"\s*--format\s+(\w+)\b", re.IGNORECASE)
_DEFAULT_FORMAT_TRACK = "landscape"
_VALID_FORMAT_TRACKS = frozenset(("portrait", "landscape"))


def _parse_format_flag(args: str) -> tuple[str, str]:
    """Extract a `--format portrait|landscape` flag from args, returning (text, format_track).

    The flag can appear anywhere in the string. Defaults to 'landscape' when absent.
    Unknown values fall back to 'landscape' with a warning logged.
    """
    match = _FORMAT_FLAG_RE.search(args)
    if not match:
        return args.strip(), _DEFAULT_FORMAT_TRACK
    fmt = match.group(1).lower()
    if fmt not in _VALID_FORMAT_TRACKS:
        _logger.warning("Unknown --format value %r — falling back to landscape", fmt)
        fmt = _DEFAULT_FORMAT_TRACK
    remaining = (args[:match.start()] + args[match.end():]).strip()
    return remaining, fmt


def _parse_duration_flag(args: str) -> tuple[str, int]:
    """Extract a trailing `--duration <seconds>` flag from `args`, returning (text, duration).

    Returns the flag-stripped text and the parsed duration. Defaults to 60 s when the
    flag is absent or the value is not a positive integer.
    """
    match = _DURATION_FLAG_RE.search(args)
    if match:
        text = args[: match.start()].strip()
        try:
            seconds = int(match.group(1))
        except ValueError:
            seconds = _DEFAULT_DURATION_SECONDS
        duration = seconds if seconds > 0 else _DEFAULT_DURATION_SECONDS
        return (text, duration)
    return (args.strip(), _DEFAULT_DURATION_SECONDS)


# ── /run <niche> — full niche-to-video pipeline ───────────────────────────────


def parse_run_command(text: str) -> Optional[str]:
    """Parse a `/run <niche>` command (was /produce in P6-S4; renamed in P7-S1).

    Returns the args text (possibly empty if no niche was given), or None if
    `text` is not a `/run` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/run" or stripped.startswith("/run ")):
        return None
    return stripped[len("/run"):].strip()


def parse_run_args(args: str) -> tuple[str, int, str]:
    """Split `args` (text after `/run`) into (niche, target_duration_seconds, format_track).

    Extracts `--duration <seconds>` and `--format portrait|landscape` flags in any order.
    Defaults to 60 s and 'landscape' when flags are absent. Unknown format values fall back
    to 'portrait' with a warning.

    Examples:
        "american housing economics"                              → ("american housing economics", 60, "portrait")
        "american housing economics --duration 45"               → ("american housing economics", 45, "portrait")
        "american housing economics --format landscape"          → ("american housing economics", 60, "landscape")
        "american housing economics --format landscape --duration 45" → ("american housing economics", 45, "landscape")
    """
    args, format_track = _parse_format_flag(args)
    text, duration = _parse_duration_flag(args)
    return text, duration, format_track


_VIDEO_URL_EXPIRY_LABEL = "24 h"


def format_run_running(niche: str) -> str:
    """Format the immediate ack sent before the full /run pipeline starts (D049)."""
    return f'Running full pipeline for "{niche}"... this takes ~5–10 minutes.'


def format_run_usage() -> str:
    """Format the reply when `/run` is sent without a niche (D049)."""
    return "Usage: /run <niche> [--duration <seconds>] [--format portrait|landscape] — e.g. /run american housing economics --format landscape"


def format_run_reply(niche: str, run_id: str, video_url: str) -> str:
    """Format the finished video reply after a /run pipeline completes (D049).

    Shows the niche, run_id, a presigned download URL, and the URL expiry label.
    Plain string only — never serializes any internal schema to chat.
    """
    return (
        f'Video ready — "{niche}"\n'
        f"Run: {run_id}\n\n"
        f"Download (expires {_VIDEO_URL_EXPIRY_LABEL}):\n{video_url}"
    )


# ── /produce <idea title> — named-idea pipeline (skips discovery) ─────────────


def parse_produce_command(text: str) -> Optional[str]:
    """Parse a `/produce <idea title>` command (P7-S1).

    Starts production from a named idea title, skipping the niche→ideas discovery
    block. Returns the args text (possibly empty), or None if `text` is not a
    `/produce` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/produce" or stripped.startswith("/produce ")):
        return None
    return stripped[len("/produce"):].strip()


def parse_produce_args(args: str) -> tuple[str, int, str]:
    """Split `args` (text after `/produce`) into (idea_title, target_duration_seconds, format_track).

    Extracts `--duration <seconds>` and `--format portrait|landscape` flags in any order.
    Defaults to 60 s and 'landscape' when flags are absent. Unknown format values fall back
    to 'portrait' with a warning.

    Examples:
        "Why starter homes vanished"                        → ("Why starter homes vanished", 60, "portrait")
        "Why starter homes vanished --duration 45"         → ("Why starter homes vanished", 45, "portrait")
        "Why starter homes vanished --format landscape"    → ("Why starter homes vanished", 60, "landscape")
    """
    args, format_track = _parse_format_flag(args)
    text, duration = _parse_duration_flag(args)
    return text, duration, format_track


def format_produce_running(idea_title: str) -> str:
    """Format the immediate ack sent before a /produce named-idea pipeline starts (D049, P7-S1)."""
    return f'Producing "{idea_title}"... this takes ~5–10 minutes.'


def format_produce_usage() -> str:
    """Format the reply when `/produce` is sent without an idea title (D049, P7-S1)."""
    return "Usage: /produce <idea title> [--duration <seconds>] [--format portrait|landscape] — e.g. /produce Why starter homes vanished --format landscape"


def format_youtube_metadata_block(metadata: "YoutubeMetadataArtifact") -> str:
    """Format a YoutubeMetadataArtifact as a copy-paste block for the operator (D049, P7-S3).

    Produces a plain-text block with title, description, and comma-separated tags.
    Plain string only — never serializes the artifact itself to chat.
    """
    tags_line = ", ".join(metadata.tags)
    return (
        "\n\n─── YouTube Metadata ───\n"
        f"Title: {metadata.title}\n\n"
        f"Description:\n{metadata.description}\n\n"
        f"Tags: {tags_line}"
    )


_FOOTAGE_SOURCE_LABELS = [
    ("pexels", "Pexels"),
    ("pixabay", "Pixabay"),
    ("wikimedia", "Wikimedia"),
    ("wikimedia_person", "Person"),
    ("replicate", "AI"),
]


def format_footage_summary(summary: dict) -> str:
    """Format the per-source footage breakdown for the Telegram reply (D049, P8-S5).

    Returns a single-line coverage string, e.g. "Footage: 14 Pexels · 4 Pixabay · 2 Person".
    Appends a QA warning line when `qa_failed_scenes > 0`.
    """
    parts = [
        f"{summary.get(key, 0)} {label}"
        for key, label in _FOOTAGE_SOURCE_LABELS
        if summary.get(key, 0) > 0
    ]
    line = "Footage: " + " · ".join(parts) if parts else "Footage: (none)"
    qa_failed = summary.get("qa_failed_scenes", 0)
    if qa_failed > 0:
        line += f"\n⚠️ {qa_failed} scenes below QA threshold"
    return line


def format_produce_reply(
    idea_title: str,
    run_id: str,
    video_url: str,
    metadata: Optional["YoutubeMetadataArtifact"] = None,
    footage_summary: Optional[dict] = None,
) -> str:
    """Format the finished video reply after a /produce pipeline completes (D049, P7-S1/S3).

    Shows the idea title, run_id, a presigned download URL, and the URL expiry label.
    Appends the YouTube metadata block when `metadata` is provided (P7-S3).
    Plain string only — never serializes any internal schema to chat.
    """
    text = (
        f'Video ready — "{idea_title}"\n'
        f"Run: {run_id}\n\n"
        f"Download (expires {_VIDEO_URL_EXPIRY_LABEL}):\n{video_url}"
    )
    if footage_summary is not None:
        text += "\n\n" + format_footage_summary(footage_summary)
    if metadata is not None:
        text += format_youtube_metadata_block(metadata)
    return text


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


def parse_testvoice_command(text: str) -> Optional[str]:
    """Parse a `/testvoice <run_id>` command.

    Returns the run_id text (possibly empty if absent), or None if `text` is
    not a `/testvoice` command at all.
    """
    stripped = text.strip()
    if not (stripped == "/testvoice" or stripped.startswith("/testvoice ")):
        return None
    return stripped[len("/testvoice"):].strip()


def format_testvoice_running(run_id: str) -> str:
    """Format the immediate ack sent before the background testvoice run starts (D049)."""
    return f"Generating voice for run {run_id}... presigned MP3 URL in ~30 s."


_TESTVOICE_MP3_URL_EXPIRY_LABEL = "1 h"


def format_testvoice_reply(run_id: str, mp3_url: str) -> str:
    """Format the finished testvoice reply after voice_production completes (D049, P6-S7).

    Shows the run_id and a presigned download URL for the generated MP3.
    Plain string only — never serializes any internal schema to chat.
    """
    return (
        f"Voice ready — run {run_id}\n\n"
        f"Download MP3 (expires {_TESTVOICE_MP3_URL_EXPIRY_LABEL}):\n{mp3_url}"
    )


def parse_pick_command(text: str) -> Optional[tuple[str, int, int, str]]:
    """Parse a `/pick <run_id> <n> [--duration <seconds>] [--format portrait|landscape]` command (P7-S1, P9-S6).

    Returns (run_id, n, target_duration_seconds, format_track) where n is the 1-based
    idea index. Defaults to 60 s and 'landscape' when flags are absent. Returns None
    for malformed input (missing args, non-integer n, n < 1, or n > _IDEAS_TOP_N).
    """
    stripped = text.strip()
    if not stripped.startswith("/pick "):
        return None
    args = stripped[len("/pick "):].strip()

    # Extract optional --format flag (can appear anywhere)
    args, format_track = _parse_format_flag(args)

    # Extract optional --duration flag from the tail.
    duration = _DEFAULT_DURATION_SECONDS
    dur_match = _DURATION_FLAG_RE.search(args)
    if dur_match:
        try:
            d = int(dur_match.group(1))
            duration = d if d > 0 else _DEFAULT_DURATION_SECONDS
        except ValueError:
            pass
        args = args[: dur_match.start()].strip()

    parts = args.split()
    if len(parts) != 2:
        return None
    run_id_part, n_part = parts
    try:
        n = int(n_part)
    except ValueError:
        return None
    if n < 1 or n > _IDEAS_TOP_N:
        return None
    return (run_id_part, n, duration, format_track)


def format_pick_usage() -> str:
    """Format the reply when `/pick` is sent with missing or invalid arguments (D049, P7-S1)."""
    return f"Usage: /pick <run_id> <n> [--duration <s>] [--format portrait|landscape] — pick idea 1–{_IDEAS_TOP_N} from a prior /ideas run, e.g. /pick abc-123 2 --format landscape"


def format_pick_running(run_id: str, idea_title: str) -> str:
    """Format the immediate ack sent before the background /pick pipeline run starts (D049, P7-S1)."""
    return f'Producing idea #{run_id[-4:]} — "{idea_title}"... this takes ~5–10 minutes.'


def format_unrecognized_command(text: str) -> str:
    """Format the reply for any unrecognized command or message (D049)."""
    return (
        "Sorry, I didn't understand that. Commands:\n"
        "  /ideas <niche> — generate ranked ideas\n"
        "  /pick <run_id> <n> [--duration <s>] [--format portrait|landscape] — produce idea N from a prior /ideas run\n"
        "  /produce <idea title> [--duration <s>] [--format portrait|landscape] — produce a named idea directly\n"
        "  /run <niche> [--duration <s>] [--format portrait|landscape] — full niche-to-video pipeline\n"
        "  /script <idea title> [--duration <s>] — generate script only\n"
        "  /testvoice <run_id> — test voiceover for an existing run"
    )


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
