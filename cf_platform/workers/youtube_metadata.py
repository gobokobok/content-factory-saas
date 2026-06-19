"""YouTube Metadata worker (P7-S2) — Script → title + description + tags.

Single Haiku call. Reads the terminal `script` artifact from the idea→script
block and generates YouTube-optimised metadata for the finished Short.

Minimal schema: title (≤70 chars), description (≤500 chars), tags (list[str] ≤15).
Title and description are hard-truncated at their limits if Claude overshoots;
tags list is capped at 15 items.

Prompt ported and simplified from src/metadata_generator.py (D047 — no import from src/).
"""

import json
import logging
import re
from datetime import datetime, timezone

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_packager import ScriptArtifact

logger = logging.getLogger(__name__)

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MAX_TITLE_CHARS = 70
_MAX_DESCRIPTION_CHARS = 500
_MAX_TAGS = 15

YOUTUBE_METADATA_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",
    model=_HAIKU_MODEL,
    sampling_params={"max_tokens": 512},
)

_SYSTEM_PROMPT = """\
You are a YouTube Shorts content strategist. Given a video script, generate publishing \
metadata optimised for discoverability and click-through rate.

Return ONLY a valid JSON object — no prose, no markdown fences, no extra keys.

Required schema:
{
  "title": "YouTube title (max 70 chars, hook-first, use numbers when possible)",
  "description": "YouTube description (max 500 chars). First sentence is the hook. Hashtags at end.",
  "tags": ["tag1", "tag2", "..."]
}

Rules:
- title: front-load the most compelling fact or tension. Hard limit: 70 characters.
- description: 2–3 sentences. End with 3–5 relevant hashtags (e.g. #HousingMarket).
- tags: 10–15 short keyword phrases. No # prefix. Mix broad and niche terms.
- All content is factual and data-driven — no sensationalism.
"""


def _extract_json(text: str) -> dict:
    """Extract and parse a JSON object from Claude's response, stripping markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    for candidate in (cleaned, re.search(r"\{.*\}", cleaned, re.DOTALL)):
        if candidate is None:
            continue
        raw = candidate if isinstance(candidate, str) else candidate.group(0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"Could not extract JSON from response: {text[:300]!r}")


class YoutubeMetadataArtifact(BaseModel):
    """Terminal artifact of the youtube_metadata worker."""

    title: str        # ≤70 chars
    description: str  # ≤500 chars
    tags: list[str]   # ≤15 items
    generated_at: datetime


def build_youtube_metadata_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Build the youtube_metadata worker node.

    Reads state.artifacts['script'] → ScriptArtifact → one Haiku call → YoutubeMetadataArtifact.
    Title is hard-truncated to 70 chars; description to 500; tags capped at 15.
    """

    async def _worker(state: StageState) -> WorkerOutput:
        """Generate YouTube metadata from the script artifact."""
        script_key = state.artifacts["script"]
        _, script_body = await read_artifact(storage, script_key)
        script_artifact = ScriptArtifact.model_validate(script_body)

        niche = state.inputs.get("niche", "")
        niche_line = f"\nCHANNEL NICHE: {niche}" if niche else ""
        user_message = (
            f"IDEA TITLE: {script_artifact.idea_title}"
            f"{niche_line}"
            f"\n\nSCRIPT:\n{script_artifact.script}"
        )

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        message = await client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=512,
            system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_message}],
        )

        data = _extract_json(message.content[0].text)

        title = str(data.get("title", ""))[:_MAX_TITLE_CHARS]
        description = str(data.get("description", ""))[:_MAX_DESCRIPTION_CHARS]
        tags = [str(t) for t in data.get("tags", [])][:_MAX_TAGS]

        artifact = YoutubeMetadataArtifact(
            title=title,
            description=description,
            tags=tags,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
