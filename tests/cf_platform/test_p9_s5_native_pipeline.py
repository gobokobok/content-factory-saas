"""Tests for P9-S5 — native pipeline wiring (StoryboardWorker + AcquisitionWorker + RenderWorker).

Covers:
- Pipeline topology includes all three native workers in correct order
- storyboard_node passes script + voice_alignment into the storyboard subgraph
- acquisition_node passes verified_storyboard into the acquisition subgraph
- render_node passes verified_storyboard + asset_manifest + voice_alignment to the render subgraph
- render_node extracts video_key from RenderArtifact envelope
- voice_alignment forwarded to storyboard_node and render_node
- legacy_adapter kwarg accepted but not called (deprecation contract)
- InProcessLegacyVideoAdapter importable (D047 src/ isolation preserved)
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.adapters.legacy_video import InProcessLegacyVideoAdapter, LegacyVideoAdapter
from cf_platform.core.schemas import (
    IdeaToScriptState,
    NicheToIdeasState,
    PipelineState,
    StageState,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.workers.render_worker import RenderArtifact

# ── Helpers ───────────────────────────────────────────────────────────────────

_RUN_ID = "run-p9s5-test"
_USER_ID = "operator"

_META: Any = MagicMock()


def _stage(artifact_key: str, r2: str, run_id: str = _RUN_ID) -> StageState:
    """Build a minimal StageState simulating a worker subgraph result."""
    return StageState(run_id=run_id, user_id=_USER_ID, inputs={}, artifacts={artifact_key: r2})


def _make_render_body(video_key: str = "runs/test/output/final.mp4") -> dict:
    """Build a RenderArtifact body dict for read_artifact mocking."""
    return RenderArtifact(
        render_script_key="runs/test/render_script.sh",
        video_key=video_key,
        scene_count=3,
        duration_s=30.0,
        generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _build_graph(**extra_kwargs: Any) -> tuple[Any, Any, Any]:
    """Compile the pipeline with patched sub-graphs; return (graph, run_graph_mock, read_artifact_mock)."""
    mock_run_graph = AsyncMock()
    mock_read_artifact = AsyncMock()
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
            **extra_kwargs,
        )
    return graph, mock_run_graph, mock_read_artifact


# ── Importability / deprecation contract ──────────────────────────────────────


def test_inprocess_legacy_adapter_still_importable() -> None:
    """InProcessLegacyVideoAdapter class is importable — D047 contract preserved."""
    # Check class-level attribute without constructing (constructor loads src/ Settings)
    assert hasattr(InProcessLegacyVideoAdapter, "render")


def test_legacy_video_adapter_protocol_importable() -> None:
    """LegacyVideoAdapter Protocol remains importable for type-checking."""
    # Protocol import check — no assertion beyond "does not raise"
    assert LegacyVideoAdapter is not None


def test_legacy_adapter_kwarg_does_not_call_render() -> None:
    """Passing legacy_adapter to build_full_pipeline_graph does NOT call adapter.render."""
    mock_adapter = MagicMock()
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
    ):
        build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
            legacy_adapter=mock_adapter,
        )
    mock_adapter.render.assert_not_called()


# ── storyboard_node ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_storyboard_node_passes_script_key() -> None:
    """storyboard_node feeds script artifact key from PipelineState into the storyboard subgraph."""
    script_r2 = "r2://script@v1.json"
    sb_r2 = "r2://sb@v1.json"
    render_r2 = "r2://render_artifact@v1.json"
    video_r2 = "runs/test/output/final.mp4"

    captured_sb_states: list[StageState] = []

    async def capture(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _stage("ranked_ideas", "r2://ranked@v1")
        if isinstance(state, IdeaToScriptState):
            return _stage("script", script_r2)
        if "youtube_metadata" in thread_id:
            return _stage("youtube_metadata", "r2://meta@v1")
        if "voice_production" in thread_id:
            return _stage("voice_alignment", "r2://voice@v1")
        if "storyboard_worker" in thread_id:
            captured_sb_states.append(state)
            return _stage("verified_storyboard", sb_r2)
        if "visual_director_worker" in thread_id:
            return _stage("visual_treatment", "r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _stage("asset_manifest", "r2://mf@v1")
        return _stage("render_artifact", render_r2)

    # idea_title is set → idea_to_script_node skips ranked_ideas read.
    # Only one read_artifact call: render_node reads RenderArtifact.
    mock_read_artifact = AsyncMock(side_effect=[
        (_META, _make_render_body(video_key=video_r2)),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, idea_title="Test Idea")
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "sb-test"}})

    assert len(captured_sb_states) == 1
    assert captured_sb_states[0].artifacts["script"] == script_r2


@pytest.mark.asyncio
async def test_storyboard_node_forwards_voice_alignment() -> None:
    """storyboard_node includes voice_alignment in the subgraph state when present."""
    voice_r2 = "r2://voice@v1.json"
    render_r2 = "r2://render@v1.json"
    video_r2 = "runs/test/output/final.mp4"

    captured_sb_states: list[StageState] = []

    async def capture(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _stage("ranked_ideas", "r2://ranked@v1")
        if isinstance(state, IdeaToScriptState):
            return _stage("script", "r2://script@v1")
        if "youtube_metadata" in thread_id:
            return _stage("youtube_metadata", "r2://meta@v1")
        if "voice_production" in thread_id:
            return _stage("voice_alignment", voice_r2)
        if "storyboard_worker" in thread_id:
            captured_sb_states.append(state)
            return _stage("verified_storyboard", "r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _stage("visual_treatment", "r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _stage("asset_manifest", "r2://mf@v1")
        return _stage("render_artifact", render_r2)

    # idea_title set → no ranked_ideas read; only render_node reads RenderArtifact.
    mock_read_artifact = AsyncMock(side_effect=[
        (_META, _make_render_body(video_key=video_r2)),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, idea_title="Test")
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "va-test"}})

    assert captured_sb_states[0].artifacts.get("voice_alignment") == voice_r2


# ── acquisition_node ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquisition_node_receives_verified_storyboard() -> None:
    """acquisition_node feeds verified_storyboard artifact key into the acquisition subgraph."""
    sb_r2 = "r2://verified_storyboard@v1.json"
    render_r2 = "r2://render@v1.json"
    video_r2 = "runs/test/output/final.mp4"

    captured_acq_states: list[StageState] = []

    async def capture(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _stage("ranked_ideas", "r2://ranked@v1")
        if isinstance(state, IdeaToScriptState):
            return _stage("script", "r2://script@v1")
        if "youtube_metadata" in thread_id:
            return _stage("youtube_metadata", "r2://meta@v1")
        if "voice_production" in thread_id:
            return _stage("voice_alignment", "r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _stage("verified_storyboard", sb_r2)
        if "visual_director_worker" in thread_id:
            return _stage("visual_treatment", "r2://vt@v1")
        if "acquisition_worker" in thread_id:
            captured_acq_states.append(state)
            return _stage("asset_manifest", "r2://mf@v1")
        return _stage("render_artifact", render_r2)

    # idea_title set → no ranked_ideas read; only render_node reads RenderArtifact.
    mock_read_artifact = AsyncMock(side_effect=[
        (_META, _make_render_body(video_key=video_r2)),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, idea_title="Test")
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "acq-test"}})

    assert captured_acq_states[0].artifacts["verified_storyboard"] == sb_r2


# ── render_node ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_node_receives_all_three_inputs() -> None:
    """render_node feeds verified_storyboard + asset_manifest + voice_alignment into render subgraph."""
    sb_r2 = "r2://sb@v1.json"
    mf_r2 = "r2://mf@v1.json"
    voice_r2 = "r2://voice@v1.json"
    render_r2 = "r2://render@v1.json"
    video_r2 = "runs/test/output/final.mp4"

    captured_render_states: list[StageState] = []

    async def capture(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _stage("ranked_ideas", "r2://ranked@v1")
        if isinstance(state, IdeaToScriptState):
            return _stage("script", "r2://script@v1")
        if "youtube_metadata" in thread_id:
            return _stage("youtube_metadata", "r2://meta@v1")
        if "voice_production" in thread_id:
            return _stage("voice_alignment", voice_r2)
        if "storyboard_worker" in thread_id:
            return _stage("verified_storyboard", sb_r2)
        if "visual_director_worker" in thread_id:
            return _stage("visual_treatment", "r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _stage("asset_manifest", mf_r2)
        captured_render_states.append(state)
        return _stage("render_artifact", render_r2)

    # idea_title set → no ranked_ideas read; only render_node reads RenderArtifact.
    mock_read_artifact = AsyncMock(side_effect=[
        (_META, _make_render_body(video_key=video_r2)),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, idea_title="Test")
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "render-test"}})

    assert len(captured_render_states) == 1
    render_state = captured_render_states[0]
    assert render_state.artifacts["verified_storyboard"] == sb_r2
    assert render_state.artifacts["asset_manifest"] == mf_r2
    assert render_state.artifacts["voice_alignment"] == voice_r2


@pytest.mark.asyncio
async def test_render_node_video_key_is_raw_mp4_path() -> None:
    """render_node extracts video_key from RenderArtifact; artifacts['video'] is the raw MP4 R2 path."""
    video_r2 = "runs/p9s5-run/output/final.mp4"
    render_r2 = "users/op/runs/p9s5/render/render_artifact@v1.json"

    async def run_graph_stub(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _stage("ranked_ideas", "r2://ranked@v1")
        if isinstance(state, IdeaToScriptState):
            return _stage("script", "r2://script@v1")
        if "youtube_metadata" in thread_id:
            return _stage("youtube_metadata", "r2://meta@v1")
        if "voice_production" in thread_id:
            return _stage("voice_alignment", "r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _stage("verified_storyboard", "r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _stage("visual_treatment", "r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _stage("asset_manifest", "r2://mf@v1")
        return _stage("render_artifact", render_r2)

    # idea_title set → no ranked_ideas read; only render_node reads RenderArtifact.
    mock_read_artifact = AsyncMock(side_effect=[
        (_META, _make_render_body(video_key=video_r2)),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=run_graph_stub),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={}, idea_title="Test")
        result = await graph.ainvoke(initial, config={"configurable": {"thread_id": "vk-test"}})

    # artifacts["video"] must be the raw MP4 path, not the RenderArtifact JSON path
    assert result["artifacts"]["video"] == video_r2
    assert result["artifacts"]["video"] != render_r2


# ── Node graph registration ───────────────────────────────────────────────────


def test_registry_registers_all_three_native_workers() -> None:
    """build_full_pipeline_graph registers storyboard_worker, acquisition_worker, render_worker."""
    mock_registry = MagicMock()
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
    ):
        build_full_pipeline_graph(
            storage=MagicMock(),
            registry=mock_registry,
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
        )

    registered_names = [call.args[0] for call in mock_registry.register.call_args_list]
    assert "storyboard_worker" in registered_names
    assert "visual_director_worker" in registered_names
    assert "acquisition_worker" in registered_names
    assert "render_worker" in registered_names
