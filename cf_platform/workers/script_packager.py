"""Script Packager worker (P5-S5) — `script_drafts + script_scores → script`.

Terminal worker in the idea→script block. Reads the final `script_drafts` and
`script_scores` artifacts, picks the best-scoring draft identified by
`ScriptScoresArtifact.best_draft_number`, and emits a `ScriptArtifact` as the
block's terminal output.

No LLM call — pure deterministic selection (model="none"). The refine loop
(P5-S4) ensures drafts are of acceptable quality before this node runs.

Pure worker per D040/D056.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_quality_scorer import ScriptScoresArtifact
from cf_platform.workers.script_writer import ScriptDraftsArtifact

SCRIPT_PACKAGER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="",
    model="none",
    sampling_params={},
)


class ScriptArtifact(BaseModel):
    """Terminal artifact of the idea→script block — the selected, quality-approved script."""

    idea_title: str
    niche: Optional[str]
    script: str
    draft_number: int
    overall_score: float
    generated_at: datetime


def build_script_packager_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a script packager WorkerNode bound to storage.

    Reads `state.artifacts["script_drafts"]` and `state.artifacts["script_scores"]`,
    locates the draft whose `draft_number` matches `ScriptScoresArtifact.best_draft_number`,
    and emits a `ScriptArtifact` as the terminal output of the idea→script block.

    Raises KeyError if either artifact reference is absent.
    Raises ValueError if `best_draft_number` does not match any draft in `script_drafts`.
    """

    async def script_packager(state: StageState) -> WorkerOutput:
        """Pick the best draft from script_drafts using best_draft_number from script_scores."""
        drafts_key = state.artifacts.get("script_drafts")
        if not drafts_key:
            raise KeyError(
                "state.artifacts['script_drafts'] is missing"
                " — Script Writer must run before Script Packager"
            )
        scores_key = state.artifacts.get("script_scores")
        if not scores_key:
            raise KeyError(
                "state.artifacts['script_scores'] is missing"
                " — Script Quality Scorer must run before Script Packager"
            )

        _, drafts_body = await read_artifact(storage, drafts_key)
        drafts_artifact = ScriptDraftsArtifact.model_validate(drafts_body)

        _, scores_body = await read_artifact(storage, scores_key)
        scores_artifact = ScriptScoresArtifact.model_validate(scores_body)

        best_number = scores_artifact.best_draft_number
        best_draft = next(
            (d for d in drafts_artifact.drafts if d.draft_number == best_number),
            None,
        )
        if best_draft is None:
            raise ValueError(
                f"script_packager: best_draft_number={best_number} not found in"
                f" script_drafts (available: {[d.draft_number for d in drafts_artifact.drafts]})"
            )

        artifact = ScriptArtifact(
            idea_title=drafts_artifact.idea_title,
            niche=drafts_artifact.niche,
            script=best_draft.script,
            draft_number=best_number,
            overall_score=scores_artifact.best_score,
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return script_packager
