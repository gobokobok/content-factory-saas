"""Tests for cf_platform/orchestrator/full_pipeline.py (P6-S2)."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.adapters.legacy_video import VideoResult
from cf_platform.core.schemas import (
    IdeaToScriptState,
    NicheToIdeasState,
    PipelineState,
    StageState,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact

# ── Fixtures ──────────────────────────────────────────────────────────────────

_RUN_ID = "run-p6s2-test"
_USER_ID = "operator"

_FAKE_ARTIFACT_META: Any = MagicMock()  # Artifact envelope — not inspected by node code


def _make_ranked_body(title: str = "Housing Crisis", niche: str = "american housing") -> dict:
    """Build a RankedIdeasArtifact-shaped dict for read_artifact mock returns."""
    score = TopicScore(
        title=title,
        angle="explainer",
        novelty=8.0,
        audience_relevance=9.0,
        emotional_trigger=7.0,
        search_demand=8.5,
        competition=6.0,
        evergreen_potential=9.0,
        monetization_relevance=8.0,
        final_score=8.5,
    )
    artifact = RankedIdeasArtifact(
        niche=niche,
        generated_at=datetime.now(timezone.utc),
        selected=score,
        alternatives=[],
        mode="single",
    )
    return artifact.model_dump(mode="json")


def _make_script_body(script: str = "Housing prices are rising.") -> dict:
    """Build a ScriptArtifact-shaped dict for read_artifact mock returns."""
    artifact = ScriptArtifact(
        idea_title="Housing Crisis",
        niche="american housing",
        script=script,
        word_count=4,
        generated_at=datetime.now(timezone.utc),
    )
    return artifact.model_dump(mode="json")


def _make_voice_body(run_id: str = _RUN_ID) -> dict:
    """Build a VoiceAlignmentArtifact-shaped dict for read_artifact mock returns."""
    return {
        "mp3_r2_key": f"runs/{run_id}/voiceover/generated.mp3",
        "word_timestamps": [],
        "alignment_method": "proportional_fallback",
        "total_duration_s": 30.0,
    }


def _make_metadata_result(run_id: str = _RUN_ID, metadata_r2: str = "r2://metadata@v1.json") -> StageState:
    """Fake StageState returned by the youtube_metadata observed graph."""
    return StageState(
        run_id=run_id,
        user_id=_USER_ID,
        inputs={},
        artifacts={"youtube_metadata": metadata_r2},
    )


def _make_voice_result(run_id: str = _RUN_ID, voice_r2: str = "r2://voice@v1.json") -> StageState:
    """Fake StageState returned by the voice_production observed graph."""
    return StageState(
        run_id=run_id,
        user_id=_USER_ID,
        inputs={},
        artifacts={"voice_alignment": voice_r2},
    )


def _make_niche_result(run_id: str = _RUN_ID, ranked_r2: str = "r2://ranked@v1.json") -> NicheToIdeasState:
    """Fake NicheToIdeasState returned by the niche_to_ideas subgraph."""
    return NicheToIdeasState(
        run_id=run_id,
        user_id=_USER_ID,
        inputs={"niche": "american housing"},
        artifacts={"ranked_ideas": ranked_r2},
    )


def _make_script_result(run_id: str = _RUN_ID, script_r2: str = "r2://script@v1.json") -> IdeaToScriptState:
    """Fake IdeaToScriptState returned by the idea_to_script subgraph."""
    return IdeaToScriptState(
        run_id=run_id,
        user_id=_USER_ID,
        inputs={"idea_title": "Housing Crisis"},
        artifacts={"script": script_r2},
    )


def _build_graph(
    *,
    mock_run_graph: AsyncMock,
    mock_read_artifact: AsyncMock,
    mock_adapter: MagicMock,
) -> Any:
    """Compile a full pipeline graph with all external deps patched."""
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        return build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
            legacy_adapter=mock_adapter,
        )


# ── PipelineState schema ──────────────────────────────────────────────────────


def test_pipeline_state_defaults() -> None:
    """PipelineState has correct defaults for hitl and target_duration_seconds."""
    state = PipelineState(run_id="r", user_id="u", inputs={})
    assert state.hitl is False
    assert state.target_duration_seconds == 60
    assert state.artifacts == {}


def test_pipeline_state_custom_values() -> None:
    """PipelineState accepts custom hitl and target_duration_seconds."""
    state = PipelineState(
        run_id="r",
        user_id="u",
        inputs={"niche": "finance"},
        hitl=True,
        target_duration_seconds=90,
    )
    assert state.hitl is True
    assert state.target_duration_seconds == 90


def test_pipeline_state_artifacts_merge() -> None:
    """PipelineState.artifacts uses the additive merge_refs reducer."""
    s1 = PipelineState(run_id="r", user_id="u", inputs={}, artifacts={"ranked_ideas": "r2://a"})
    s2 = PipelineState(run_id="r", user_id="u", inputs={}, artifacts={"script": "r2://b"})
    merged = {**s1.artifacts, **s2.artifacts}
    assert merged == {"ranked_ideas": "r2://a", "script": "r2://b"}


# ── Graph compilation ─────────────────────────────────────────────────────────


def test_build_full_pipeline_graph_compiles() -> None:
    """build_full_pipeline_graph returns a compiled graph without error."""
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
            legacy_adapter=MagicMock(),
        )
    assert graph is not None


# ── Full graph execution ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_happy_path() -> None:
    """Full graph threads run_id + artifacts across all five block nodes."""
    ranked_r2 = "r2://ranked_ideas@v1.json"
    script_r2 = "r2://script@v1.json"
    metadata_r2 = "r2://metadata@v1.json"
    voice_r2 = "r2://voice@v1.json"
    video_r2 = "r2://video/output/final.mp4"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_metadata_result(metadata_r2=metadata_r2),
        _make_voice_result(voice_r2=voice_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),   # idea_to_script_node reads ranked_ideas
        (_FAKE_ARTIFACT_META, _make_voice_body()),    # legacy_render_node reads voice_alignment
        (_FAKE_ARTIFACT_META, _make_script_body()),   # legacy_render_node reads script
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(
            run_id=_RUN_ID,
            user_id=_USER_ID,
            inputs={"niche": "american housing"},
        )
        result = await graph.ainvoke(initial, config={"configurable": {"thread_id": "t1"}})

    assert result["artifacts"]["ranked_ideas"] == ranked_r2
    assert result["artifacts"]["script"] == script_r2
    assert result["artifacts"]["youtube_metadata"] == metadata_r2
    assert result["artifacts"]["voice_alignment"] == voice_r2
    assert result["artifacts"]["video"] == video_r2


@pytest.mark.asyncio
async def test_run_id_threads_into_block_states() -> None:
    """niche_to_ideas_node and idea_to_script_node receive the parent run_id."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"

    captured_states: list[Any] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        captured_states.append((state, thread_id))
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(run_id=state.run_id, ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            return _make_script_result(run_id=state.run_id, script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_metadata_result(run_id=state.run_id)
        return _make_voice_result(run_id=state.run_id)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture_run_graph),
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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t2"}})

    assert len(captured_states) == 4
    niche_state, niche_thread = captured_states[0]
    script_state, script_thread = captured_states[1]
    metadata_state, metadata_thread = captured_states[2]
    voice_state, voice_thread = captured_states[3]

    assert niche_state.run_id == _RUN_ID
    assert script_state.run_id == _RUN_ID
    assert metadata_state.run_id == _RUN_ID
    assert voice_state.run_id == _RUN_ID
    assert niche_thread == f"{_RUN_ID}:niche_to_ideas"
    assert script_thread == f"{_RUN_ID}:idea_to_script"
    assert metadata_thread == f"{_RUN_ID}:youtube_metadata"
    assert voice_thread == f"{_RUN_ID}:voice_production"


@pytest.mark.asyncio
async def test_idea_title_extracted_from_ranked_ideas() -> None:
    """idea_to_script_node extracts idea_title from the ranked_ideas artifact."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"

    captured_script_state: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured_script_state.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_metadata_result()
        return _make_voice_result()

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body(title="Starter Homes Vanished")),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture_run_graph),
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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t3"}})

    assert len(captured_script_state) == 1
    assert captured_script_state[0].inputs["idea_title"] == "Starter Homes Vanished"


@pytest.mark.asyncio
async def test_niche_flows_into_idea_to_script() -> None:
    """idea_to_script_node passes niche from parent inputs into block inputs."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_metadata_result()
        return _make_voice_result()

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture_run_graph),
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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "american housing"})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t4"}})

    assert captured[0].inputs.get("niche") == "american housing"


