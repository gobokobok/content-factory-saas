"""DEPRECATED (P5-S6) — replaced by evaluator.py + integrity_checker.py in the Blueprint IR pipeline (D058).
Kept importable so legacy tests pass; not registered in the active idea_to_script graph.

Script Quality Scorer worker (P5-S2) — `script_drafts → script_scores`.

Reads the `script_drafts` artifact produced by the Script Writer, then calls
Claude Sonnet to score each draft on four virality/quality axes plus a weighted
overall_score (0–10).

Control signal:
  "continue"  if  best_overall_score / 10.0 >= quality_threshold
  "retry"     otherwise (graph will increment iteration and re-run the writer)

The worker never inspects `state.iteration` or enforces loop bounds — that is
exclusively the graph's responsibility (P5-S4 / D057).

`quality_threshold` is read from `getattr(state, "quality_threshold", 0.8)` so
the worker is forward-compatible with `IdeaToScriptState` (P5-S5) without
importing it.

Pure worker per D040/D056.
"""

import json
from datetime import UTC, datetime
from typing import Any

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import ControlSignal, StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_writer import ScriptDraftsArtifact

_SCRIPT_QUALITY_SCORER_PROMPT_V2 = """\
You are a content quality scorer for a data-driven YouTube Shorts channel.

You will be given one or more script drafts for a 60–90 second short-form video. \
Score each draft on the following axes from 0.0 to 10.0. Avoid clustering near 7–8; \
use the full range to differentiate drafts meaningfully.

Axes:
1. hook_strength — Does the opening line grab attention within the first 10 seconds? \
1 = flat/slow opening, 10 = immediate visceral hook
2. data_quality — Are specific statistics, trends, or historic facts cited? \
1 = vague/invented claims, 10 = precise, credible, and grounding
3. narrative_flow — Does the structure progress clearly: hook → data-driven middle → \
punchy close? 1 = choppy/confused, 10 = seamless and purposeful
4. virality_potential — How likely is this to be shared or trigger a strong emotional \
response? 1 = forgettable, 10 = highly shareable
5. overall_score — Weighted composite. Apply these weights: hook_strength ×2, \
virality_potential ×2, data_quality ×1.5, narrative_flow ×1.5. \
Divide the weighted sum by 7.0 to normalize to 0–10. \
Do NOT round — keep two decimal places.

For each axis also write a one-sentence coaching note: the single most impactful \
edit that would raise that axis's score. If the axis is already ≥ 9.0, write \
"No change needed." Be specific — name the exact line, word, or missing element.

Return ONLY a JSON array with one object per draft, preserving the original \
draft_number field. No preamble, no markdown fences, no commentary. Example:
[
  {
    "draft_number": 1,
    "hook_strength": 8.5,
    "hook_coaching": "No change needed.",
    "data_quality": 7.0,
    "data_coaching": "Replace 'billions in losses' with the exact Q3 2024 figure from the FHFA report.",
    "narrative_flow": 8.0,
    "narrative_coaching": "The closing line repeats the hook — replace with a forward-looking provocation.",
    "virality_potential": 6.5,
    "virality_coaching": "Add a relatable personal-scale anchor ('that's $800/month more than your parents paid') before the closing question.",
    "overall_score": 7.57
  }
]\
"""

SCRIPT_QUALITY_SCORER_REGISTRATION = WorkerRegistration(
    worker_version="1.1.0",
    prompt_version="v2",
    prompt=_SCRIPT_QUALITY_SCORER_PROMPT_V2,
    model="claude-sonnet-4-6",
    sampling_params={},
)

_DEFAULT_QUALITY_THRESHOLD = 0.8


class ScriptDraftScore(BaseModel):
    """Scores for one script draft across four quality axes plus a weighted overall.

    Coaching fields are Optional for backward-compatibility with artifacts written
    before prompt v2 — old artifacts stored in R2 won't have them.
    """

    draft_number: int
    hook_strength: float
    hook_coaching: str | None = None
    data_quality: float
    data_coaching: str | None = None
    narrative_flow: float
    narrative_coaching: str | None = None
    virality_potential: float
    virality_coaching: str | None = None
    overall_score: float


class ScriptScoresArtifact(BaseModel):
    """Artifact body produced by the script quality scorer worker."""

    idea_title: str
    scored_drafts: list[ScriptDraftScore]
    best_draft_number: int
    best_score: float
    generated_at: datetime


def _build_user_message(idea_title: str, drafts_text: list[tuple[int, str]]) -> str:
    """Compose the Claude user message from the idea title and numbered draft scripts."""
    parts = [f"Idea: {idea_title}\n"]
    for draft_number, script in drafts_text:
        parts.append(f"--- Draft {draft_number} ---\n{script}")
    return "\n\n".join(parts)


def build_script_quality_scorer_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a script quality scorer WorkerNode bound to storage and the Anthropic API key.

    Reads `state.artifacts["script_drafts"]` → calls Claude Sonnet → parses
    per-draft scores → returns `ScriptScoresArtifact`.

    Control signal is derived from `best_overall_score / 10.0` compared against
    `getattr(state, "quality_threshold", 0.8)`:
      "continue"  if score meets threshold
      "retry"     otherwise

    Raises KeyError if `state.artifacts["script_drafts"]` is absent (Script
    Writer must run first). Raises ValueError if Claude returns non-JSON or
    malformed score objects.
    """

    async def script_quality_scorer(state: StageState) -> WorkerOutput:
        """Read script_drafts artifact, call Claude Sonnet, return ScriptScoresArtifact."""
        drafts_key = state.artifacts.get("script_drafts")
        if not drafts_key:
            raise KeyError(
                "state.artifacts['script_drafts'] is missing"
                " — run the Script Writer worker before Script Quality Scorer"
            )

        _, body = await read_artifact(storage, drafts_key)
        drafts_artifact = ScriptDraftsArtifact.model_validate(body)

        drafts_text = [(d.draft_number, d.script) for d in drafts_artifact.drafts]
        user_message = _build_user_message(drafts_artifact.idea_title, drafts_text)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=SCRIPT_QUALITY_SCORER_REGISTRATION.model,
            max_tokens=2048,
            system=SCRIPT_QUALITY_SCORER_REGISTRATION.prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        try:
            raw_scores: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"script_quality_scorer@v1 returned invalid JSON: {exc}"
                f"\nRaw response: {raw_text!r}"
            ) from exc

        scored_drafts = [ScriptDraftScore.model_validate(s) for s in raw_scores]

        best = max(scored_drafts, key=lambda s: s.overall_score)
        quality_threshold: float = getattr(state, "quality_threshold", _DEFAULT_QUALITY_THRESHOLD)
        control: ControlSignal = (
            "continue" if best.overall_score / 10.0 >= quality_threshold else "retry"
        )

        artifact = ScriptScoresArtifact(
            idea_title=drafts_artifact.idea_title,
            scored_drafts=scored_drafts,
            best_draft_number=best.draft_number,
            best_score=best.overall_score,
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact, control=control)

    return script_quality_scorer
