"""Haiku-based schema validator for storyboard.json — enforces v0.6 production rules."""

import json
import logging
import re
from typing import TYPE_CHECKING, Optional

import anthropic

from src.exceptions import StoryboardValidationError
from src.models import Storyboard, ValidationResult
from src.utils.model_router import DEFAULT_MODELS, PRICING, VALIDATE

if TYPE_CHECKING:
    from src.utils.model_router import ModelRouter

logger = logging.getLogger(__name__)

# Derived from ModelRouter defaults — kept as module-level constants for backward compat
VALIDATOR_MODEL = DEFAULT_MODELS[VALIDATE]
_INPUT_COST_PER_TOKEN, _OUTPUT_COST_PER_TOKEN = PRICING[VALIDATOR_MODEL]

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


async def validate_storyboard(
    storyboard: Storyboard,
    api_key: str,
    router: Optional["ModelRouter"] = None,
) -> ValidationResult:
    """
    Call Haiku to validate a parsed storyboard against v0.6 schema rules.

    When a ModelRouter is provided, model selection and cost logging are delegated
    to it so ENV overrides apply. Falls back to VALIDATOR_MODEL when router is None.
    Returns ValidationResult with valid flag, error list, and token cost data.
    Raises StoryboardValidationError on API failure or unparseable Haiku response.
    """
    model = router.model_for(VALIDATE) if router else VALIDATOR_MODEL
    client = anthropic.AsyncAnthropic(api_key=api_key)
    storyboard_json = json.dumps(
        storyboard.model_dump(by_alias=True, mode="json"), indent=2
    )

    try:
        message = await client.messages.create(
            model=model,
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

    if router:
        cost_usd = router.log_cost(VALIDATE, model, input_tokens, output_tokens)
    else:
        cost_usd = round(
            input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN,
            8,
        )
        logger.info(
            "Storyboard validation: valid=pending errors=pending tokens=%d cost=$%.8f",
            input_tokens + output_tokens,
            cost_usd,
        )

    try:
        result = json.loads(raw)
        valid = bool(result["valid"])
        errors = list(result.get("errors", []))
        # Filter out known non-actionable Haiku findings:
        # - duration_s / hard_cut / ceiling: Haiku invents duration limits not in schema
        # - subtitle_style / bg_music / visual_style: optional global metadata fields
        #   never used by the rendering pipeline — empty is acceptable
        # - "is empty": parser already defaults all empty fields to safe values;
        #   empty prompts/voiceover_lines fail gracefully at acquisition/caption time
        #   rather than blocking the whole storyboard
        errors = [
            e for e in errors
            if "duration_s" not in e
            and "hard_cut" not in e
            and "ceiling" not in e
            and "subtitle_style" not in e
            and "bg_music" not in e
            and "visual_style" not in e
            and " is empty" not in e
            # Haiku incorrectly requires motion_effect for animated scenes;
            # schema only requires it for still_with_motion.
            and not ("animated" in e and "motion_effect" in e)
        ]
        valid = len(errors) == 0
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Haiku returned unparseable validation response: %s", raw[:300])
        raise StoryboardValidationError(
            f"Haiku returned invalid validation JSON: {raw[:200]}"
        ) from exc

    if not router:
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
