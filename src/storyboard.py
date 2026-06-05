"""Claude API storyboard generation — calls v0.8 prompt and parses response into storyboard.json."""

import asyncio
import logging
import re
from typing import Optional

import anthropic

from src.config import Settings
from src.exceptions import StoryboardAPIError, StoryboardParseError, StoryboardValidationError
from src.models import (
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    ValidationResult,
    VisualPrompts,
    WordTimestamp,
)
from src.utils.model_router import GENERATE, ModelRouter
from src.validators.storyboard_validator import validate_storyboard

# Fields that operators are permitted to edit via PATCH /runs/{run_id}/storyboard.
_PATCHABLE_FIELDS: set[str] = {"ai_generate_prompt"}

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a production storyboard generator for a faceless, voiceover-driven YouTube Shorts channel.

Format: 30–60 second YouTube Short, 9:16 vertical. Voiceover only. AI-generated visuals + stock footage.

Your job: take a voiceover script and produce a full production storyboard. Output a structured scene-by-scene breakdown. No prose, no commentary — only the storyboard.

═══════════════════════════════════════
GLOBAL OUTPUT (once, at the top)
═══════════════════════════════════════

- subtitle_style: font weight, color, animation style, screen position
- bg_music: mood, tempo, genre ref, instrumentation, dB under VO, swell behavior at CTA
- visual_style: color palette, aesthetic, motion design notes

═══════════════════════════════════════
SCENE FIELDS (every scene)
═══════════════════════════════════════

- scene: sequential number (use 03a / 03b for list sub-scenes)
- clip_type: hard_cut | still_with_motion | animated
- duration_s: derived from VO word count (see rules below)
- voiceover_line: exact portion of VO spoken over this scene — 4–6 words maximum. Short phrase, not a full sentence. Split longer VO lines into separate scenes.
- visual_prompts:
    PRIMARY: STK `3–4 concrete nouns only — no adjectives`
    FALLBACK: STK `1–2 words, core subject only`
    AI_GENERATE if no stock: `cinematic image generation prompt — include shallow depth of field, golden hour lighting or equivalent, cinematic`
- motion_effect: zoom-in | zoom-out | pan-left | pan-right | ken-burns | null
- on_screen_text: exact text string or null
- sfx: specific sound description — never null; if no sound write "silence"
- sfx_timing: on cut | Xs after cut | on spoken word "[word]"

═══════════════════════════════════════
DURATION RULES
═══════════════════════════════════════

Duration is always derived from the word count of the voiceover_line. Never from clip type ceiling.

| Words in VO line      | Duration     |
|-----------------------|--------------|
| List item, 1 word     | 0.3–0.4s     |
| List item, 2–3 words  | 0.5–0.7s     |
| List item, 3–4 words  | 0.8–1.0s     |
| Non-list, 4–6 words   | 1.0–1.5s     |
| Non-list, 7–10 words  | 2.0–2.5s     |
| Non-list, 11–14 words | 3.0–3.5s     |
| 15+ words             | Split into two scenes |

- Maximum silence/padding after VO ends: 0.5s
- Non-list scene minimum: 1.0s
- List item minimum: 0.7s (except single-word items)

Clip type ceilings (hard limits, never exceed):
- hard_cut: ≤1s
- still_with_motion: ≤3s
- animated: ≤4s

═══════════════════════════════════════
TIMESTAMP ALIGNMENT (when word timestamps are provided)
═══════════════════════════════════════

If the user message contains a WORD TIMESTAMPS block, those timings are from the actual
recorded voiceover (Deepgram Nova-2). They are authoritative — use them to set duration_s.

For each scene:
1. Locate the words of voiceover_line in the timestamp list (case-insensitive, ignore punctuation).
2. duration_s = (end_ms of last matched word − start_ms of first matched word) / 1000
3. Round to 2 decimal places. Add at most 0.3s of silence tail for natural phrasing.
4. Never guess or use the word-count table when timestamps are present.
5. If a word cannot be matched, use the word-count table as fallback for that scene only.

The total_duration in SUMMARY must equal the sum of all scene duration_s values.

═══════════════════════════════════════
CLIP TYPE RULES
═══════════════════════════════════════

HARD_CUT
- Emphasis, shock, or list items
- Sub-1s permitted only for list items or deliberate punch cuts
- No motion effect

