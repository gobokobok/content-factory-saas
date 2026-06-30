"""VisualDirectorWorker (P11-S1) — verified_storyboard → visual_treatment artifact.

Receives the enriched storyboard (with global_context + semantic_context from P10-S3)
and produces a per-scene visual plan: shot type, search terms, motion preset, diversity
strategy. The AcquisitionWorker fulfils this plan; it does not make visual decisions.

Pipeline position:
    storyboard_worker → visual_director_worker → acquisition_worker → render_worker

Internal steps:
  1. Read verified_storyboard artifact from R2.
  2. Call Claude Sonnet with a documentary-editor system prompt.
  3. Validate the response: parse VisualTreatment; enforce shot-type diversity rule.
  4. On diversity violation: re-invoke with the violation highlighted (max 1 retry).
  5. Compute diversity_score; write visual_treatment artifact to R2.
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
from cf_platform.models.visual_treatment import (
    SHOT_TYPE_VOCABULARY,
    DiversityPlan,
    SceneVisualPlan,
    VisualTreatment,
)
from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
from src.models import Storyboard

logger = logging.getLogger(__name__)

VISUAL_DIRECTOR_PROMPT_VERSION = "v0.1"


class VisualTreatmentArtifact(BaseModel):
    """Terminal artifact of the VisualDirectorWorker.

    visual_treatment contains the full VisualTreatment model serialised to a dict.
    Callers deserialise via VisualTreatment.model_validate(artifact.visual_treatment).
    """

    prompt_version: str
    scene_count: int
    visual_treatment: dict  # VisualTreatment.model_dump()
    generated_at: datetime

_SONNET_MODEL = "claude-sonnet-4-6"

VISUAL_DIRECTOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version=VISUAL_DIRECTOR_PROMPT_VERSION,
    prompt="",
    model=_SONNET_MODEL,
    sampling_params={"max_tokens": 8000},
)

# Maximum number of diversity-violation retries.
_MAX_DIVERSITY_RETRIES = 1

# Minimum consecutive identical shot_types that triggers a diversity violation.
_DIVERSITY_CLUSTER_THRESHOLD = 3

# Shot-type vocabulary as a comma-separated string for the prompt.
_SHOT_TYPE_LIST = ", ".join(sorted(SHOT_TYPE_VOCABULARY))

_SYSTEM_PROMPT = """\
You are an experienced documentary video editor and visual director.

Your task: given a voiceover storyboard for a YouTube documentary, produce a visual
treatment — a per-scene visual plan that a stock-footage researcher will execute.

You do NOT search for assets. You answer: "If a top documentary editor planned the
visuals for this script, what would they specify?"

═══════════════════════════════════════
SHOT TYPE VOCABULARY (use ONLY these values for shot_type)
═══════════════════════════════════════

portrait        — headshot / portrait photo of a specific named person
wide            — establishing shot: cityscape, landscape, building exterior
macro_science   — close-up: microscopy, molecular imagery, laboratory detail
diagram         — chart, graph, data visualisation, infographic
archive         — historical photo, archival news footage, documentary archive
drone           — aerial view, overhead cityscape
lifestyle       — person in context: working, walking, daily activity
screen_recording — software interface, website, data dashboard
animation       — motion graphic, explainer animation, cartoon
infographic     — text + icon visual summary, numbered list graphic

═══════════════════════════════════════
DIVERSITY RULES (STRICTLY ENFORCED)
═══════════════════════════════════════

1. No 3 or more consecutive scenes may share the same shot_type.
2. A run of more than 10 scenes must use at least 4 distinct shot_types.
3. Open with a wide or establishing shot unless the first scene names a specific person.
4. Alternate between "close" types (portrait, macro_science) and "wide" types (wide, drone, lifestyle).

═══════════════════════════════════════
ASSET CLASS RULES
═══════════════════════════════════════

Use exactly one of: "person_photo", "stock", "archive_image", "diagram", "animation"

- person_photo   → Character segment_type; person_name is set in storyboard
- archive_image  → Event segment_type; historical era
- diagram        → when shot_type is "diagram" or "infographic"
- animation      → when shot_type is "animation"
- stock          → all other B-roll scenes

═══════════════════════════════════════
PREFERRED SOURCE RULES
═══════════════════════════════════════

- person_photo   → always "wikimedia"
- archive_image  → always "wikimedia"
- diagram        → "any" (no good source for diagrams in stock)
- stock          → "pexels" (Pexels has the best stock video coverage)

═══════════════════════════════════════
SEARCH TERMS RULES
═══════════════════════════════════════

search_terms is an ordered list of 2–4 queries tried in sequence by the acquisition layer.
Rules:
- Each query: 2–5 concrete nouns. No verbs. No articles. No adjectives unless essential.
- First query: most specific. Subsequent queries: progressively broader.
- CRITICAL: domain-anchor every query. If global_context.domain is "neuroscience":
    "protein" scenes → "neuron protein synapse" NOT "protein shake" NOT "food"
    "cell" scenes    → "neuron brain cell"        NOT "blood cell" NOT "bacteria"
