"""Run log summarizer — calls Haiku to generate human-readable run_log.txt."""

import json
import logging

from anthropic import Anthropic

from src.exceptions import StorageError
from src.storage import R2Client

logger = logging.getLogger(__name__)

HAIKU_MODEL = "claude-haiku-4-5-20251001"

_SYSTEM_PROMPT = (
    "You are a content pipeline monitor. Given run_log.json data, write a concise "
    "plain-text summary of the pipeline status.\n\n"
    "For each step write exactly one line:\n"
    "  Complete  →  ✓ [Step Label]: Complete\n"
    "  Failed    →  ✗ [Step Label]: Failed — [brief reason from error field]\n"
    "  Pending   →  ○ [Step Label]: Pending\n\n"
    "Step label map: storyboard→Storyboard, asset_manifest→Asset Manifest, "
    "asset_acquisition→Asset Acquisition, alignment→Alignment, "
    "ffmpeg_script→FFmpeg Script, render→Render.\n\n"
    "Output only the step lines. No preamble, no trailing notes."
)


def generate_run_log_summary(run_log_data: dict, api_key: str) -> str:
    """Call Haiku with run_log.json content and return a plain-text summary string."""
    client = Anthropic(api_key=api_key)
    log_text = json.dumps(run_log_data, indent=2)
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Summarise this run log:\n\n{log_text}"}],
    )
    return response.content[0].text.strip()


def write_run_log_summary(run_id: str, storage: R2Client, api_key: str) -> None:
    """Read run_log.json, call Haiku for a summary, and write run_log.txt to R2.

    Fully non-fatal — all errors are caught and logged as warnings so no
    pipeline step is ever blocked by a summarizer failure.
    """
    try:
        run_log_data = storage.get_json(f"runs/{run_id}/run_log.json")
        summary = generate_run_log_summary(run_log_data, api_key)
        storage.upload_text(f"runs/{run_id}/run_log.txt", summary)
        logger.info("run_log.txt written: run=%s chars=%d", run_id, len(summary))
    except StorageError as exc:
        logger.warning("run_log.txt skipped (storage error): run=%s error=%s", run_id, exc)
    except Exception as exc:
        logger.warning("run_log.txt skipped: run=%s error=%s", run_id, exc)
