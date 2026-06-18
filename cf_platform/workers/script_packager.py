"""Script Packager worker (P5-S6) — `generated_script → script`.

Terminal worker in the idea→script block. Reads the final GeneratedScriptArtifact
(from script_generation or apply_patch), emits a ScriptArtifact as the block's
terminal output. Sets status='manual_review' when the graph exhausted all
integrity repair attempts.

No LLM call — pure deterministic selection (model="none").

Pure worker per D040/D056.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import GeneratedScriptArtifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

SCRIPT_PACKAGER_REGISTRATION = WorkerRegistration(
    worker_version="2.0.0",
    prompt_version="v2",
    prompt="",
    model="none",
    sampling_params={},
)

# Maximum integrity repair cycles from the block graph (D058).
_MAX_INTEGRITY_LOOPS = 2


class ScriptArtifact(BaseModel):
    """Terminal artifact of the idea→script block — the selected, quality-approved script."""

    idea_title: str
    niche: Optional[str]
    script: str
    word_count: int = 0
    overall_score: Optional[float] = None  # not computed in Blueprint IR pipeline (P5-S6)
    draft_number: Optional[int] = None  # not applicable in Blueprint IR pipeline
    status: Literal["ok", "manual_review"] = "ok"
    generated_at: datetime


def build_script_packager_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a script packager WorkerNode bound to storage.

    Reads state.artifacts['generated_script'] → GeneratedScriptArtifact.
    Sets status='manual_review' when state.integrity_loops >= _MAX_INTEGRITY_LOOPS
    and state.integrity_verdict == 'retry' (integrity repair exhausted).

    Raises KeyError if the generated_script artifact reference is absent.
    """

    async def script_packager(state: StageState) -> WorkerOutput:
        """Pick final script from generated_script artifact; set status if manual_review."""
        script_key = state.artifacts.get("generated_script")
        if not script_key:
            raise KeyError(
                "state.artifacts['generated_script'] missing — "
                "script_generation must run before script_packager"
            )

        _, script_body = await read_artifact(storage, script_key)
        generated = GeneratedScriptArtifact.model_validate(script_body)

        # Determine if we exhausted integrity repair attempts
        integrity_loops: int = int(getattr(state, "integrity_loops", 0))
        integrity_verdict: str = str(getattr(state, "integrity_verdict", "continue"))
        is_manual_review = (
            integrity_verdict == "retry" and integrity_loops >= _MAX_INTEGRITY_LOOPS
        )

        artifact = ScriptArtifact(
            idea_title=generated.idea_title,
            niche=generated.niche,
            script=generated.script,
            word_count=generated.word_count,
            overall_score=None,
            draft_number=None,
            status="manual_review" if is_manual_review else "ok",
            generated_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact)

    return script_packager
