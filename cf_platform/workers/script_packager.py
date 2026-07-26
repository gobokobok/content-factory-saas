"""Script Packager worker (P5-S6) — `generated_script → script`.

Terminal worker in the idea→script block. Reads the final GeneratedScriptArtifact
(from script_generation or apply_patch), emits a ScriptArtifact as the block's
terminal output. Sets status='manual_review' when the graph exhausted all
integrity repair attempts.

No LLM call — pure deterministic selection (model="none").

Pure worker per D040/D056.
"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import GeneratedScriptArtifact
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_WORDS_PER_SECOND = 160 / 60  # standard narration pace
_LENGTH_TOLERANCE = 0.20  # 20% over/under target_words triggers length_ok=False

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
    niche: str | None
    script: str
    word_count: int = 0
    overall_score: float | None = None  # not computed in Blueprint IR pipeline (P5-S6)
    draft_number: int | None = None  # not applicable in Blueprint IR pipeline
    status: Literal["ok", "manual_review"] = "ok"
    length_ok: bool = True  # False when word_count is >20% over or under target_words (P6-S5)
    generated_at: datetime


def build_script_packager_worker(storage: ArtifactStorage) -> WorkerNode:
    """Return a script packager WorkerNode bound to storage.

    Reads state.artifacts['generated_script'] → GeneratedScriptArtifact.
    Sets status='manual_review' when state.integrity_loops >= _MAX_INTEGRITY_LOOPS
    and state.integrity_verdict == 'retry' (integrity repair exhausted).
    Sets length_ok=False when word_count is >20% over or under the target_words
    derived from generated.target_duration_seconds (P6-S5, deterministic — no LLM).

    Raises KeyError if the generated_script artifact reference is absent.
    """

    async def script_packager(state: StageState) -> WorkerOutput:
        """Pick final script from generated_script artifact; set status and length_ok."""
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

        # Deterministic length check — no LLM call (P6-S5)
        target_words = round(generated.target_duration_seconds * _WORDS_PER_SECOND)
        length_ok = (
            abs(generated.word_count - target_words) / max(target_words, 1)
            <= _LENGTH_TOLERANCE
        )

        artifact = ScriptArtifact(
            idea_title=generated.idea_title,
            niche=generated.niche,
            script=generated.script,
            word_count=generated.word_count,
            overall_score=None,
            draft_number=None,
            status="manual_review" if is_manual_review else "ok",
            length_ok=length_ok,
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact)

    return script_packager
