"""AnimationStoryboardWorker (P-AN1-S2, D108) — script + voice timing → verified_storyboard.

The second storyboard path. A run whose `visual_mode` is `ai_animation` gets its
storyboard from this worker instead of `storyboard_worker`: every scene is a
generated image, and the storyboard carries a continuity bible (recurring
characters, props and settings).

One model call per run. The prompt adapts the operator's Visual Director v4.1
(narrative analysis, concept development, continuity bible, shot planning,
narration fit, prompt structure) to this pipeline's contracts:

- **Timing** is the existing word-index contract: the model returns
  `start_word` / `end_word`, Python derives every duration from the voiceover.
- **Output is JSON.** `ai_prompt` holds only the scene-specific description; the
  bible text, the fixed lines, the master style and the aspect phrase are added in
  code at generation time (cf_platform/core/ai_images.py).

Not to be confused with `visual_director_worker` (P11), which plans stock shots
for an existing storyboard and is not used here.

Steps:
  1. Generate (Sonnet 5.5, adaptive thinking) — JSON with `continuity` and scenes.
  2. Validate (deterministic) — contiguous word spans, bible ids resolve, motion
     vocabulary, scenes over the limit are flagged, never split.
  3. Emit the same `verified_storyboard` artifact type as the stock worker.

There is no review pass: the stock reviewer patches stock queries and render
options, neither of which applies to generated images.
"""

import logging
import re
from datetime import UTC, datetime

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.sfx_library import SFX_LIBRARY, sfx_vocab_prompt_line
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.storyboard_worker import (
    VerifiedStoryboardArtifact,
    _apply_patches_and_render_options,
    _asset_tier_to_clip_type,
    _assign_asset_tier,
    _extract_json_object,
    _format_indexed_timestamps,
    _normalize_deepgram_words_with_display,
    _reify_scene,
    _sanitize_storyboard_data,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
from src.models import (
    ANIMATION_MODE,
    CONTINUITY_KINDS,
    MOTION_EFFECTS,
    SCENE_FLAG_NEEDS_PROMPT,
    SCENE_FLAG_TOO_LONG,
    Storyboard,
    normalize_motion_effect,
)

logger = logging.getLogger(__name__)

ANIMATION_STORYBOARD_PROMPT_VERSION = "an-v0.1"

# The model the operator validated the look with (D108). Thinking is adaptive;
# effort is the only depth control on this model.
_ANIMATION_MODEL = "claude-sonnet-5-5"
_ANIMATION_EFFORT = "high"
_ANIMATION_MAX_TOKENS = 64000

ANIMATION_STORYBOARD_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version=ANIMATION_STORYBOARD_PROMPT_VERSION,
    prompt="",
    model=_ANIMATION_MODEL,
    sampling_params={
        "max_tokens": _ANIMATION_MAX_TOKENS,
        "thinking": "adaptive",
        "effort": _ANIMATION_EFFORT,
    },
)

# Scene length in Animation mode, both formats (Visual Director v4.1 §4.1).
ANIMATION_MIN_SCENE_S = 1.0
ANIMATION_MAX_SCENE_S = 5.0
# Word timestamps end where the word ends, so a scene the model sized to exactly
# the limit can measure a few milliseconds over it.
_MAX_SCENE_TOLERANCE_S = 0.05

_FORMAT_PHRASE = {"portrait": "Vertical 9:16", "landscape": "Horizontal 16:9"}
_SFX_VOCAB_SENTINEL = "SFX_VOCAB_PLACEHOLDER"
_MOTION_VOCAB_SENTINEL = "MOTION_VOCAB_PLACEHOLDER"

