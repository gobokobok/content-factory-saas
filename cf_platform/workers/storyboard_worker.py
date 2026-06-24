"""StoryboardWorker (P9-S2) — Script → verified_storyboard artifact.

Internal generate→review→patch cycle. Single `verified_storyboard` artifact emitted.
No intermediate reviewer artifact surfaced externally.

Pipeline position (after P9-S5 wiring):
    voice_production → storyboard_worker → acquisition_worker → render_worker

Steps:
  1. Generate (Sonnet, prompt v0.12) — JSON output with segment_type, three-tier
     queries (primary_stk / context_stk / concept_stk), on_screen_text_type.
  2. Review (Haiku) — checks five quality dimensions; returns structured JSON patches.
  3. Patch (deterministic) — applies patches, then computes render_options per scene.
  4. Emit verified_storyboard artifact to R2 via the observability wrapper.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
from src.models import (
    LowerThirdSpec,
    OnScreenTextOverlay,
    SceneRenderOptions,
    Storyboard,
    StoryboardGlobal,
    StoryboardScene,
    StoryboardSummary,
    VisualPrompts,
)

logger = logging.getLogger(__name__)

STORYBOARD_PROMPT_VERSION = "v0.12"

_SONNET_MODEL = "claude-sonnet-4-6"
_HAIKU_MODEL = "claude-haiku-4-5-20251001"

STORYBOARD_WORKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version=STORYBOARD_PROMPT_VERSION,
    prompt="",
    model=_SONNET_MODEL,
    sampling_params={"max_tokens": 16000},
)

_GENERATE_SYSTEM_PROMPT = """\
You are a production storyboard generator for a faceless, voiceover-driven YouTube Shorts channel.

Format: 30–60 second YouTube Short, 9:16 vertical. Voiceover only. Stock footage + Wikimedia Commons.

Your job: take a voiceover script and produce a full production storyboard.
Output ONLY a valid JSON object — no prose, no markdown fences, no extra keys.
Every word in the script must appear verbatim in exactly one scene's voiceover_line.

═══════════════════════════════════════
SEGMENT TYPE
═══════════════════════════════════════

Every scene has a segment_type. Use exactly one of:

"Character" — the voiceover names a specific real individual AND the scene should show
  that person's face (e.g. Jerome Powell, Octavia Hill, Robert Moses).
  MUST set person_name and person_title.
  Acquisition: tries Wikipedia portrait first; falls back to Pexels+Pixabay on miss.

"Event" — the voiceover names a specific historical event, era, or landmark (e.g. London
  Blitz, Great Depression, Letchworth Garden City, postwar housing boom).
  Acquisition: searches Wikimedia Commons for archival imagery first.

"B-roll" — everything else: generic stock video/photo illustrating a concept.
  Acquisition: Pexels + Pixabay concurrent merge+rank.

Rules:
- Never assign "Character" without setting person_name.
- Never assign "Event" for abstract concepts (inflation, demand, equity) — use "B-roll".
- Set "Character" for any named individual the scene should depict, including historical
  figures (Octavia Hill, Ebenezer Howard, Harold Macmillan). Wikipedia has portraits
  for most figures born after ~1820.

Examples:
  VO: "Jerome Powell signalled rates would stay high"
    → segment_type: "Character", person_name: "Jerome Powell", person_title: "Chair, Federal Reserve"
  VO: "The London Blitz destroyed four million homes"
    → segment_type: "Event"
  VO: "Homeownership rates dropped to 1960s lows"
    → segment_type: "B-roll"

═══════════════════════════════════════
THREE-TIER QUERIES
═══════════════════════════════════════

Every scene gets three search queries in priority cascade order.

