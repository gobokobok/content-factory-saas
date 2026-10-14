"""Write the image prompt for one animation scene (P-LITE, D117).

A scene made by splitting another has no image prompt, and re-creating the whole
storyboard would re-cut every scene. This asks the same Visual Director that wrote
the storyboard (animation_storyboard_worker) for ONE scene: its concept, shot and
image prompt, written against the run's continuity bible and its neighbours so the
shot sequence still varies.

The director's own rules are reused word for word — sections 2 (visual concept),
5 (shot planning), 6 (narration fit) and 7 (the image prompt) of its system prompt —
so a prompt written here follows the same guidelines as one written with the
storyboard. Pure with respect to storage: takes the storyboard, returns the result.
"""

import json
import logging
import re
from dataclasses import dataclass

import anthropic

from cf_platform.workers.animation_storyboard_worker import (
    _ANIMATION_EFFORT,
    _ANIMATION_MODEL,
    _ANIMATION_SYSTEM_PROMPT,
    _FORMAT_PHRASE,
)
from src.models import Storyboard

logger = logging.getLogger(__name__)

SCENE_PROMPT_VERSION = "sp-v0.1"
_MAX_TOKENS = 16000
_SHOT_SIZES = ("extreme wide", "wide", "medium", "close-up", "extreme close-up")
_SECTION_RULE = "═══════════════════════════════════════"
# The director's sections that govern a single scene's image.
_REUSED_SECTIONS = ("2. VISUAL CONCEPT", "5. SHOT PLANNING AND RHYTHM", "6. NARRATION FIT AND FACTUAL ACCURACY", "7. THE IMAGE PROMPT")


class ScenePromptError(ValueError):
    """Raised when no usable prompt came back; the message is safe to show the user."""


@dataclass(frozen=True)
class ScenePrompt:
    """What the director wrote for one scene."""

    ai_prompt: str
    entities: list[str]
    visual_concept: str = ""
    shot_size: str = ""
    shot_angle: str = ""


def director_section(title: str) -> str:
    """One numbered section of the Visual Director's system prompt, heading included.

    Raises ValueError when the section is missing — a renamed heading must fail the
    tests, not quietly drop a rule from every prompt.
    """
    heading = f"{_SECTION_RULE}\n{title}\n{_SECTION_RULE}\n"
    start = _ANIMATION_SYSTEM_PROMPT.index(heading)
    end = _ANIMATION_SYSTEM_PROMPT.find(f"\n{_SECTION_RULE}\n", start + len(heading))
    return _ANIMATION_SYSTEM_PROMPT[start:end if end != -1 else None].strip()


def scene_prompt_system() -> str:
    """The system prompt: the director's role, its single-scene rules and the answer format."""
    rules = "\n\n".join(director_section(title) for title in _REUSED_SECTIONS)
    return (
        "You are the Visual Director who planned this storyboard for a faceless, voiceover-driven video "
        "made entirely from generated illustrations. One scene has no image yet — usually because it was "
        "just split from another. Plan that ONE scene the way you planned the others: same rules, same "
        "continuity bible, and a shot that fits between its neighbours.\n\n"
        f"{rules}\n\n"
        f"{_SECTION_RULE}\nFOR THIS SCENE\n{_SECTION_RULE}\n\n"
        "- Use only the continuity entries you are given. Do not invent a new character, prop or setting; "
        "a scene does not need a person. List in entities the ids of the entries the image shows.\n"
        "- Differ from the scene before and the scene after in at least two shot dimensions unless the "
        "narration gives a reason not to.\n"
        "- Support this scene's own words; the other scenes are context only.\n\n"
        "Output ONLY a valid JSON object, no prose, no markdown fences:\n"
        '{"visual_concept": "...", "shot": {"size": "...", "angle": "..."}, "entities": ["id"], "ai_prompt": "..."}'
    )


