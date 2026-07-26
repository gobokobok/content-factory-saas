"""Evaluator worker (P5-S6) — `blueprint + normalized_context → evaluation`.

Node [2] in the Blueprint IR pipeline (D058). Single Sonnet call that combines
fact-checking, quality scoring, and signal-alignment assessment — no web_search.
Emits an EvaluationArtifact whose corrections are applied deterministically by
blueprint_merge (node [3]).

Pure worker per D040/D056.
"""

import json

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    EvaluationArtifact,
    NormalizedContext,
)
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_EVALUATOR_PROMPT_V1 = """\
You are a fact-checker and editorial evaluator for a data-driven short-form video channel.

Given a Blueprint IR and the normalised context that produced it, assess the blueprint \
across three dimensions in a single pass:

1. Factual accuracy — identify any claims that are likely wrong, unverifiable, or \
   misleading based on your training data. Do NOT use web search.
2. Quality score — rate the overall blueprint 0–10 for how well it will produce a \
   compelling, accurate, data-driven short video.
3. Signal alignment — note any mismatches between the stated angle / evidence and what \
   the blueprint actually plans to say.

Return ONLY a single JSON object (no markdown fences):
{
  "score": <float 0–10>,
  "factual_corrections": ["correction or note on claim that needs fixing"],
  "alignment_notes": "updated direction_alignment_notes paragraph",
  "evidence_additions": ["additional data point or source to add to required_evidence"],
  "passed": <true if score >= 7.0>,
  "notes": "brief overall assessment"
}

Rules:
- `factual_corrections` is empty [] when all claims are accurate
- `evidence_additions` is empty [] when required_evidence is sufficient
- `alignment_notes` can repeat the original if alignment is fine
- Be conservative: only flag things you are confident are wrong
\
"""

EVALUATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_EVALUATOR_PROMPT_V1,
    model="claude-sonnet-4-6",
    sampling_params={},
)


def build_evaluator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return an evaluator WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['blueprint']           → Blueprint
      state.artifacts['normalized_context']  → NormalizedContext

    Makes one Sonnet call combining fact-check + score + alignment.
    Raises ValueError on JSON parse failure.
    """

    async def evaluator(state: StageState) -> WorkerOutput:
        """Read blueprint + context, call Claude Sonnet, return EvaluationArtifact."""
        bp_key = state.artifacts.get("blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['blueprint'] missing — "
                "blueprint_generation must run before evaluation"
            )
        ctx_key = state.artifacts.get("normalized_context")
        if not ctx_key:
            raise KeyError(
                "state.artifacts['normalized_context'] missing — "
                "context_normalization must run before evaluation"
            )

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        _, ctx_body = await read_artifact(storage, ctx_key)
        ctx = NormalizedContext.model_validate(ctx_body)

        niche: str | None = state.inputs.get("niche")
        user_message = _build_user_message(niche, blueprint, ctx)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=90.0)
        response = await client.messages.create(
            model=EVALUATOR_REGISTRATION.model,
            max_tokens=2048,
            system=_EVALUATOR_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = extract_json_object(response.content[0].text)
        try:
            raw_dict = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"evaluator@v1 returned invalid JSON: {exc}\nRaw: {raw_text!r}"
            ) from exc

        artifact = EvaluationArtifact(
            score=float(raw_dict.get("score", 7.0)),
            factual_corrections=list(raw_dict.get("factual_corrections", [])),
            alignment_notes=str(raw_dict.get("alignment_notes", blueprint.direction_alignment_notes)),
            evidence_additions=list(raw_dict.get("evidence_additions", [])),
            passed=bool(raw_dict.get("passed", True)),
            notes=str(raw_dict.get("notes", "")),
        )
        return WorkerOutput(artifact=artifact)

    return evaluator


def _build_user_message(
    niche: str | None,
    blueprint: Blueprint,
    ctx: NormalizedContext,
) -> str:
    """Compose the Claude user message for the evaluation call."""
    parts = []
    if niche:
        parts.append(f"Channel niche: {niche}")
    parts.append(f"Primary angle: {ctx.primary_angle}")
    parts.append("")
    parts.append("=== BLUEPRINT IR ===")
    parts.append(f"Hook angle: {blueprint.hook_angle}")
    parts.append(f"Claims: {json.dumps(blueprint.claims)}")
    parts.append(f"Required evidence: {json.dumps(blueprint.required_evidence)}")
    parts.append(f"Direction alignment: {blueprint.direction_alignment_notes}")
    parts.append("")
    parts.append("=== AVAILABLE CONTEXT ===")
    parts.append(f"Evidence summary: {ctx.evidence_summary}")
    if ctx.top_signals:
        parts.append(f"Top signals: {'; '.join(ctx.top_signals)}")
    parts.append("")
    parts.append("Evaluate the blueprint and return the JSON assessment.")
    return "\n".join(parts)
