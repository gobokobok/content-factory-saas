"""P-HARD1-S2 — a failed voice job reads "error" with the reason, never "complete" with no audio.

PROD 2026-10-10, run 6fe35dab: the TTS call failed, the worker fell back to proportional
timing and the job finished "complete" with no audio. The worker now raises; the job
document and the status route must carry the reason so the UI can show it with Retry.
"""

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import StageState
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID
from cf_platform.interfaces.routes.studio import studio_get_voice_status
from cf_platform.interfaces.routes.workers import _run_voice_background
from cf_platform.workers.voice_production import VoiceGenerationError

RUN = "run-hard1"


def _state() -> StageState:
    """A minimal stage state for the background task."""
    return StageState(run_id=RUN, user_id=PLATFORM_USER_ID, inputs={}, artifacts={})


@pytest.mark.asyncio
async def test_failed_tts_job_reports_error_with_reason() -> None:
    """The job document says error + reason, and the status route returns both."""
    storage = InMemoryArtifactStorage()

    async def failing_worker(state: StageState):
        raise VoiceGenerationError("The voice provider failed: RuntimeError: quota. Retry the voiceover.")

    await _run_voice_background(RUN, "job-1", _state(), failing_worker, storage)

    job = await storage.get_json(f"runs/{RUN}/voice/current_job.json")
    assert job["status"] == "error"
    assert "quota" in job["error"]

    status = await studio_get_voice_status(RUN, storage)
    assert status["status"] == "error"
    assert "Retry" in status["error"]


@pytest.mark.asyncio
async def test_failed_job_leaves_no_voice_alignment_artifact() -> None:
    """Nothing is written as the run's voice when the TTS failed."""
    storage = InMemoryArtifactStorage()

    async def failing_worker(state: StageState):
        raise VoiceGenerationError("not configured")

    await _run_voice_background(RUN, "job-2", _state(), failing_worker, storage)

    keys = await storage.list_keys(f"users/{PLATFORM_USER_ID}/runs/{RUN}/voice/")
    assert keys == []


def test_idea_to_script_request_bounds_max_iterations() -> None:
    """P-HARD1-S1 F4: a client cannot ask for an unbounded number of paid LLM drafts."""
    from pydantic import ValidationError

    from cf_platform.interfaces.routes.blocks import IdeaToScriptRequest

    assert IdeaToScriptRequest(idea_title="x", max_iterations=5).max_iterations == 5
    for bad in (0, 6, 500):
        with pytest.raises(ValidationError):
            IdeaToScriptRequest(idea_title="x", max_iterations=bad)