_ANIMATION_SYSTEM_PROMPT = """\
You are an expert Visual Director, Storyboard Artist and Editor for faceless,
voiceover-driven videos made entirely from generated illustrations.

You are given a finished narration as an indexed word list with its real timing,
the master style every image will be rendered in, and the frame format. Turn the
narration into a production-ready storyboard. You direct the viewer's visual
experience; you do not merely illustrate the words.

Priorities, in order:
1. Narrative clarity and visual impact.
2. Factual accuracy.
3. Visual continuity.
4. Shot variety and editorial rhythm.
5. Production feasibility.

Output ONLY a valid JSON object in the format at the end. No prose, no markdown
fences, no extra keys.

═══════════════════════════════════════
1. NARRATIVE ANALYSIS
═══════════════════════════════════════

Analyse the whole narration before planning any scene. Identify the beats that are
actually there: hook, setup, development, escalation, reveal, payoff, closing. Do
not force a script into this structure.

For each beat decide what the narration communicates, what the viewer should
understand or feel, the strongest concrete image for it, and what must stay hidden
until a later beat. Show what the narration says at that moment. Never reveal the
payoff early and never add unsupported facts for effect.

═══════════════════════════════════════
2. VISUAL CONCEPT
═══════════════════════════════════════

Develop the idea before the shot or the prompt. Choose the approach that serves the
words: literal depiction, visual analogy, scale contrast, a revealing detail, human
consequence, environmental context, evidence or comparison, or a visual surprise
that is immediately understandable. Use literal imagery when it is stronger than a
metaphor.

For the hook and each major reveal, weigh at least three distinct concepts
privately — on immediate comprehension, curiosity, specificity to this narration,
factual accuracy, fit with the master style and feasibility — and keep the
strongest. Output only the one you chose.

Reject generic imagery: no lightbulb for an idea, brain for intelligence, clock for
time, pile of money for cost or anonymous laptop for technology, unless the
specific composition says something. Novelty must strengthen the meaning.

The hook is one of the most arresting images of the video: one clear focal point,
understandable at a glance, specific to this video, interesting without text.

═══════════════════════════════════════
3. CONTINUITY BIBLE
═══════════════════════════════════════

Before planning shots, define the recurring elements that must stay the same from
image to image. Each image is generated independently, with no memory of the
others; the bible is the only thing that holds a subject together.

Write one entry per recurring character, prop or setting:
- id: short lowercase identifier (letters, digits, underscore), unique.
- kind: "character" | "prop" | "setting".
- name: how you refer to it in scene prompts, e.g. "the learner", "the teal book".
- description: a fixed, self-contained description that names every feature that
  must not change — for a character: age and build, hair, face, glasses, each
  garment with its colour, material and pattern, distinctive accessories; for a
  prop: shape, colour, material, distinguishing marks; for a setting: layout,
  materials, fixed objects, light direction. Anything you leave open will drift
  between images, so close it: say "plain mustard-yellow cable-knit sweater", not
  "a yellow sweater".

Rules:
- The description is appended word for word to every scene that lists the entry.
  Write it as a noun phrase or a full sentence that reads correctly on its own.
- A character who appears in clearly different outfits gets one entry per outfit,
  with the same face, hair and build wording in each.
- Do not put the master style, the aspect ratio or lighting mood into a
  description. The style is added separately.
- Keep the bible short. Do not invent recurring characters or objects the
  narration does not need. An empty bible is valid.
- For real products, vehicles, places and people, do not invent distinctive
  features. If a detail cannot be known, leave it out or stay less specific.

═══════════════════════════════════════
4. SCENES AND TIMING — INDEXED WORD LIST
═══════════════════════════════════════

The narration is given as a numbered word list with timestamps. Punctuation is
preserved: a period, question mark or exclamation mark ends a sentence. For each
scene output start_word and end_word, integer indices from the list, inclusive.
Durations are computed from the timestamps; do not output them.

- Every scene lasts between 1.0 and 5.0 seconds. Use the timestamps, and the word
  budget in the user message, to stay inside the limit.
- A beat longer than 5 seconds becomes two or more scenes with different concepts
  or shots. Split at a sentence or clause boundary, never mid-phrase, and never
  separate a noun from its adjective.
- A fragment under 1 second joins a neighbour when the result stays coherent.
- Starting points: hook 1–2.5 s, punchline 1–2 s, setup or context 2.5–4 s, key
  fact or reveal 2.5–4 s, escalation 1.5–2.5 s per beat, payoff 3–5 s,
  closing 2–4 s. The narration and the concept decide.

Coverage — critical. Every index belongs to exactly one scene:
first scene start_word = 0; last scene end_word = N − 1;
scene[i].end_word + 1 == scene[i+1].start_word for every pair.

═══════════════════════════════════════
5. SHOT PLANNING AND RHYTHM
═══════════════════════════════════════

Plan the whole shot sequence before writing any prompt.

shot.size: extreme wide | wide | medium | close-up | extreme close-up.
shot.angle: eye-level | low | high | top-down | side-on | three-quarter |
over-the-shoulder.

Consecutive scenes differ in at least two of: shot size, camera angle, detail
level (environment, main subject, revealing detail, scale relationship, human
reaction, silhouette), and subject placement. Never repeat a shot configuration in
consecutive scenes by default. Deliberate repetition is allowed only for a
narrative reason — escalation, comparison, suspense, a visible change — and you
say so in visual_concept.

Use the cuts to mean something: context then detail reveals; detail then wide
establishes scale; tightening shots build tension; a sudden wider frame reveals a
larger relationship; a quiet, simple frame strengthens a payoff. The payoff has
one dominant focal point. Reuse an opening motif at the close only when it
strengthens the ending.

═══════════════════════════════════════
6. NARRATION FIT AND FACTUAL ACCURACY
═══════════════════════════════════════

Every scene faithfully supports its own words. One clear visual idea per scene.
No atmospheric filler. Do not depict imagined events as genuine historical
photographs, do not invent logos, labels, numbers, interfaces or technical
components, and do not let exaggeration contradict the claim. For an uncertain
detail, omit it or choose a less specific composition.

Text and numbers never go into the image. They are added in post-production as
on-screen text:
- on_screen_text is set only when the narration itself states a figure, a date,
  or opens a numbered section, and then it repeats the narration's own figure or
  label. Do not invent overlay copy. Otherwise it is null.
- on_screen_text_type: "stat" for a figure, "date" for a year or date with its
  context (never a bare year), "label" for a section opener. null when
  on_screen_text is null.

═══════════════════════════════════════
7. THE IMAGE PROMPT
═══════════════════════════════════════

ai_prompt is one coherent paragraph describing ONLY what is specific to this
scene, in this order:
1. Subject and frozen action: who or what is visible and the precise instant.
2. Composition: shot size, angle, perspective, framing, focal point, placement.
3. Spatial relationships: relative scale, foreground, middle ground, background.
4. Environment and details that support the concept, nothing else.
5. Lighting and mood, consistent with the master style.

Refer to a bible entry by its exact name ("the learner", "the teal book") and list
its id in entities. Do NOT restate its description: code appends it.

Never include in ai_prompt:
- the master style or any part of it (palette, rendering technique, line quality);
- the aspect ratio or orientation;
- instructions about text, borders, letterboxing or keeping an area clear;
- "same as the previous image", "as before", or any reference to another scene.

Describe one instant, not a sequence. Use concrete actions and relationships;
never "a dramatic moment". Establish a hierarchy: primary subject, supporting
detail, background. Keep the main subject readable at phone size. More words do
not make a better image: remove redundant adjectives and competing ideas.

visual_concept: one sentence — what the viewer sees and why it carries the beat.
visual_keywords: 3–6 short concrete nouns or phrases naming what is in the frame.

═══════════════════════════════════════
8. MOTION
═══════════════════════════════════════

The image is a still that the renderer moves. Give each scene:
- motion_note: one concise instruction in your own words, e.g. "Slow push-in
  toward the cracked tile", "Gentle drift left across the shelf", "Static hold".
- motion_effect: the renderer's nearest equivalent, exactly one of:
MOTION_VOCAB_PLACEHOLDER

A push-in is "zoom_in" (or "ken_burns" for a very gentle one); a pullback or
reveal of scale is "zoom_out"; a lateral drift is "pan_left" or "pan_right"; a hold
is "static". Tilts, parallax and vertical moves do not exist: choose the nearest
effect and keep your wording in motion_note. Match the move to the beat, vary it,
and prefer a clean hold on very short scenes.

═══════════════════════════════════════
9. SOUND EFFECT
═══════════════════════════════════════

sfx is exactly one of these keys, or "silence":
SFX_VOCAB_PLACEHOLDER

"silence" is the majority. Pick a key only when the scene clearly matches.

═══════════════════════════════════════
FINAL CHECK — silently, before answering
═══════════════════════════════════════

- Every word index is assigned once, in order, with no gap or overlap.
- Every scene is 1.0–5.0 seconds by the timestamps.
- Every consecutive pair differs in two shot dimensions, or says why not.
- Every id in entities exists in continuity; every bible entry is used.
- No ai_prompt contains style, aspect ratio, text instructions or a reference to
  another scene.
- A scene that is compliant but generic, confusing or repetitive is redesigned.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

{
  "continuity": [
    {
      "id": "learner",
      "kind": "character",
      "name": "the learner",
      "description": "a young woman student with a shoulder-length black bob and straight fringe, round wire-rim glasses, a dusty-rose scrunchie on her left wrist, and an oversized plain mustard-yellow cable-knit sweater over a white collared shirt"
    }
  ],
  "scenes": [
    {
      "scene": "1",
      "start_word": 0,
      "end_word": 6,
      "visual_concept": "The learner leans back beside a tower of finished books, glowing with the feeling of mastery the video is about to undermine.",
      "visual_keywords": ["tower of books", "desk lamp", "satisfied grin"],
      "shot": {"size": "medium", "angle": "low"},
      "entities": ["learner"],
      "ai_prompt": "Medium shot from a low angle, subject off-centre left: the learner leaning far back in a wooden chair with both arms behind her head and a satisfied grin, one foot on the desk edge, a thick closed book in front of her. Beside her rises a leaning tower of finished books taller than she is. A single warm desk lamp against a deep blue night window, sharp shadows on weathered wood.",
      "motion_effect": "zoom_in",
      "motion_note": "Slow push-in on her grin.",
      "on_screen_text": null,
      "on_screen_text_type": null,
      "sfx": "silence"
    }
  ]
}
"""


