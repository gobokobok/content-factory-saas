"""Script Refiner worker (P5-S4) — `script_drafts + script_scores + factcheck_report → script_drafts`.

Reads the best-scoring draft (from `script_scores`) together with the factcheck
report and produces a refined `ScriptDraftsArtifact` containing one corrected,
improved script. The artifact key is still "script_drafts" — the immutable
artifact store writes a new version so the scorer and fact-checker in the next
iteration evaluate the improved text.

The refiner always returns `control="continue"`. It is the graph's conditional
edge (P5-S4 loop) that decides whether another iteration is needed.

Pure worker per D040/D056.
"""

import json
from datetime import datetime, timezone
from typing import Any

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.fact_checker import FactcheckReportArtifact
from cf_platform.workers.script_quality_scorer import ScriptScoresArtifact
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

_SCRIPT_REFINER_PROMPT_V1 = """\
You are a script editor for "The Housing Equation", a data-driven YouTube Shorts \
channel about American housing economics.

You will receive:
1. A script draft that has been scored and fact-checked
2. The quality scores for that draft (hook_strength, data_quality, narrative_flow, \
virality_potential, overall_score — all 0–10)
3. Fact-check results: a list of claims with verdicts (supported / refuted / unverifiable)

Your job is to produce one refined, improved version of the script that:
- Corrects or removes any refuted or unverifiable factual claims (replace with \
verified alternatives or reframe without the specific number)
- Addresses the weakest scoring axes (lowest-scoring axes should be visibly improved)
- Preserves the core topic, angle, and approximate length (150–200 words)
- Keeps the hook in the first 10 seconds, a data-driven middle, and a punchy close

Return ONLY a JSON array with exactly one object. No preamble, no markdown fences. \
Example:
[
  {
    "draft_number": 1,
    "script": "In 1980, the average American could afford a home after 3 years of saving. \
Today that figure has quadrupled. Here is why..."
  }
]\
"""

SCRIPT_REFINER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_SCRIPT_REFINER_PROMPT_V1,
    model="claude-sonnet-4-6",
    sampling_params={},
)


def _build_user_message(
    idea_title: str,
    best_script: str,
    scores_text: str,
    claims_text: str,
) -> str:
    """Compose the Claude user message from the best draft, its scores, and claim verdicts."""
    return (
        f"Idea: {idea_title}\n\n"
        f"--- Best Draft ---\n{best_script}\n\n"
        f"--- Quality Scores ---\n{scores_text}\n\n"
        f"--- Fact-Check Results ---\n{claims_text}"
    )


def _format_scores(scores_artifact: ScriptScoresArtifact) -> str:
    """Format the best draft's scores as a readable summary for the prompt."""
    best = next(
        (s for s in scores_artifact.scored_drafts if s.draft_number == scores_artifact.best_draft_number),
        scores_artifact.scored_drafts[0],
    )
    return (
        f"hook_strength: {best.hook_strength}\n"
        f"data_quality: {best.data_quality}\n"
        f"narrative_flow: {best.narrative_flow}\n"
        f"virality_potential: {best.virality_potential}\n"
        f"overall_score: {best.overall_score}"
    )


def _format_claims(report: FactcheckReportArtifact) -> str:
    """Format the fact-check claims as a bullet list for the prompt."""
    if not report.claims:
        return "(no factual claims identified)"
    lines = []
    for c in report.claims:
        lines.append(f"- [{c.verdict.upper()}] {c.claim}\n  Note: {c.note}")
    return "\n".join(lines)


def build_script_refiner_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a script refiner WorkerNode bound to storage and the Anthropic API key.

    Reads `state.artifacts["script_drafts"]`, `state.artifacts["script_scores"]`, and
    `state.artifacts["factcheck_report"]` → calls Claude Sonnet with the best draft,
    its quality scores, and the claim verdicts → returns a refined `ScriptDraftsArtifact`
    with exactly one corrected draft (draft_number=1).

    Always returns `control="continue"` — the graph edge decides whether another
    iteration is warranted.

    Raises KeyError if any of the three required artifacts are missing from state.
    Raises ValueError if Claude returns non-JSON or a malformed draft object.
    """

    async def script_refiner(state: StageState) -> WorkerOutput:
        """Read best draft + scores + claims, call Claude Sonnet, return refined ScriptDraftsArtifact."""
        for key in ("script_drafts", "script_scores", "factcheck_report"):
            if not state.artifacts.get(key):
                raise KeyError(
                    f"state.artifacts['{key}'] is missing"
                    " — script_writer, script_quality_scorer, and fact_checker must run first"
                )

        _, drafts_body = await read_artifact(storage, state.artifacts["script_drafts"])
        _, scores_body = await read_artifact(storage, state.artifacts["script_scores"])
        _, factcheck_body = await read_artifact(storage, state.artifacts["factcheck_report"])

        drafts_artifact = ScriptDraftsArtifact.model_validate(drafts_body)
        scores_artifact = ScriptScoresArtifact.model_validate(scores_body)
        factcheck_report = FactcheckReportArtifact.model_validate(factcheck_body)

        best_draft = next(
            (d for d in drafts_artifact.drafts if d.draft_number == scores_artifact.best_draft_number),
            drafts_artifact.drafts[0],
        )

        user_message = _build_user_message(
            idea_title=drafts_artifact.idea_title,
            best_script=best_draft.script,
            scores_text=_format_scores(scores_artifact),
            claims_text=_format_claims(factcheck_report),
        )

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=SCRIPT_REFINER_REGISTRATION.model,
            max_tokens=1024,
            system=SCRIPT_REFINER_REGISTRATION.prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        try:
            raw_drafts: list[dict[str, Any]] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"script_refiner@v1 returned invalid JSON: {exc}"
                f"\nRaw response: {raw_text!r}"
            ) from exc

        drafts = [ScriptDraft.model_validate(d) for d in raw_drafts]
        artifact = ScriptDraftsArtifact(
            niche=drafts_artifact.niche,
            idea_title=drafts_artifact.idea_title,
            idea_angle=drafts_artifact.idea_angle,
            drafts=drafts,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact, control="continue")

    return script_refiner
