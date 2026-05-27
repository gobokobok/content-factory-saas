"""Haiku-based schema validator for storyboard.json — enforces v0.6 production rules."""

import json
import logging
import re

import anthropic

from src.exceptions import StoryboardValidationError
from src.models import Storyboard, ValidationResult

logger = logging.getLogger(__name__)

VALIDATOR_MODEL = "claude-haiku-4-5-20251001"

# Haiku 4.5 pricing per token (USD) — used for per-run cost logging
_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000

VALIDATION_SYSTEM_PROMPT = """\
You are a schema validator for storyboard.json files produced by a YouTube Shorts production pipeline.

Validate the given storyboard JSON against these rules and return ONLY valid JSON — no prose, no explanation.

IMPORTANT: Do NOT validate duration_s values. Any positive duration_s is valid regardless of clip_type. Do not invent duration limits, ceilings, or minimums that are not listed below.

RULES:
1. Global block must contain non-empty subtitle_style, bg_music, and visual_style.
2. Every scene must have a non-empty sfx field. If no sound, the value must be "silence" — never null.
3. Every scene must have a non-empty sfx_timing field.
4. clip_type must be exactly one of: hard_cut, still_with_motion, animated.
5. motion_effect is required (non-null) ONLY when clip_type is "still_with_motion". For all other clip_type values, motion_effect may be null.
6. Every scene must have all three visual prompts: primary_stk, fallback_stk, and ai_generate — all non-empty.
7. Every scene must have a non-empty voiceover_line.

Do NOT report errors for duration_s under any circumstances.

OUTPUT FORMAT — return exactly this JSON and nothing else:
{"valid": true, "errors": []}
or
{"valid": false, "errors": ["scene 3: sfx is null", "scene 4: still_with_motion scene has null motion_effect"]}
"""


async def validate_storyboard(storyboard: Storyboard, api_key: str) -> ValidationResult:
    """
    Call Haiku to validate a parsed storyboard against v0.6 schema rules.

    Returns ValidationResult with valid flag, error list, and token cost data.
    Raises StoryboardValidationError on API failure or unparseable Haiku response.
    """
    client = anthropic.AsyncAnthropic(api_key=api_key)
    storyboard_json = json.dumps(
        storyboard.model_dump(by_alias=True, mode="json"), indent=2
    )

    try:
        message = await client.messages.create(
            model=VALIDATOR_MODEL,
            max_tokens=1024,
            system=VALIDATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": storyboard_json}],
        )
    except anthropic.APIError as exc:
        raise StoryboardValidationError(f"Haiku validation API error: {exc}") from exc

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
        raw = raw.strip()
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = round(
        input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN,
        8,
    )

    try:
        result = json.loads(raw)
        valid = bool(result["valid"])
        errors = list(result.get("errors", []))
        # Filter out any duration_s errors — Haiku hallucinates duration limits not in schema
        errors = [e for e in errors if "duration_s" not in e and "hard_cut" not in e and "ceiling" not in e]
        valid = len(errors) == 0
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Haiku returned unparseable validation response: %s", raw[:300])
        raise StoryboardValidationError(
            f"Haiku returned invalid validation JSON: {raw[:200]}"
        ) from exc

    logger.info(
        "Storyboard validation: valid=%s errors=%d tokens=%d cost=$%.8f",
        valid,
        len(errors),
        input_tokens + output_tokens,
        cost_usd,
    )

    return ValidationResult(
        valid=valid,
        errors=errors,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