class AnimationStoryboardError(ValueError):
    """Raised when an animation storyboard cannot be produced; the message is safe to show the operator."""


def animation_system_prompt() -> str:
    """The animation system prompt with the motion and SFX vocabularies filled in."""
    motion = "\n".join(f'- "{m}"' for m in MOTION_EFFECTS)
    return (
        _ANIMATION_SYSTEM_PROMPT
        .replace(_MOTION_VOCAB_SENTINEL, motion)
        .replace(_SFX_VOCAB_SENTINEL, sfx_vocab_prompt_line())
    )


def build_animation_user_message(
    script: str,
    words: list[VoiceWordTimestamp],
    display_words: list[str],
    format_track: str,
    master_style: str,
) -> str:
    """The user message: format, master style (context only), word budget, word list, script.

    The master style is given so concepts and lighting fit it; the system prompt
    forbids echoing it. The word budget converts the 1–5 second limit into words at
    this voiceover's measured rate.
    """
    n_words = len(words)
    total_s = max(words[-1].end_ms / 1000.0, 1.0) if words else 1.0
    wps = n_words / total_s
    max_words = max(2, int(ANIMATION_MAX_SCENE_S * wps))
    min_words = max(1, round(ANIMATION_MIN_SCENE_S * wps))
    style = master_style.strip() or "None given. Choose concepts that work in any consistent illustration style."
    return (
        f"FORMAT: {_FORMAT_PHRASE.get(format_track, _FORMAT_PHRASE['portrait'])}. "
        "Compose for this frame; do not mention it in any ai_prompt.\n\n"
        "MASTER STYLE (context only — it is appended to every image in code; "
        f"never repeat it in your output):\n{style}\n\n"
        f"Measured speech rate: {wps:.1f} words/sec over {total_s:.1f} s. "
        f"At this rate a scene of 1.0–5.0 s is about {min_words}–{max_words} words; "
        f"HARD MAXIMUM {max_words} words. The timestamps are authoritative where they disagree.\n\n"
        f"INDEXED WORD LIST ({n_words} words — use start_word/end_word indices; "
        "punctuation marks sentence boundaries):\n"
        f"{_format_indexed_timestamps(words, display_words)}\n\n"
        f"NARRATION (for reference only — use word indices for boundaries):\n{script}"
    )


