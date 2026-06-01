"""Claude Haiku publishing metadata generator — called after render completes."""

import json
import logging
import re

import anthropic

from src.exceptions import MetadataError
from src.models import PublishingMetadata, Storyboard
from src.utils.model_router import TRANSFORM, ModelRouter

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a social media content strategist specializing in YouTube Shorts and Instagram Reels \
about economics and personal finance. Your task: given a project name and video storyboard, \
generate publishing metadata optimized for discoverability.

Return ONLY a valid JSON object — no prose, no markdown fences, no extra keys.

Required schema:
{
  "title": "Primary YouTube title (max 100 chars, hook-first, curiosity-driven)",
  "alt_titles": ["Alternative title 1 (max 100 chars)", "Alternative title 2 (max 100 chars)"],
  "youtube_description": "2–3 sentence YouTube description. First sentence is the hook. Include call-to-action at end.",
  "instagram_description": "1–2 sentence Instagram caption. Conversational tone. End with 1 emoji.",
  "hashtags": ["hashtag1", "hashtag2", "..."],
  "seo_tags": ["tag1", "tag2", "..."]
}

Rules:
- title and alt_titles: front-load the most compelling fact or tension. Use numbers when possible.
- hashtags: 8–12 items. Mix broad (#realestate) and niche (#housingcrisis). No # prefix in values.
- seo_tags: 10–15 short keyword phrases for YouTube tags. No # prefix.
- All content is factual and non-sensational — this channel values data accuracy.
"""


def _extract_json(text: str) -> dict:
    """
    Extract and parse a JSON object from Claude's response text.

    Strips optional markdown code fences before parsing.
    Raises MetadataError if no valid JSON object is found.
    """
    # Strip ```json ... ``` or ``` ... ``` fences Claude sometimes emits
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    # Try direct parse first; then try to extract the first {...} block
    for candidate in (cleaned, re.search(r"\{.*\}", cleaned, re.DOTALL)):
        if candidate is None:
            continue
        raw = candidate if isinstance(candidate, str) else candidate.group(0)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            continue

    raise MetadataError(f"Could not extract JSON from Claude response: {text[:300]!r}")


def _build_user_message(project_name: str, storyboard: Storyboard) -> str:
    """Build the user message containing project name and voiceover script."""
    vo_lines = "\n".join(
        f"Scene {s.scene}: {s.voiceover_line}" for s in storyboard.scenes if s.voiceover_line
    )
    visual_style = storyboard.global_.visual_style
    return (
        f"PROJECT NAME: {project_name}\n\n"
        f"VISUAL STYLE: {visual_style}\n\n"
        f"VOICEOVER SCRIPT (scene by scene):\n{vo_lines}"
    )


async def generate_metadata(
    project_name: str,
    storyboard: Storyboard,
    api_key: str,
    router: ModelRouter,
) -> tuple[PublishingMetadata, int, int, float]:
    """
    Call Claude Haiku to generate publishing metadata for a completed video.

    Returns (PublishingMetadata, input_tokens, output_tokens, cost_usd).
    Raises MetadataError on API failure or unparseable response.
    """
    model = router.model_for(TRANSFORM)
    client = anthropic.AsyncAnthropic(api_key=api_key)
    user_message = _build_user_message(project_name, storyboard)

    try:
        message = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
    except anthropic.APIError as exc:
        raise MetadataError(f"Claude API error during metadata generation: {exc}") from exc

    raw_text = message.content[0].text
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = router.log_cost(TRANSFORM, model, input_tokens, output_tokens)

    data = _extract_json(raw_text)

    try:
        metadata = PublishingMetadata.model_validate(data)
    except Exception as exc:
        raise MetadataError(f"Metadata schema validation failed: {exc}") from exc

    return metadata, input_tokens, output_tokens, cost_usd
