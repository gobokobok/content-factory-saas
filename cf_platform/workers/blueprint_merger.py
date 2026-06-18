"""Blueprint Merger worker (P5-S6) — `blueprint + evaluation → merged_blueprint`.

Node [3] in the Blueprint IR pipeline (D058). Pure deterministic function —
zero LLM calls. Applies the factual corrections and evidence additions from the
EvaluationArtifact to produce an updated Blueprint artifact.

Pure worker per D040/D056.
"""

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, EvaluationArtifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

BLUEPRINT_MERGER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",  # no LLM prompt — deterministic node
    model="none",
    sampling_params={},
)


def build_blueprint_merger_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a blueprint merger WorkerNode bound to storage.

    Reads:
      state.artifacts['blueprint']   → Blueprint (original)
      state.artifacts['evaluation']  → EvaluationArtifact

    Applies evaluation corrections deterministically and emits a merged Blueprint.
    Raises KeyError if either artifact reference is absent.
    """

    async def blueprint_merger(state: StageState) -> WorkerOutput:
        """Merge evaluation corrections into the blueprint; return updated Blueprint."""
        bp_key = state.artifacts.get("blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['blueprint'] missing — "
                "blueprint_generation must run before blueprint_merge"
            )
        eval_key = state.artifacts.get("evaluation")
        if not eval_key:
            raise KeyError(
                "state.artifacts['evaluation'] missing — "
                "evaluation must run before blueprint_merge"
            )

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        _, eval_body = await read_artifact(storage, eval_key)
        evaluation = EvaluationArtifact.model_validate(eval_body)

        merged = _merge(blueprint, evaluation)
        return WorkerOutput(artifact=merged)

    return blueprint_merger


def _merge(blueprint: Blueprint, evaluation: EvaluationArtifact) -> Blueprint:
    """Apply evaluation corrections to blueprint; return a new Blueprint instance."""
    updated_claims = list(blueprint.claims)
    for correction in evaluation.factual_corrections:
        # Append corrections as annotated notes; the script writer interprets them
        updated_claims.append(f"[correction] {correction}")

    updated_evidence = list(blueprint.required_evidence)
    for addition in evaluation.evidence_additions:
        if addition not in updated_evidence:
            updated_evidence.append(addition)

    # Use evaluation's alignment_notes if non-empty; keep original otherwise
    alignment_notes = (
        evaluation.alignment_notes.strip()
        or blueprint.direction_alignment_notes
    )

    return Blueprint(
        hook_angle=blueprint.hook_angle,
        structure=blueprint.structure,
        claims=updated_claims,
        monetization_angle=blueprint.monetization_angle,
        required_evidence=updated_evidence,
        signal_summary=blueprint.signal_summary,
        direction_alignment_notes=alignment_notes,
    )