STILL_WITH_MOTION
- Use when a single frame + movement conveys the full idea
- A photograph could tell the story
- Single mood, place, person, emotion, or establishing shot
- motion_effect is mandatory: zoom-in | zoom-out | pan-left | pan-right | ken-burns

CRITICAL: If clip_type is "still_with_motion", motion_effect MUST be one of: "ken_burns_in", "ken_burns_out", "pan_left", "pan_right". It must never be null. If you have no preference, default to "ken_burns_in".

ANIMATED
- Use only when the concept requires change, transition, or sequence to land
- A photograph cannot tell the story alone
- Use for: transformation (before→after), abstract concepts, cause and effect, metaphors requiring movement
- Never assign animated for visual variety alone
- motion_effect: null

═══════════════════════════════════════
COMMA-LIST RULE
═══════════════════════════════════════

When the VO contains a comma-separated list of items, each item becomes its own hard_cut scene.
- Label sub-scenes: 03a, 03b, 03c
- Duration per item scaled by word count (see table above)
- SFX must be item-specific — never generic
- on_screen_text only if item is 2+ words and adds value

═══════════════════════════════════════
VISUAL PROMPTS RULE
═══════════════════════════════════════

Every scene gets exactly three prompts in a decision hierarchy:
1. PRIMARY: STK — Pexels search string
2. FALLBACK: STK — broader Pexels search if primary returns nothing
3. AI_GENERATE if no stock — Flux/Replicate image generation prompt

The downstream pipeline tries PRIMARY first, then FALLBACK, then generates if neither works.

PRIMARY query rules:
- 3–4 concrete nouns only. No adjectives. No verbs.
- Ask yourself: what physical object would a cameraman point a lens at?
- Pexels is keyword-matched, not semantic. Adjectives reduce recall without improving precision.

FALLBACK query rules:
- 1–2 words. Core subject only. Broadest noun that still covers the scene.

AI_GENERATE rules:
- Describe the subject, composition, and lighting as a camera direction.
- Always include: shallow depth of field, golden hour lighting (or equivalent for the scene mood), cinematic, 9:16 vertical.
- Never use abstract concepts — describe what the camera sees.

Few-shot examples:

  VO: "Homeowners across the country are watching their equity disappear"
  PRIMARY: STK `house equity document calculator`
  FALLBACK: STK `homeowner`
  AI_GENERATE: `Close-up of a homeowner's hands holding house keys over a blurred suburban street, shallow depth of field, golden hour lighting, cinematic 9:16 vertical, photorealistic`

  VO: "Mortgage rates hit a 20-year high last October"
  PRIMARY: STK `mortgage document interest rate`
  FALLBACK: STK `mortgage`
  AI_GENERATE: `Bank document with interest rate figures on a desk, shallow depth of field, warm indoor lighting, cinematic 9:16 vertical, photorealistic`

  VO: "Rents in major cities rose 30% in three years"
  PRIMARY: STK `apartment building city street`
  FALLBACK: STK `apartment`
  AI_GENERATE: `Exterior of a multi-storey apartment building at dusk, urban street, shallow depth of field, golden hour lighting, cinematic 9:16 vertical, photorealistic`

  VO: "First-time buyers are getting squeezed out"
  PRIMARY: STK `young couple house keys`
  FALLBACK: STK `house keys`
  AI_GENERATE: `Young couple standing in front of a suburban house holding keys, shallow depth of field, soft golden hour lighting, cinematic 9:16 vertical, photorealistic`

═══════════════════════════════════════
RHYTHM RULE
═══════════════════════════════════════

Scene count is driven by narrative beats, not a fixed target.
Vary clip types to match emotional arc:
- Opening: establish with still_with_motion
- Tension/list/emphasis: hard_cut sequence
- Concept/transformation: animated
- Resolution/CTA: still_with_motion with ken-burns

Never place the same clip_type more than twice in a row unless it is a deliberate list sequence.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

GLOBAL
subtitle_style: [value]
bg_music: [value]
visual_style: [value]

---

SCENE [N]
clip_type: [value]
duration_s: [value]
voiceover_line: "[value]"
visual_prompts:
  PRIMARY: STK `[value]`
  FALLBACK: STK `[value]`
  AI_GENERATE if no stock: `[value]`
motion_effect: [value]
on_screen_text: [value]
sfx: [value]
sfx_timing: [value]

---

[repeat for all scenes]