- Use semantic_context.domain_qualifier when present to anchor the query.
- For person_photo: first query is "{person_name} {person_title or role}"; second is "{person_name}".
- For archive_image: include the specific event or era name.
- NEVER include the avoid list terms in your search_terms.

═══════════════════════════════════════
OUTPUT FORMAT
═══════════════════════════════════════

Output ONLY a valid JSON object — no prose, no markdown fences.

{
  "global_style": "<one-line aesthetic direction for the whole run>",
  "shot_sequence_plan": "<macro shot-type arc, e.g. 'wide → macro → portrait → archive → wide'>",
  "scenes": [
    {
      "scene": <integer, 1-indexed>,
      "visual_intent": "<one sentence: what should the viewer feel or understand from this shot>",
      "shot_type": "<from vocabulary above>",
      "era": "<'contemporary' | '1930s' | 'timeless' | other era label>",
      "asset_class": "<person_photo | stock | archive_image | diagram | animation>",
      "preferred_source": "<wikimedia | pexels | pixabay | any>",
      "search_terms": ["<query 1>", "<query 2>", ...],
      "avoid": ["<term to exclude>", ...],
      "motion": "<ken_burns_in | ken_burns_out | slow_push | static | none>",
      "transition_from_prev": "<cut | dissolve | fade>"
    }
  ],
  "diversity_plan": {
    "shot_type_sequence": ["wide", "macro_science", ...],
    "notes": "<brief diversity strategy note>"
  }
}

Include every scene from the storyboard. scene numbers must be 1-indexed and match
the order of scenes in the input storyboard exactly.
"""


def _extract_json_object(text: str) -> dict:
    """Extract and parse a JSON object from Claude's response, stripping markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def _detect_diversity_violations(scenes: list[SceneVisualPlan]) -> list[str]:
    """Return a list of human-readable diversity violation descriptions.

    Checks for runs of 3+ consecutive identical shot_types.
    """
    violations: list[str] = []
    if len(scenes) < _DIVERSITY_CLUSTER_THRESHOLD:
        return violations

    run_start = 0
    for i in range(1, len(scenes)):
        if scenes[i].shot_type != scenes[i - 1].shot_type:
            run_start = i
        else:
            run_length = i - run_start + 1
            if run_length == _DIVERSITY_CLUSTER_THRESHOLD:
                violations.append(
                    f"Scenes {run_start + 1}–{i + 1} all have shot_type='{scenes[i].shot_type}' "
                    f"({run_length} consecutive — max allowed is {_DIVERSITY_CLUSTER_THRESHOLD - 1})"
                )
    return violations


def _compute_diversity_score(scenes: list[SceneVisualPlan]) -> float:
    """Compute diversity_score = unique_shot_types / total_scenes."""
    if not scenes:
        return 0.0
    unique = len({s.shot_type for s in scenes})
    return round(unique / len(scenes), 3)


def _build_storyboard_user_message(storyboard: Storyboard) -> str:
    """Serialise the storyboard into a compact JSON user message for Claude."""
    scenes_data = []
    for i, scene in enumerate(storyboard.scenes, start=1):
        sd: dict = {
            "scene": i,
            "segment_type": scene.segment_type,
            "voiceover_line": scene.voiceover_line,
            "primary_stk": scene.primary_stk,
        }
        if scene.person_name:
            sd["person_name"] = scene.person_name
            sd["person_title"] = scene.person_title or ""
        if scene.semantic_context:
            sc = scene.semantic_context
            sd["semantic_context"] = {
                "primary_concept": sc.primary_concept,
                "domain_qualifier": sc.domain_qualifier,
                "avoid": sc.avoid,
                "visual_tags": sc.visual_tags,
                "entity_type": sc.entity_type,
            }
        scenes_data.append(sd)

    payload: dict = {"scenes": scenes_data}
    if storyboard.global_context:
        gc = storyboard.global_context
        payload["global_context"] = {
            "topic": gc.topic,
            "domain": gc.domain,
            "subtopics": gc.subtopics,
            "avoid_globally": gc.avoid_globally,
            "tone": gc.tone,
        }

    return json.dumps(payload, indent=2)