def animation_scene_flags(
    duration_s: float, ai_prompt: str | None, existing: list[str] | None = None
) -> list[str]:
    """The flags of an animation scene after its length or prompt changed.

    `too_long` and `needs_prompt` are recomputed from the scene as it is now; any
    other flag already on it (an out-of-date image) is kept.
    """
    flags = [f for f in existing or [] if f not in (SCENE_FLAG_TOO_LONG, SCENE_FLAG_NEEDS_PROMPT)]
    if duration_s > ANIMATION_MAX_SCENE_S + _MAX_SCENE_TOLERANCE_S:
        flags.append(SCENE_FLAG_TOO_LONG)
    if not (ai_prompt or "").strip():
        flags.append(SCENE_FLAG_NEEDS_PROMPT)
    return flags


_ID_CLEAN = re.compile(r"[^a-z0-9_]+")


def normalize_entity_id(raw: object) -> str:
    """Lowercase snake_case id for a continuity entry; '' when nothing usable is left."""
    return _ID_CLEAN.sub("_", str(raw or "").strip().lower()).strip("_")


def _clean_continuity(raw: object) -> list[dict]:
    """Validate the model's bible: known kinds, non-empty descriptions, unique ids."""
    entries: list[dict] = []
    seen: set[str] = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        entry_id = normalize_entity_id(item.get("id") or item.get("name"))
        if not entry_id or not description:
            logger.warning("AnimationStoryboardWorker: dropping a continuity entry without id or description")
            continue
        if entry_id in seen:
            logger.warning("AnimationStoryboardWorker: duplicate continuity id %r — keeping the first", entry_id)
            continue
        seen.add(entry_id)
        kind = str(item.get("kind") or "").strip().lower()
        entries.append({
            "id": entry_id,
            "kind": kind if kind in CONTINUITY_KINDS else "prop",
            "name": str(item.get("name") or entry_id).strip(),
            "description": description,
        })
    return entries