@pytest.mark.asyncio
async def test_niche_absent_not_injected() -> None:
    """idea_to_script_node does not inject niche key when parent inputs lack it."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_metadata_result()
        return _make_voice_result()

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture_run_graph),
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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t5"}})

    assert "niche" not in captured[0].inputs


@pytest.mark.asyncio
async def test_target_duration_flows_into_idea_to_script() -> None:
    """idea_to_script_node passes target_duration_seconds from PipelineState."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_metadata_result()
        return _make_voice_result()

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=capture_run_graph),
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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(
            run_id=_RUN_ID,
            user_id=_USER_ID,
            inputs={},
            target_duration_seconds=90,
        )
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t6"}})

    assert captured[0].target_duration_seconds == 90


@pytest.mark.asyncio
async def test_legacy_render_node_reads_script_artifact() -> None:
    """legacy_render_node reads the script artifact and calls adapter.render with its text."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"
    script_text = "Housing prices skyrocketed last year."

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_metadata_result(),
        _make_voice_result(),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body(script=script_text)),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete"))

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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t7"}})

    mock_adapter.render.assert_awaited_once()
    call_kwargs = mock_adapter.render.call_args
    assert call_kwargs.kwargs["run_id"] == _RUN_ID
    assert call_kwargs.kwargs["script"] == script_text


@pytest.mark.asyncio
async def test_legacy_render_failure_raises_runtime_error() -> None:
    """legacy_render_node raises RuntimeError when the adapter reports status='failed'."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_metadata_result(),
        _make_voice_result(),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_voice_body()),
        (_FAKE_ARTIFACT_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(return_value=VideoResult(r2_key="", legacy_run_id=_RUN_ID, status="failed", error="storyboard: timeout"))

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
            legacy_adapter=mock_adapter,
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        with pytest.raises(Exception):
            await graph.ainvoke(initial, config={"configurable": {"thread_id": "t8"}})


@pytest.mark.asyncio
async def test_default_legacy_adapter_is_in_process() -> None:
    """build_full_pipeline_graph instantiates InProcessLegacyVideoAdapter when none is provided."""
    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.InProcessLegacyVideoAdapter") as mock_cls,
    ):
        mock_cls.return_value = MagicMock()
        build_full_pipeline_graph(
            storage=MagicMock(),
            registry=MagicMock(),
            executions=MagicMock(),
            artifact_repo=MagicMock(),
            adapters=[],
            trace_repo=MagicMock(),
            anthropic_api_key="test-key",
            legacy_adapter=None,
        )
    mock_cls.assert_called_once()