def _parse_treatment(raw: dict, scene_count: int) -> VisualTreatment:
    """Parse Claude's raw JSON dict into a validated VisualTreatment.

    Normalises shot_type values: unknown values fall back to "wide" with a warning.
    Truncates scene list to actual scene_count; pads with wide/stock if short.
    """
    raw_scenes = raw.get("scenes", [])
    scenes: list[SceneVisualPlan] = []

    for i, rs in enumerate(raw_scenes[:scene_count], start=1):
        shot_type = rs.get("shot_type", "wide")
        if shot_type not in SHOT_TYPE_VOCABULARY:
            logger.warning("VisualDirector: unknown shot_type=%r for scene %d — normalising to 'wide'", shot_type, i)
            shot_type = "wide"
        scenes.append(SceneVisualPlan(
            scene=i,
            visual_intent=rs.get("visual_intent", ""),
            shot_type=shot_type,
            era=rs.get("era", "contemporary"),
            asset_class=rs.get("asset_class", "stock"),
            preferred_source=rs.get("preferred_source", "any"),
            search_terms=rs.get("search_terms", []),
            avoid=rs.get("avoid", []),
            motion=rs.get("motion", "none"),
            transition_from_prev=rs.get("transition_from_prev", "cut"),
        ))

    # Pad if Claude returned fewer scenes than the storyboard has.
    while len(scenes) < scene_count:
        idx = len(scenes) + 1
        logger.warning("VisualDirector: missing scene %d in treatment — inserting wide/stock placeholder", idx)
        scenes.append(SceneVisualPlan(
            scene=idx,
            visual_intent="Generic B-roll — visual director did not specify",
            shot_type="wide",
            asset_class="stock",
        ))

    dp_raw = raw.get("diversity_plan", {})
    diversity_plan = DiversityPlan(
        shot_type_sequence=dp_raw.get("shot_type_sequence", []),
        notes=dp_raw.get("notes", ""),
    )

    return VisualTreatment(
        global_style=raw.get("global_style", ""),
        shot_sequence_plan=raw.get("shot_sequence_plan", ""),
        scenes=scenes,
        diversity_plan=diversity_plan,
        prompt_version=VISUAL_DIRECTOR_PROMPT_VERSION,
    )


async def _call_visual_director(
    client: anthropic.AsyncAnthropic,
    storyboard: Storyboard,
    violation_feedback: Optional[str] = None,
) -> dict:
    """Call Claude Sonnet to generate (or re-generate) the visual treatment.

    When violation_feedback is provided, it is appended to the user message so
    Claude knows which diversity rules were violated in the previous attempt.
    """
    user_message = _build_storyboard_user_message(storyboard)
    if violation_feedback:
        user_message = (
            f"{user_message}\n\n"
            f"⚠️ DIVERSITY VIOLATION IN PREVIOUS ATTEMPT — you MUST fix these:\n"
            f"{violation_feedback}\n\n"
            f"Re-generate the full treatment. Spread shot_types across consecutive scenes."
        )

    response = await client.messages.create(
        model=_SONNET_MODEL,
        max_tokens=8000,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return _extract_json_object(response.content[0].text)


def build_visual_director_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Factory: build the VisualDirectorWorker async callable.

    Reads verified_storyboard → produces visual_treatment artifact.

    Returns:
        Async callable matching the WorkerNode signature.
    """
    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

    async def _worker(state: StageState) -> WorkerOutput:
        """VisualDirectorWorker main: storyboard → visual treatment → R2 artifact."""
        run_id = state.run_id

        # ── 1. Read the verified storyboard ──────────────────────────────────
        sb_key = state.artifacts.get("verified_storyboard")
        if not sb_key:
            raise ValueError("VisualDirectorWorker: 'verified_storyboard' artifact key missing from state")

        _, sb_body = await read_artifact(storage, sb_key)
        sb_artifact = VerifiedStoryboardArtifact.model_validate(sb_body)
        storyboard = Storyboard.model_validate(sb_artifact.storyboard)
        scene_count = len(storyboard.scenes)

        logger.info("VisualDirectorWorker run=%s scenes=%d", run_id, scene_count)

        # ── 2. Call Visual Director (with retry on diversity violation) ───────
        violation_feedback: Optional[str] = None
        treatment: Optional[VisualTreatment] = None

        for attempt in range(_MAX_DIVERSITY_RETRIES + 1):
            try:
                raw = await _call_visual_director(client, storyboard, violation_feedback)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.error("VisualDirectorWorker: JSON parse error attempt=%d: %s", attempt, exc)
                raise RuntimeError(f"VisualDirectorWorker: could not parse Claude response: {exc}") from exc

            treatment = _parse_treatment(raw, scene_count)
            violations = _detect_diversity_violations(treatment.scenes)

            if not violations:
                break

            if attempt < _MAX_DIVERSITY_RETRIES:
                violation_feedback = "\n".join(violations)
                logger.warning(
                    "VisualDirectorWorker run=%s diversity violations (attempt %d/%d): %s",
                    run_id, attempt + 1, _MAX_DIVERSITY_RETRIES + 1, violation_feedback,
                )
            else:
                # Log but do not block — a slightly non-diverse treatment is better than failure.
                logger.error(
                    "VisualDirectorWorker run=%s diversity violations persist after retry: %s",
                    run_id, "\n".join(violations),
                )

        # ── 3. Compute and attach diversity_score ────────────────────────────
        treatment.diversity_score = _compute_diversity_score(treatment.scenes)
        logger.info(
            "VisualDirectorWorker run=%s diversity_score=%.3f unique_shot_types=%d",
            run_id, treatment.diversity_score, len({s.shot_type for s in treatment.scenes}),
        )

        # ── 4. Return artifact (observed wrapper writes to R2) ────────────────
        artifact = VisualTreatmentArtifact(
            prompt_version=VISUAL_DIRECTOR_PROMPT_VERSION,
            scene_count=scene_count,
            visual_treatment=treatment.model_dump(),
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return _worker