1. primary_stk — Pexels+Pixabay search string
   - 3–4 concrete nouns only. No adjectives. No verbs. No era labels.
   - Topic-anchored: what B-roll would a documentary filmmaker cut to for THIS line in
     this video's topic domain? ("Repairs" in a housing video = house renovation, not tools.)
   - SEMANTIC RULE: query the CONCEPT being communicated, never the literal words spoken.
     VO "point zero three percent annual growth" → concept is tiny growth rate →
       primary_stk: "economy slow growth graph" NOT "pointing finger".
     VO "inflation eating savings" → concept is purchasing power erosion →
       primary_stk: "money value decline chart" NOT "eating food".
   - For Character: start with person's full name (e.g. "Jerome Powell Federal Reserve")
   - For Event: include the specific proper noun (e.g. "London Blitz 1940 ruins")

2. context_stk — broader Pexels+Pixabay fallback
   - 1–2 words. Core subject only. Broadest noun that still covers the scene.
   - For Character: person's surname only (e.g. "Powell")
   - For Event: event/place name only (e.g. "London Blitz")

3. concept_stk — most abstract fallback
   - Single noun. The most universal term for the scene's concept.
   - Examples: "housing", "interest", "economy", "city", "people", "government"

Example:
  VO: "Rents in major cities rose 30% in three years"
  primary_stk: "apartment building city rental"
  context_stk: "apartment"
  concept_stk: "housing"

═══════════════════════════════════════
ON_SCREEN_TEXT TYPE
═══════════════════════════════════════

on_screen_text_type must be one of three values (or null when on_screen_text is null):
- "stat" — a data point, percentage, or number (e.g. "38% decline", "$450K median price")
- "date" — a year or date range (e.g. "1970–1990", "March 2022")
- "lower_third" — reserved; do NOT use this — the reviewer computes it for Character scenes

Rules:
- When on_screen_text contains a stat or figure, set on_screen_text_type: "stat"
- When on_screen_text is a year or date, set on_screen_text_type: "date"
- When on_screen_text is null, on_screen_text_type must also be null

═══════════════════════════════════════
RENDER DECISION NOTE
═══════════════════════════════════════

Do NOT set render_options — that field is computed by the storyboard reviewer.
Your job is to set the raw scene fields accurately. The reviewer reads them and writes render_options.

═══════════════════════════════════════
DURATION RULES
═══════════════════════════════════════

Duration is derived from the word count of voiceover_line, never from clip type ceiling.

| Words in VO line      | Duration     |
|-----------------------|--------------|
| List item, 1 word     | 0.3–0.4s     |
| List item, 2–3 words  | 0.5–0.7s     |
| List item, 3–4 words  | 0.8–1.0s     |
| Non-list, 4–6 words   | 1.0–1.5s     |
| Non-list, 7–10 words  | 2.0–2.5s     |
| Non-list, 11–14 words | 3.0–3.5s     |
| 15+ words             | Split into two scenes |

- Non-list scene minimum: 1.0s. List item minimum: 0.7s (except single-word items).
- HARD MAXIMUM: still_with_motion scenes must not exceed 5.0s. Video (hard_cut/animated)
  scenes must not exceed 10.0s. If the voiceover line would push a still past 5.0s, split
  it into two scenes at the nearest clause boundary.

If WORD TIMESTAMPS are provided, use them authoritatively:
  duration_s = (end_ms of last VO word − start_ms of first VO word) / 1000 + up to 0.3s tail
  Never use the word-count table when timestamps are present.
  If a timestamp-derived duration would exceed the hard maximum above, split the scene.

═══════════════════════════════════════
CLIP TYPE RULES
═══════════════════════════════════════

- hard_cut: emphasis, shock, list items. motion_effect: null.
- still_with_motion: single frame + movement. motion_effect is mandatory:
  one of ken_burns_in | ken_burns_out | pan_left | pan_right.
- animated: concept requires change or sequence. motion_effect: null.

COMMA-LIST RULE: each list item → its own hard_cut scene, labelled 03a / 03b / 03c.
Bridge phrases ("Others enjoy activities like") belong to the first item's voiceover_line.

