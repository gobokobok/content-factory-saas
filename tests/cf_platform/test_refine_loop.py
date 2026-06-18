"""DEPRECATED — replaced by test_blueprint_graph.py (P5-S6).

The cyclic write→score→fact-check→refine loop was replaced by the Blueprint IR
pipeline in P5-S6 (D058). Graph topology tests now live in test_blueprint_graph.py.
The wrap() control_channel tests are retained here since they test infrastructure,
not the old graph topology.
"""

from datetime import datetime, timezone

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.schemas import StageState, WorkerOutput
from cf_platform.core.worker_registry import (
    InMemoryExecutionRepository,
    WorkerRegistry,
    WorkerRegistration,
    wrap,
)
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


# ── wrap() control_channel tests (infrastructure, not graph-topology) ──


@pytest.mark.asyncio
async def test_wrap_emits_control_signal_when_channel_set():
    """wrap() with control_channel includes the signal in its return dict."""
    storage = InMemoryArtifactStorage()
    executions = InMemoryExecutionRepository()
    artifact_repo = InMemoryArtifactRepository()
    registry = WorkerRegistry()
    reg = WorkerRegistration(
        worker_version="1.0.0", prompt_version="v1", prompt="p", model="none"
    )
    registry.register("test_worker", reg)

    artifact_body = ScriptDraftsArtifact(
        niche="housing", idea_title="Test", idea_angle=None,
        drafts=[ScriptDraft(draft_number=1, script="s")], generated_at=_NOW
    )

    async def my_worker(state: StageState) -> WorkerOutput:
        return WorkerOutput(artifact=artifact_body, control="retry")

    wrapped = wrap(
        "test_worker",
        "script_drafts",
        my_worker,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
        control_channel="integrity_verdict",
    )

    state = StageState(run_id="r1", user_id="u", inputs={})
    result = await wrapped(state)

    assert result["integrity_verdict"] == "retry"
    assert "artifacts" in result


@pytest.mark.asyncio
async def test_wrap_no_control_channel_omits_signal():
    """wrap() without control_channel does not include any extra field."""
    storage = InMemoryArtifactStorage()
    executions = InMemoryExecutionRepository()
    artifact_repo = InMemoryArtifactRepository()
    registry = WorkerRegistry()
    reg = WorkerRegistration(
        worker_version="1.0.0", prompt_version="v1", prompt="p", model="none"
    )
    registry.register("test_worker2", reg)

    artifact_body = ScriptDraftsArtifact(
        niche=None, idea_title="T", idea_angle=None,
        drafts=[ScriptDraft(draft_number=1, script="s")], generated_at=_NOW
    )

    async def my_worker(state: StageState) -> WorkerOutput:
        return WorkerOutput(artifact=artifact_body, control="retry")

    wrapped = wrap(
        "test_worker2",
        "script_drafts",
        my_worker,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    state = StageState(run_id="r2", user_id="u", inputs={})
    result = await wrapped(state)

    assert list(result.keys()) == ["artifacts"]