SUMMARY
Total scenes: [N]
Total duration: [Xs]
Rhythm: [SM / HC / HC / AN / SM ...]
"""


def _format_timestamps(words: list[WordTimestamp]) -> str:
    """Format a word timestamp list as a compact one-line-per-word block for the Claude prompt."""
    return "\n".join(f'[{w.start_ms}ms–{w.end_ms}ms] "{w.word}"' for w in words)


def _split_script_into_chunks(script: str, max_paragraphs: int = 10) -> list[str]:
    """Split a voiceover script into chunks of at most max_paragraphs paragraphs.

    Splits on blank-line boundaries. Returns [script] when the script fits in one
    chunk (paragraph count ≤ max_paragraphs). The last chunk absorbs any remainder.
    Never cuts mid-sentence because splits happen only at paragraph boundaries.
    """
    paragraphs = re.split(r"\n\s*\n", script.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if len(paragraphs) <= max_paragraphs:
        return [script.strip()]

    chunks = []
    for i in range(0, len(paragraphs), max_paragraphs):
        chunks.append("\n\n".join(paragraphs[i : i + max_paragraphs]))

    return chunks


def _slice_alignment_for_chunk(
    words: list[WordTimestamp],
    chunk_idx: int,
    chunks: list[str],
) -> list[WordTimestamp]:
    """Return the word timestamp slice corresponding to the chunk at chunk_idx.

    Divides the global word list proportionally by each chunk's character count.
    The last chunk always receives any remaining words to avoid truncation.
    Returns an empty list when words is empty or all chunks have zero length.
    """
    if not words or not chunks:
        return []

    total_chars = sum(len(c) for c in chunks)
    if total_chars == 0:
        return []

    cumulative = 0
    for i, chunk in enumerate(chunks):
        start_idx = round(cumulative / total_chars * len(words))
        cumulative += len(chunk)
        if i == len(chunks) - 1:
            end_idx = len(words)
        else:
            end_idx = round(cumulative / total_chars * len(words))

        if i == chunk_idx:
            return words[start_idx:end_idx]

    return []


def _merge_storyboard_chunks(storyboards: list[Storyboard]) -> Storyboard:
    """Merge multiple per-chunk storyboards into one with globally contiguous scene numbers.

    Scene numbers are reassigned as 1, 2, 3 … N across all chunks.
    The GLOBAL block from the first storyboard is preserved.
    SUMMARY is recomputed: total_scenes = N, total_duration_s = sum of all scene durations.
    Raises StoryboardParseError when called with an empty list.
    """
    if not storyboards:
        raise StoryboardParseError("Cannot merge an empty storyboard list")

    if len(storyboards) == 1:
        return storyboards[0]

    all_scenes: list[StoryboardScene] = []
    for sb in storyboards:
        all_scenes.extend(sb.scenes)

    renumbered = [
        scene.model_copy(update={"scene": str(i + 1)})
        for i, scene in enumerate(all_scenes)
    ]

    total_duration = round(sum(s.duration_s for s in renumbered), 2)
    rhythm_parts = [sb.summary.rhythm for sb in storyboards if sb.summary.rhythm]

    summary = StoryboardSummary(
        total_scenes=len(renumbered),
        total_duration_s=total_duration,
        rhythm=" / ".join(rhythm_parts),
    )

    return Storyboard(global_=storyboards[0].global_, scenes=renumbered, summary=summary)


async def generate_storyboard(
    script: str,
    settings: Settings,
    word_timestamps: Optional[list[WordTimestamp]] = None,
) -> tuple[Storyboard, ValidationResult]:
    """
    Call Claude API with v0.8 prompt, parse, then validate with Haiku.

    For long scripts (paragraph count > STORYBOARD_CHUNK_SIZE), splits the script
    into chunks and runs each as a concurrent Claude call via asyncio.gather.
    Results are renumbered and merged before validation.
    Falls back to a single call when the script fits in one chunk.
    Model selection and cost logging go through ModelRouter so ENV overrides apply.
    Returns (storyboard, validation_result). Raises StoryboardValidationError if
    Haiku finds schema violations in the generated storyboard.
    """
    chunks = _split_script_into_chunks(script, max_paragraphs=settings.STORYBOARD_CHUNK_SIZE)
    router = ModelRouter(settings)
    model = router.model_for(GENERATE)

    if len(chunks) == 1:
        raw_text, input_tokens, output_tokens = await _call_claude_api(
            script, settings.ANTHROPIC_API_KEY, model, word_timestamps
        )
        router.log_cost(GENERATE, model, input_tokens, output_tokens)
        storyboard = _parse_storyboard_response(raw_text)
    else:
        api_calls = [
            _call_claude_api(
                chunk,
                settings.ANTHROPIC_API_KEY,
                model,
                _slice_alignment_for_chunk(word_timestamps or [], i, chunks) or None,
            )
            for i, chunk in enumerate(chunks)
        ]
        results = await asyncio.gather(*api_calls)

        chunk_storyboards = []
        for raw_text, in_tok, out_tok in results:
            router.log_cost(GENERATE, model, in_tok, out_tok)
            chunk_storyboards.append(_parse_storyboard_response(raw_text))

        storyboard = _merge_storyboard_chunks(chunk_storyboards)

    validation = await validate_storyboard(storyboard, settings.ANTHROPIC_API_KEY, router=router)
    if not validation.valid:
        error_summary = "; ".join(validation.errors)
        raise StoryboardValidationError(f"Storyboard validation failed: {error_summary}")
    return storyboard, validation


async def _call_claude_api(
    script: str,
    api_key: str,
    model: str,
    word_timestamps: Optional[list[WordTimestamp]] = None,
) -> tuple[str, int, int]:
    """Call Claude API with the v0.8 system prompt.

    Returns (raw_text, input_tokens, output_tokens).
    """
    if word_timestamps:
        ts_block = _format_timestamps(word_timestamps)
        user_content = (
            f"WORD TIMESTAMPS (Deepgram Nova-2 — use these for scene duration_s):\n"
            f"{ts_block}\n\n"
            f"VOICEOVER SCRIPT:\n{script}"
        )
    else:
        user_content = script

    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=8192,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        return message.content[0].text, message.usage.input_tokens, message.usage.output_tokens
    except anthropic.APIError as exc:
        raise StoryboardAPIError(f"Claude API error: {exc}") from exc


def _parse_storyboard_response(text: str) -> Storyboard:
    """
    Parse the Claude text response into a validated Storyboard model.

    Expects sections separated by '---' on its own line. First section is GLOBAL,
    last is SUMMARY, all middle sections are SCENE blocks.
    Raises StoryboardParseError on any failure.
    """
    parts = re.split(r"(?m)^\s*---\s*$", text.strip())
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) < 3:
        logger.error(
            "Storyboard parse failed — raw response (first 500 chars): %s",
            text[:500],
        )
        raise StoryboardParseError(
            f"Expected GLOBAL + at least 1 SCENE + SUMMARY sections, got {len(parts)}"
        )

    try:
        global_ = _parse_global(parts[0])
    except StoryboardParseError:
        raise
    except Exception as exc:
        raise StoryboardParseError(f"Failed to parse GLOBAL block: {exc}") from exc

    scenes = []
    for i, block in enumerate(parts[1:-1]):
        try:
            scenes.append(_parse_scene(block, index=i))
        except StoryboardParseError:
            raise
        except Exception as exc:
            raise StoryboardParseError(f"Failed to parse scene block {i + 1}: {exc}") from exc

    try:
        summary = _parse_summary(parts[-1], scenes=scenes)
    except StoryboardParseError:
        raise
    except Exception as exc:
        raise StoryboardParseError(f"Failed to parse SUMMARY block: {exc}") from exc

    return Storyboard(global_=global_, scenes=scenes, summary=summary)


def _get_field(text: str, field: str, required: bool = True) -> Optional[str]:
    """
    Extract a single-line field value from a storyboard block.

    Tolerates Claude markdown bold formatting (**field:** value) and leading
    bullet/dash characters. Returns None for literal 'null' values or empty
    values. Raises StoryboardParseError only when required=True and the field
    is completely absent.
    """
    # Permit optional ** markdown bold around the field name (Claude quirk)
    match = re.search(
        rf"^[-\s]*\*{{0,2}}{re.escape(field)}\*{{0,2}}:\s*(.+)$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if not match:
        if required:
            logger.error(
                "Missing field '%s' in block (first 300 chars): %s",
                field,
                text[:300],
            )
            raise StoryboardParseError(f"Missing required field '{field}'")
        return None
    value = match.group(1).strip()
    # Strip leading markdown bold markers Claude sometimes leaves in the value
    # e.g. **subtitle_style:** value → captures "** value" → strip to "value"
    value = re.sub(r"^\*+\s*", "", value).strip()
    # Treat bare 'null' or empty-after-strip as absent
    if not value or value.lower() == "null":
        return None
    return value


def _parse_global(block: str) -> StoryboardGlobal:
    """
    Parse the GLOBAL section into a StoryboardGlobal model.

    All three fields are treated as optional metadata — none of them are used
    by the rendering pipeline. Defaults to empty string when Claude omits or
    leaves a field blank.
    """
    return StoryboardGlobal(
        subtitle_style=_get_field(block, "subtitle_style", required=False) or "",
        bg_music=_get_field(block, "bg_music", required=False) or "",
        visual_style=_get_field(block, "visual_style", required=False) or "",
    )


def _extract_vp(pattern: str, block: str) -> str:
    """Run a visual-prompt regex and return the stripped group(1), or ''."""
    m = re.search(pattern, block, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""


def _parse_visual_prompts(block: str) -> VisualPrompts:
    """
    Parse the visual_prompts sub-section (PRIMARY / FALLBACK / AI_GENERATE).

    Tries multiple formats Claude uses:
      1. PRIMARY: STK `value`          (canonical format with backticks)
      2. PRIMARY: STK value            (canonical without backticks)
      3. PRIMARY: `value`              (no STK keyword)
      4. PRIMARY: value                (bare value)
      5. primary_stk: value            (YAML-style field name)

    Defaults to empty string rather than raising — empty prompts fail
    gracefully at asset acquisition rather than crashing the whole pipeline.
    """
    _VP = r"[`\"]?([^`\"\n]+?)[`\"]?\s*$"

    primary = (
        _extract_vp(rf"PRIMARY[:\s]+STK[:\s]+{_VP}", block) or
        _extract_vp(rf"PRIMARY[:\s]+{_VP}", block) or
        _get_field(block, "primary_stk", required=False) or
        ""
    )
    fallback = (
        _extract_vp(rf"FALLBACK[:\s]+STK[:\s]+{_VP}", block) or
        _extract_vp(rf"FALLBACK[:\s]+{_VP}", block) or
        _get_field(block, "fallback_stk", required=False) or
        ""
    )
    ai_gen = (
        _extract_vp(rf"AI_GENERATE[^:\n]*:[:\s]+{_VP}", block) or
        _extract_vp(rf"AI[_\s]GEN(?:ERATE)?[^:\n]*:[:\s]+{_VP}", block) or
        _get_field(block, "ai_generate", required=False) or
        ""
    )

    return VisualPrompts(
        primary_stk=primary,
        fallback_stk=fallback,
        ai_generate=ai_gen,
    )


_VALID_CLIP_TYPES = {"hard_cut", "still_with_motion", "animated"}
_DEFAULT_CLIP_TYPE = "still_with_motion"


def _parse_scene(block: str, index: int = 0) -> StoryboardScene:
    """
    Parse a single SCENE block into a StoryboardScene model.

    All required fields have safe fallbacks so a partially malformed Claude
    response produces a renderable scene rather than a hard failure:
      clip_type    → "still_with_motion"
      duration_s   → 2.0
      voiceover_line → ""
      sfx          → "silence"
      sfx_timing   → "scene_start"
      motion_effect → "zoom_in" when clip_type is "still_with_motion"

    Scene ID must start with a digit (e.g. "1", "3a"). If SCENE has no
    numeric ID — e.g. Claude writes "SCENE" on its own line — we fall back
    to the 1-based block index to avoid capturing a field name as the ID.
    """
    # Require scene ID to start with a digit so we never capture a field
    # name like "visual_style:" when SCENE appears on its own line.
    scene_match = re.search(r"SCENE\s+(\d+\w*)", block, re.IGNORECASE)
    if not scene_match:
        # SCENE keyword exists but no numeric ID — use 1-based block position
        if not re.search(r"\bSCENE\b", block, re.IGNORECASE):
            raise StoryboardParseError(f"No SCENE header found in block: {block[:80]!r}")
        scene_id = str(index + 1)
        logger.warning("SCENE block %d has no numeric ID — assigned '%s'", index + 1, scene_id)
    else:
        scene_id = scene_match.group(1)

    # clip_type — validate; fall back to still_with_motion
    raw_clip = _get_field(block, "clip_type", required=False)
    if raw_clip and raw_clip.lower().replace("-", "_") in _VALID_CLIP_TYPES:
        clip_type = raw_clip.lower().replace("-", "_")
    else:
        if raw_clip:
            logger.warning("Unknown clip_type '%s' in scene %s — defaulting to %s",
                           raw_clip, scene_id, _DEFAULT_CLIP_TYPE)
        else:
            logger.warning("Missing clip_type in scene %s — defaulting to %s",
                           scene_id, _DEFAULT_CLIP_TYPE)
        clip_type = _DEFAULT_CLIP_TYPE

    # duration_s — fall back to 2.0
    dur_raw = _get_field(block, "duration_s", required=False)
    try:
        duration_s = float(dur_raw.rstrip("s").strip()) if dur_raw else 2.0
    except (ValueError, AttributeError):
        logger.warning("Invalid duration_s '%s' in scene %s — defaulting to 2.0", dur_raw, scene_id)
        duration_s = 2.0

    # voiceover_line — fall back to ""
    vo_raw = _get_field(block, "voiceover_line", required=False)
    voiceover_line = vo_raw.strip('"').strip("'") if vo_raw else ""

    visual_prompts = _parse_visual_prompts(block)

    motion_effect_raw = _get_field(block, "motion_effect", required=False)
    # still_with_motion requires a non-null motion_effect for the zoompan filter
    if clip_type == "still_with_motion" and not motion_effect_raw:
        motion_effect_raw = "zoom_in"
        logger.warning("still_with_motion scene %s has no motion_effect — defaulting to zoom_in", scene_id)
    motion_effect = motion_effect_raw

    on_screen_text = _get_field(block, "on_screen_text", required=False)

    # sfx must be non-null; default to "silence"
    sfx_raw = _get_field(block, "sfx", required=False)
    sfx = sfx_raw if sfx_raw else "silence"

    # sfx_timing — default to "scene_start"
    sfx_timing_raw = _get_field(block, "sfx_timing", required=False)
    sfx_timing = sfx_timing_raw if sfx_timing_raw else "scene_start"

    return StoryboardScene(
        scene=scene_id,
        clip_type=clip_type,
        duration_s=duration_s,
        voiceover_line=voiceover_line,
        visual_prompts=visual_prompts,
        motion_effect=motion_effect,
        on_screen_text=on_screen_text,
        sfx=sfx,
        sfx_timing=sfx_timing,
    )


def _parse_summary(block: str, scenes: Optional[list] = None) -> StoryboardSummary:
    """
    Parse the SUMMARY section into a StoryboardSummary model.

    Falls back to computed values from the scene list when Claude omits fields:
      total_scenes   → len(scenes)
      total_duration → sum of scene duration_s values
      rhythm         → ""
    """
    scenes = scenes or []

    scenes_match = re.search(r"Total scenes:\s*(\d+)", block, re.IGNORECASE)
    duration_match = re.search(r"Total duration:[^\d]*([\d.]+)", block, re.IGNORECASE)
    rhythm_match = re.search(r"Rhythm:\s*(.+)$", block, re.IGNORECASE | re.MULTILINE)

    total_scenes = int(scenes_match.group(1)) if scenes_match else len(scenes)
    total_duration_s = float(duration_match.group(1)) if duration_match else sum(
        s.duration_s for s in scenes
    )
    rhythm = rhythm_match.group(1).strip() if rhythm_match else ""

    return StoryboardSummary(
        total_scenes=total_scenes,
        total_duration_s=total_duration_s,
        rhythm=rhythm,
    )


def patch_scene_field(
    run_id: str,
    scene_id: str,
    field: str,
    value: str,
    storage: "R2Client",  # type: ignore[name-defined]  # imported at call site to avoid circular
) -> Storyboard:
    """
    Update a single editable field on one storyboard scene and write back to R2.

    Only fields listed in _PATCHABLE_FIELDS are accepted.  Raises ValueError on
    unknown field, StoryboardParseError on unknown scene_id.
    """
    if field not in _PATCHABLE_FIELDS:
        raise ValueError(f"Field '{field}' is not patchable; allowed: {sorted(_PATCHABLE_FIELDS)}")

    storyboard_key = f"runs/{run_id}/storyboard.json"
    data = storage.get_json(storyboard_key)
    storyboard = Storyboard.model_validate(data)

    for scene in storyboard.scenes:
        if scene.scene == scene_id:
            if field == "ai_generate_prompt":
                scene.visual_prompts.ai_generate = value
            break
    else:
        raise StoryboardParseError(f"Scene '{scene_id}' not found in storyboard for run '{run_id}'")

    storage.upload_json(
        storyboard_key,
        storyboard.model_dump(by_alias=True, mode="json"),
    )
    return storyboard
