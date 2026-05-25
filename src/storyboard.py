"""Claude API storyboard generation — calls v0.5 prompt and parses response into storyboard.json."""

import logging
import re
from typing import Optional

import anthropic

from src.config import Settings
from src.exceptions import StoryboardAPIError, StoryboardParseError
from src.models import (
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
)

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
- voiceover_line: exact portion of VO spoken over this scene
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


async def generate_storyboard(script: str, settings: Settings) -> Storyboard:
    """Call Claude API with v0.5 prompt, parse and validate into a Storyboard."""
    raw_text = await _call_claude_api(script, settings.ANTHROPIC_API_KEY, settings.CLAUDE_MODEL)
    return _parse_storyboard_response(raw_text)


async def _call_claude_api(script: str, api_key: str, model: str) -> str:
    """Call Claude API with the v0.4 system prompt. Returns the raw text response."""
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": script}],
        )
        return message.content[0].text
    except anthropic.APIError as exc:
        raise StoryboardAPIError(f"Claude API error: {exc}") from exc


def _parse_storyboard_response(text: str) -> Storyboard:
    """
    Parse the Claude text response into a validated Storyboard model.

    Expects sections separated by '---'. First section is GLOBAL, last is SUMMARY,
    all middle sections are SCENE blocks. Raises StoryboardParseError on any failure.
    """
    parts = re.split(r"\n\s*---\s*\n", text.strip())
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) < 3:
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
            scenes.append(_parse_scene(block))
        except StoryboardParseError:
            raise
        except Exception as exc:
            raise StoryboardParseError(f"Failed to parse scene block {i + 1}: {exc}") from exc

    try:
        summary = _parse_summary(parts[-1])
    except StoryboardParseError:
        raise
    except Exception as exc:
        raise StoryboardParseError(f"Failed to parse SUMMARY block: {exc}") from exc

    return Storyboard(global_=global_, scenes=scenes, summary=summary)


def _get_field(text: str, field: str, required: bool = True) -> Optional[str]:
    """Extract a single-line field value; returns None for literal 'null' values."""
    match = re.search(rf"^[-\s]*{re.escape(field)}:\s*(.+)$", text, re.MULTILINE)
    if not match:
        if required:
            raise StoryboardParseError(f"Missing required field '{field}'")
        return None
    value = match.group(1).strip()
    return None if value.lower() == "null" else value


def _parse_global(block: str) -> StoryboardGlobal:
    """Parse the GLOBAL section into a StoryboardGlobal model."""
    return StoryboardGlobal(
        subtitle_style=_get_field(block, "subtitle_style"),
        bg_music=_get_field(block, "bg_music"),
        visual_style=_get_field(block, "visual_style"),
    )


def _parse_visual_prompts(block: str) -> VisualPrompts:
    """Parse the visual_prompts sub-section (PRIMARY / FALLBACK / AI_GENERATE)."""
    primary = re.search(r"PRIMARY:\s*STK\s*`([^`]+)`", block)
    fallback = re.search(r"FALLBACK:\s*STK\s*`([^`]+)`", block)
    ai_gen = re.search(r"AI_GENERATE[^:]*:\s*`([^`]+)`", block)

    if not primary:
        raise StoryboardParseError("Missing PRIMARY visual prompt in scene")
    if not fallback:
        raise StoryboardParseError("Missing FALLBACK visual prompt in scene")
    if not ai_gen:
        raise StoryboardParseError("Missing AI_GENERATE visual prompt in scene")

    return VisualPrompts(
        primary_stk=primary.group(1).strip(),
        fallback_stk=fallback.group(1).strip(),
        ai_generate=ai_gen.group(1).strip(),
    )


def _parse_scene(block: str) -> StoryboardScene:
    """Parse a single SCENE block into a StoryboardScene model."""
    scene_match = re.search(r"SCENE\s+(\S+)", block, re.IGNORECASE)
    if not scene_match:
        raise StoryboardParseError(f"No SCENE header found in block: {block[:80]!r}")
    scene_id = scene_match.group(1)

    clip_type = _get_field(block, "clip_type")

    dur_raw = _get_field(block, "duration_s")
    try:
        duration_s = float(dur_raw.rstrip("s").strip())
    except (ValueError, AttributeError) as exc:
        raise StoryboardParseError(f"Invalid duration_s value: '{dur_raw}'") from exc

    vo_raw = _get_field(block, "voiceover_line")
    voiceover_line = vo_raw.strip('"').strip("'") if vo_raw else ""

    visual_prompts = _parse_visual_prompts(block)

    motion_effect = _get_field(block, "motion_effect", required=False)
    on_screen_text = _get_field(block, "on_screen_text", required=False)
    sfx = _get_field(block, "sfx")
    sfx_timing = _get_field(block, "sfx_timing")

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


def _parse_summary(block: str) -> StoryboardSummary:
    """Parse the SUMMARY section into a StoryboardSummary model."""
    scenes_match = re.search(r"Total scenes:\s*(\d+)", block, re.IGNORECASE)
    duration_match = re.search(r"Total duration:[^\d]*([\d.]+)", block, re.IGNORECASE)
    rhythm_match = re.search(r"Rhythm:\s*(.+)$", block, re.IGNORECASE | re.MULTILINE)

    if not scenes_match:
        raise StoryboardParseError("Missing 'Total scenes' in SUMMARY")
    if not duration_match:
        raise StoryboardParseError("Missing 'Total duration' in SUMMARY")
    if not rhythm_match:
        raise StoryboardParseError("Missing 'Rhythm' in SUMMARY")

    return StoryboardSummary(
        total_scenes=int(scenes_match.group(1)),
        total_duration_s=float(duration_match.group(1)),
        rhythm=rhythm_match.group(1).strip(),
    )