═══════════════════════════════════════
COVERAGE RULE — CRITICAL
═══════════════════════════════════════

Every word in the input script must appear verbatim in exactly one scene's voiceover_line.
After writing all scenes, verify: read the script left to right — each word maps to exactly
one voiceover_line.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

Output ONLY the JSON object below. No prose. No markdown fences. No extra keys.

{
  "global": {
    "subtitle_style": "...",
    "bg_music": "...",
    "visual_style": "..."
  },
  "scenes": [
    {
      "scene": "1",
      "clip_type": "still_with_motion",
      "duration_s": 2.5,
      "voiceover_line": "...",
      "segment_type": "B-roll",
      "primary_stk": "house exterior repair workers",
      "context_stk": "house renovation",
      "concept_stk": "housing",
      "on_screen_text": null,
      "on_screen_text_type": null,
      "motion_effect": "ken_burns_in",
      "sfx": "ambient street traffic",
      "sfx_timing": "on cut",
      "person_name": null,
      "person_title": null
    }
  ],
  "summary": {
    "total_scenes": 15,
    "total_duration_s": 32.5,
    "rhythm": "SM / HC / HC / AN / SM"
  }
}
"""

_REVIEW_SYSTEM_PROMPT = """\
You are a storyboard quality reviewer. Given a JSON storyboard and the original script,
check five quality dimensions and return a structured JSON patch list.

Review dimensions:
a. Coverage: every word from the original script must appear verbatim in exactly one
   scene's voiceover_line. Flag missing or duplicated words.
b. segment_type correctness: named real person → must be "Character" (and person_name set);
   named specific historical event/era/landmark → must be "Event"; everything else → "B-roll".
   Correct misclassifications.
c. on_screen_text gaps: if voiceover_line contains a prominent stat (percentage, dollar figure)
   or year/date that would be compelling on-screen but on_screen_text is null, suggest adding
   it. Only suggest when the stat/date is the core point of the scene — not every number.
d. Query domain anchoring: primary_stk should reflect the video topic domain, not literal VO
   words. Flag when queries contain era labels (Victorian, 1880s, medieval) or drift off-topic.
   Suggest a topic-anchored replacement.
e. SFX specificity: sfx must be a concrete, specific noun phrase (e.g. "pen scratching paper",
   "crowd applause in conference room"). Flag vague values like "sound", "noise", "ambient".
   Suggest a specific replacement.

Output ONLY valid JSON. No prose. No markdown fences.

{
  "coverage_ok": true,
  "patches": [
    {"scene_id": "3", "field": "segment_type", "value": "Character"},
    {"scene_id": "3", "field": "person_name", "value": "Jerome Powell"},
    {"scene_id": "5", "field": "sfx", "value": "crowd applause in conference hall"}
  ],
  "issues": [
    "Scene 3: Jerome Powell named in VO but segment_type was B-roll"
  ]
}

Rules:
- Only include patches for genuine problems. An empty patches list is valid and encouraged.
- patches[].field must be one of: segment_type, person_name, person_title, primary_stk,
  context_stk, concept_stk, on_screen_text, on_screen_text_type, sfx, sfx_timing