def build_scene_prompt_message(storyboard: Storyboard, scene_id: str, master_style: str, format_track: str) -> str:
    """The user message: format, style, bible, every scene's words, the neighbours' shots, the target."""
    scenes = storyboard.scenes
    index = next((i for i, s in enumerate(scenes) if str(s.scene) == scene_id), None)
    if index is None:
        raise ScenePromptError(f"Scene {scene_id} is not in the storyboard.")
    style = master_style.strip() or "None given. Choose images that work in any consistent illustration style."
    bible = "\n".join(
        f'- id "{e.id}" ({e.kind}) — {e.name}: {e.description}' for e in storyboard.continuity
    ) or "- (none: use no entities)"
    lines = []
    for i, s in enumerate(scenes):
        marker = "  <-- THIS SCENE" if i == index else ""
        lines.append(f"{i + 1}. \"{s.voiceover_line}\"{marker}")
    neighbours = []
    for label, j in (("Scene before", index - 1), ("Scene after", index + 1)):
        if 0 <= j < len(scenes):
            s = scenes[j]
            shot = " · ".join(x for x in (s.shot.size if s.shot else "", s.shot.angle if s.shot else "") if x)
            neighbours.append(
                f"{label} ({j + 1}): shot {shot or 'unknown'}; entities {s.entities or []}; "
                f"prompt: {s.ai_prompt or '(none yet)'}"
            )
    target = scenes[index]
    return (
        f"FORMAT: {_FORMAT_PHRASE.get(format_track, _FORMAT_PHRASE['portrait'])}. Compose for this frame; "
        "do not mention it in ai_prompt.\n\n"
        "MASTER STYLE (context only — it is appended to every image in code; never repeat it):\n"
        f"{style}\n\n"
        f"CONTINUITY BIBLE (refer to an entry by its name; its description is appended in code):\n{bible}\n\n"
        f"THE NARRATION, SCENE BY SCENE:\n" + "\n".join(lines) + "\n\n"
        + ("\n".join(neighbours) + "\n\n" if neighbours else "")
        + f"WRITE SCENE {index + 1}: \"{target.voiceover_line}\" ({target.duration_s:.1f} s)."
    )


def parse_scene_prompt(raw_text: str, storyboard: Storyboard) -> ScenePrompt:
    """Read the model's JSON answer; entities are kept only when they are in the bible."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if start != -1 and end > start else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise ScenePromptError("The director's answer could not be read. Try again.")
    prompt = str(data.get("ai_prompt") or "").strip()
    if not prompt:
        raise ScenePromptError("The director returned no image prompt. Try again.")
    known = {e.id for e in storyboard.continuity}
    entities: list[str] = []
    for raw in data.get("entities") or []:
        entity_id = str(raw).strip()
        if entity_id in known and entity_id not in entities:
            entities.append(entity_id)
    shot = data.get("shot") if isinstance(data.get("shot"), dict) else {}
    size = str(shot.get("size") or "").strip().lower()
    return ScenePrompt(
        ai_prompt=prompt,
        entities=entities,
        visual_concept=str(data.get("visual_concept") or "").strip(),
        shot_size=size if size in _SHOT_SIZES else "",
        shot_angle=str(shot.get("angle") or "").strip().lower(),
    )


async def request_scene_prompt(system_prompt: str, user_content: str, api_key: str) -> str:
    """Call the director's model once and return its text answer (thinking blocks are skipped)."""
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=300.0, max_retries=1)
    message = await client.messages.create(
        model=_ANIMATION_MODEL,
        max_tokens=_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": _ANIMATION_EFFORT},
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    if message.stop_reason == "refusal":
        raise ScenePromptError("The director declined to write a prompt for this scene.")
    if message.stop_reason == "max_tokens":
        raise ScenePromptError("The director's answer was cut off. Try again.")
    return "".join(block.text for block in message.content if block.type == "text")


async def write_scene_prompt(
    storyboard: Storyboard,
    scene_id: str,
    api_key: str,
    *,
    master_style: str = "",
    format_track: str = "portrait",
) -> ScenePrompt:
    """Ask the Visual Director for one scene's concept, shot and image prompt.

    Raises ScenePromptError for a scene that is not in the storyboard, a missing
    key, a refusal, or an answer without a prompt.
    """
    if not api_key:
        raise ScenePromptError("The director is not configured: ANTHROPIC_API_KEY is not set.")
    user_content = build_scene_prompt_message(storyboard, scene_id, master_style, format_track)
    try:
        raw = await request_scene_prompt(scene_prompt_system(), user_content, api_key)
    except anthropic.APIError as exc:
        logger.error("Scene prompt request failed for scene %s: %s", scene_id, type(exc).__name__)
        raise ScenePromptError("The director could not be reached. Try again.") from exc
    result = parse_scene_prompt(raw, storyboard)
    logger.info("Scene prompt written for scene %s (%d entities, prompt %s)", scene_id, len(result.entities), SCENE_PROMPT_VERSION)
    return result