def _close_word_spans(scenes: list[dict], n_words: int) -> list[dict]:
    """Make the scenes cover every word exactly once, whatever the model returned.

    Sorted by start_word; the first scene is pinned to word 0, the last to N−1, and
    each scene ends where the next begins. Scenes left empty by a duplicate
    start_word are dropped. Same rule as the stock path.
    """
    ordered = sorted(
        (s for s in scenes if isinstance(s, dict)),
        key=lambda s: int(s.get("start_word", 0) or 0),
    )
    if not ordered:
        return []
    ordered[0]["start_word"] = 0
    for i in range(len(ordered) - 1):
        ordered[i]["end_word"] = int(ordered[i + 1].get("start_word", 0) or 0) - 1
    ordered[-1]["end_word"] = n_words - 1
    return [s for s in ordered if int(s.get("end_word", 0)) >= int(s.get("start_word", 0))]


_SFX_KEYS = frozenset(e.key for e in SFX_LIBRARY)


def _finish_scene(scene: dict, words: list[VoiceWordTimestamp], index: int, known_ids: set[str]) -> dict:
    """Fill the Python-owned fields of one animation scene and validate the model's.

    Timing comes from the word span. The scene is always an `ai_image` still; its
    motion is the model's choice among MOTION_EFFECTS. Entity ids that are not in
    the bible are dropped with a warning. A scene over the limit, or without a
    prompt, is flagged for the operator — never split, which would copy one prompt
    onto two scenes.
    """
    chosen_motion = scene.get("motion_effect")
    _reify_scene(scene, words, index)

    tier = _assign_asset_tier(scene["duration_s"])
    if tier == "video":
        tier = "still_motion"
    scene["asset_tier"] = tier
    scene["clip_type"] = _asset_tier_to_clip_type(tier)
    scene["motion_effect"] = normalize_motion_effect(chosen_motion, scene["clip_type"])
    scene["asset_strategy"] = "ai_image"
    scene["segment_type"] = "B-roll"
    scene["scene"] = str(index + 1)

    entities: list[str] = []
    for raw_id in scene.get("entities") if isinstance(scene.get("entities"), list) else []:
        entity_id = normalize_entity_id(raw_id)
        if entity_id in known_ids and entity_id not in entities:
            entities.append(entity_id)
        elif entity_id not in known_ids:
            logger.warning(
                "AnimationStoryboardWorker: scene %s names unknown continuity id %r — ignored",
                scene["scene"], raw_id,
            )
    scene["entities"] = entities

    shot = scene.get("shot")
    scene["shot"] = (
        {"size": str(shot.get("size") or "").strip(), "angle": str(shot.get("angle") or "").strip()}
        if isinstance(shot, dict) else None
    )
    keywords = scene.get("visual_keywords")
    scene["visual_keywords"] = [str(k).strip() for k in keywords if str(k).strip()] if isinstance(keywords, list) else []
    scene["ai_prompt"] = str(scene.get("ai_prompt") or "").strip() or None
    sfx = str(scene.get("sfx") or "").strip()
    scene["sfx"] = sfx if sfx in _SFX_KEYS else "silence"
    scene["sfx_timing"] = "scene_start"

    scene["flags"] = animation_scene_flags(scene["duration_s"], scene["ai_prompt"])
    return scene