- Do NOT patch render_options — that is computed after your review.
- coverage_ok is true only when every script word appears in exactly one voiceover_line.
- Limit patches to the most impactful corrections. Do not over-patch.
"""


# ── Artifact schema ───────────────────────────────────────────────────────────


class VerifiedStoryboardArtifact(BaseModel):
    """Terminal artifact of the StoryboardWorker.

    storyboard is the full Storyboard model serialised to a dict with render_options
    populated on every scene. Callers deserialise via Storyboard.model_validate(artifact.storyboard).
    """

    prompt_version: str
    scene_count: int
    storyboard: dict  # Storyboard.model_dump(by_alias=True, mode="json")
    generated_at: datetime


# ── Helper functions ──────────────────────────────────────────────────────────


def _format_voice_timestamps(words: list[VoiceWordTimestamp]) -> str:
    """Format word timestamps as a compact block for the generate prompt."""
    return "\n".join(f'[{w.start_ms}ms–{w.end_ms}ms] "{w.word}"' for w in words)


def _extract_json_object(text: str) -> dict:
    """Extract and parse a JSON object from a Claude response, stripping markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _parse_review_response(text: str) -> tuple[list[dict], bool, list[str]]:
    """Parse Haiku's review JSON. Returns (patches, coverage_ok, issues).

    Gracefully returns ([], True, []) on any parse failure so a bad review
    response never blocks the pipeline.
    """
    try:
        data = _extract_json_object(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("StoryboardWorker: could not parse review response — skipping patches")
        return [], True, []
    patches = [p for p in data.get("patches", []) if isinstance(p, dict)]
    coverage_ok = bool(data.get("coverage_ok", True))
    issues = [str(i) for i in data.get("issues", [])]
    return patches, coverage_ok, issues


def _apply_patches_and_render_options(
    storyboard: Storyboard,
    patches: list[dict],
) -> Storyboard:
    """Apply review patches then compute render_options for every scene.

    Patch step (deterministic):
    1. Apply field-level patches from the review.
    2. For each scene, compute render_options based on segment_type / on_screen_text:
       - Character + person_name → lower_third overlay; on_screen_text nulled out
       - Event → film_look = True
       - on_screen_text present (stat/date) → on_screen_text_overlay with enable_expr
         computed from cumulative scene duration offsets
    3. lower_third always carries caption_y_override=1540 so subtitles shift up.
    """
    # Index scenes by ID for O(1) patch application
    scenes_by_id: dict[str, StoryboardScene] = {s.scene: s for s in storyboard.scenes}
    original_order = [s.scene for s in storyboard.scenes]

    _PATCHABLE_FIELDS = {
        "segment_type", "person_name", "person_title",
        "primary_stk", "context_stk", "concept_stk",
        "on_screen_text", "on_screen_text_type", "sfx", "sfx_timing",
    }

    for patch in patches:
        scene_id = str(patch.get("scene_id", ""))
        field = str(patch.get("field", ""))
        value = patch.get("value")
        if scene_id not in scenes_by_id or field not in _PATCHABLE_FIELDS:
            continue
        scenes_by_id[scene_id] = scenes_by_id[scene_id].model_copy(update={field: value})

    # Compute render_options using cumulative scene start times
    cumulative_t = 0.0
    patched_scenes: list[StoryboardScene] = []

    for scene_id in original_order:
        scene = scenes_by_id[scene_id]
        scene_start = cumulative_t
        render_kwargs: dict = {}

        # Character + person_name → lower_third overlay; null on_screen_text
        if scene.segment_type == "Character" and scene.person_name:
            render_kwargs["lower_third"] = LowerThirdSpec(
                name=scene.person_name,
                title=scene.person_title,
                caption_y_override=1540,
            )
            scene = scene.model_copy(update={"on_screen_text": None, "on_screen_text_type": None})

        # Event → film_look
        if scene.segment_type == "Event":
            render_kwargs["film_look"] = True

        # on_screen_text (stat or date) → timed on_screen_text_overlay
        if (
            scene.on_screen_text
            and scene.on_screen_text_type
            and scene.on_screen_text_type in ("stat", "date")
        ):
            end_t = scene_start + scene.duration_s
            enable_expr = f"between(t,{scene_start:.3f},{end_t:.3f})"
            render_kwargs["on_screen_text_overlay"] = OnScreenTextOverlay(
                text=scene.on_screen_text,
                type=scene.on_screen_text_type,
                enable_expr=enable_expr,
            )

        if render_kwargs:
            scene = scene.model_copy(update={"render_options": SceneRenderOptions(**render_kwargs)})

        cumulative_t += scene.duration_s
        patched_scenes.append(scene)

    return storyboard.model_copy(update={"scenes": patched_scenes})


# ── API call helpers ──────────────────────────────────────────────────────────


async def _generate(
    script: str,
    voice_timestamps: list[VoiceWordTimestamp],
    api_key: str,
) -> Storyboard:
    """Call Sonnet with prompt v0.12 to generate the raw storyboard JSON."""
    if voice_timestamps:
        ts_block = _format_voice_timestamps(voice_timestamps)
        user_content = (
            "WORD TIMESTAMPS (Deepgram Nova-2 — use for scene duration_s):\n"
            f"{ts_block}\n\n"
            f"VOICEOVER SCRIPT:\n{script}"
        )
    else:
        user_content = script

    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=_SONNET_MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": _GENERATE_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    raw_text = message.content[0].text
    try:
        data = _extract_json_object(raw_text)
        return Storyboard.model_validate(data)
    except Exception as exc:
        raise ValueError(f"StoryboardWorker: failed to parse generate response: {exc}") from exc


async def _review(
    script: str,
    storyboard: Storyboard,
    api_key: str,
) -> tuple[list[dict], bool, list[str]]:
    """Call Haiku to review the storyboard across 5 quality dimensions.

    Returns (patches, coverage_ok, issues).
    """
    storyboard_json = json.dumps(
        storyboard.model_dump(by_alias=True, mode="json"),
        indent=2,
    )
    user_content = (
        f"ORIGINAL SCRIPT:\n{script}\n\n"
        f"STORYBOARD JSON:\n{storyboard_json}"
    )

    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": _REVIEW_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    raw_text = message.content[0].text
    return _parse_review_response(raw_text)


# ── Worker factory ────────────────────────────────────────────────────────────


def build_storyboard_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Build the storyboard worker node.

    Reads state.artifacts['script'] and optionally state.artifacts['voice_alignment'].
    Internal cycle: generate (Sonnet) → review (Haiku) → patch (deterministic).
    Emits a single VerifiedStoryboardArtifact with render_options populated per scene.
    """

    async def _worker(state: StageState) -> WorkerOutput:
        """Run generate→review→patch and return VerifiedStoryboardArtifact."""
        # Read script
        script_key = state.artifacts["script"]
        _, script_body = await read_artifact(storage, script_key)
        script_artifact = ScriptArtifact.model_validate(script_body)
        script_text = script_artifact.script

        # Read voice alignment timestamps (optional — absent for standalone endpoint calls)
        voice_timestamps: list[VoiceWordTimestamp] = []
        if "voice_alignment" in state.artifacts:
            try:
                _, va_body = await read_artifact(storage, state.artifacts["voice_alignment"])
                va = VoiceAlignmentArtifact.model_validate(va_body)
                voice_timestamps = va.word_timestamps
            except Exception:
                logger.warning("StoryboardWorker: could not read voice_alignment — using word-count durations")

        # Step 1: Generate raw storyboard (Sonnet, prompt v0.12)
        storyboard = await _generate(script_text, voice_timestamps, anthropic_api_key)
        logger.info("StoryboardWorker: generated %d scenes", len(storyboard.scenes))

        # Step 2: Review — 5 quality dimensions (Haiku, structured JSON)
        patches, coverage_ok, issues = await _review(script_text, storyboard, anthropic_api_key)
        if not coverage_ok:
            logger.warning("StoryboardWorker: coverage check failed — %s", "; ".join(issues))
        if patches:
            logger.info("StoryboardWorker: applying %d review patches", len(patches))

        # Step 3: Patch — apply corrections + compute render_options (deterministic)
        storyboard = _apply_patches_and_render_options(storyboard, patches)

        artifact = VerifiedStoryboardArtifact(
            prompt_version=STORYBOARD_PROMPT_VERSION,
            scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