def parse_animation_storyboard(raw_text: str, words: list[VoiceWordTimestamp]) -> Storyboard:
    """Turn the model's answer into a validated animation Storyboard.

    Raises AnimationStoryboardError when the answer is not usable JSON or has no
    scenes. Everything the model does not own (durations, clip type, strategy,
    render options, the summary) is derived here.
    """
    try:
        data = _extract_json_object(raw_text)
    except Exception as exc:
        raise AnimationStoryboardError(f"The storyboard answer was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise AnimationStoryboardError("The storyboard answer was not a JSON object.")

    continuity = _clean_continuity(data.get("continuity"))
    known_ids = {entry["id"] for entry in continuity}
    scenes = _close_word_spans(data.get("scenes") or [], len(words))
    if not scenes:
        raise AnimationStoryboardError("The storyboard answer contained no scenes.")
    scenes = [_finish_scene(scene, words, i, known_ids) for i, scene in enumerate(scenes)]

    body = _sanitize_storyboard_data({
        "global": {"subtitle_style": "", "bg_music": "", "visual_style": ANIMATION_MODE},
        "scenes": scenes,
        "summary": {
            "total_scenes": len(scenes),
            "total_duration_s": round(sum(s["duration_s"] for s in scenes), 3),
            "rhythm": " / ".join((s["shot"] or {}).get("size") or "?" for s in scenes[:8])
            + (" …" if len(scenes) > 8 else ""),
        },
        "visual_mode": ANIMATION_MODE,
        "continuity": continuity,
    })
    try:
        storyboard = Storyboard.model_validate(body)
    except Exception as exc:
        raise AnimationStoryboardError(f"The storyboard answer did not match the schema: {exc}") from exc
    # Overlays need render_options, exactly as on the stock path; no patches apply.
    return _apply_patches_and_render_options(storyboard, [])


async def request_animation_storyboard(system_prompt: str, user_content: str, api_key: str) -> str:
    """Call the model once and return its text answer.

    Streamed, because the output budget is large and the model thinks first; the
    thinking blocks are skipped and only text blocks are joined. Raises
    AnimationStoryboardError when the model declines or runs out of output.
    """
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=900.0, max_retries=0)
    async with client.messages.stream(
        model=_ANIMATION_MODEL,
        max_tokens=_ANIMATION_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": _ANIMATION_EFFORT},
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        message = await stream.get_final_message()
    if message.stop_reason == "refusal":
        raise AnimationStoryboardError("The model declined to write this storyboard.")
    if message.stop_reason == "max_tokens":
        raise AnimationStoryboardError(
            "The storyboard was cut off before it finished — the narration is too long for one pass."
        )
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text.strip():
        raise AnimationStoryboardError("The model returned no storyboard.")
    return text


async def generate_animation_storyboard(
    script: str,
    voice_timestamps: list[VoiceWordTimestamp],
    api_key: str,
    *,
    format_track: str = "portrait",
    master_style: str = "",
) -> Storyboard:
    """Generate an animation storyboard from the narration and its word timing.

    Pure with respect to storage: takes the words, returns the Storyboard. Raises
    AnimationStoryboardError when there is no voiceover timing to cut scenes on.
    """
    if not voice_timestamps:
        raise AnimationStoryboardError(
            "An Animation storyboard is cut on the voiceover's timing — generate or upload the voiceover first."
        )
    words, display = _normalize_deepgram_words_with_display([w.model_dump() for w in voice_timestamps])
    user_content = build_animation_user_message(script, words, display, format_track, master_style)
    raw_text = await request_animation_storyboard(animation_system_prompt(), user_content, api_key)
    return parse_animation_storyboard(raw_text, words)


def build_animation_storyboard_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Build the animation storyboard worker node.

    Reads state.artifacts['script'] and state.artifacts['voice_alignment'];
    state.inputs carries `format_track` and the run's resolved `master_style`.
    Emits one VerifiedStoryboardArtifact, the same type the stock worker emits.
    """

    async def _worker(state: StageState) -> WorkerOutput:
        """Run generate → validate and return the VerifiedStoryboardArtifact."""
        _, script_body = await read_artifact(storage, state.artifacts["script"])
        script_text = ScriptArtifact.model_validate(script_body).script

        voice_timestamps: list[VoiceWordTimestamp] = []
        if "voice_alignment" in state.artifacts:
            _, va_body = await read_artifact(storage, state.artifacts["voice_alignment"])
            voice_timestamps = VoiceAlignmentArtifact.model_validate(va_body).word_timestamps

        storyboard = await generate_animation_storyboard(
            script_text,
            voice_timestamps,
            anthropic_api_key,
            format_track=state.inputs.get("format_track", "portrait"),
            master_style=str(state.inputs.get("master_style") or ""),
        )
        flagged = sum(1 for s in storyboard.scenes if SCENE_FLAG_TOO_LONG in s.flags)
        logger.info(
            "AnimationStoryboardWorker: %d scenes, %d continuity entries, %d over %.1fs (prompt %s)",
            len(storyboard.scenes), len(storyboard.continuity), flagged,
            ANIMATION_MAX_SCENE_S, ANIMATION_STORYBOARD_PROMPT_VERSION,
        )
        artifact = VerifiedStoryboardArtifact(
            prompt_version=ANIMATION_STORYBOARD_PROMPT_VERSION,
            scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
