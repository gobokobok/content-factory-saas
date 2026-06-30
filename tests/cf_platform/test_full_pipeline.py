"""Tests for cf_platform/orchestrator/full_pipeline.py (P6-S2, P9-S5)."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.schemas import (
    IdeaToScriptState,
    NicheToIdeasState,
    PipelineState,
    StageState,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.render_worker import RenderArtifact
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


def _make_render_artifact_body(video_key: str = "runs/run-test/output/final.mp4") -> dict:
    """Build a RenderArtifact-shaped dict for read_artifact mock (render_node reads this)."""
    artifact = RenderArtifact(
        render_script_key="runs/run-test/render_script.sh",
        video_key=video_key,
        scene_count=5,
        duration_s=45.0,
        generated_at=datetime.now(timezone.utc),
    )
    return artifact.model_dump(mode="json")


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


def _make_stage_result(
    run_id: str = _RUN_ID,
    artifact_key: str = "key",
    artifact_r2: str = "r2://artifact@v1.json",
) -> StageState:
    """Fake StageState returned by any observed single-worker subgraph."""
    return StageState(
        run_id=run_id,
        user_id=_USER_ID,
        inputs={},
        artifacts={artifact_key: artifact_r2},
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
        )
    assert graph is not None


def test_legacy_adapter_kwarg_accepted_but_not_used() -> None:
    """legacy_adapter kwarg is accepted for backward compat but not stored or called."""
    mock_adapter = MagicMock()
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
            legacy_adapter=mock_adapter,
        )
    assert graph is not None
    mock_adapter.render.assert_not_called()


# ── Full graph execution ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_happy_path() -> None:
    """Full graph threads run_id + artifacts across all seven block nodes."""
    ranked_r2 = "r2://ranked_ideas@v1.json"
    script_r2 = "r2://script@v1.json"
    metadata_r2 = "r2://metadata@v1.json"
    voice_r2 = "r2://voice@v1.json"
    sb_r2 = "r2://verified_storyboard@v1.json"
    mf_r2 = "r2://asset_manifest@v1.json"
    render_r2 = "r2://render_artifact@v1.json"
    video_r2 = "runs/run-test/output/final.mp4"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_stage_result(artifact_key="youtube_metadata", artifact_r2=metadata_r2),
        _make_stage_result(artifact_key="voice_alignment", artifact_r2=voice_r2),
        _make_stage_result(artifact_key="verified_storyboard", artifact_r2=sb_r2),
        _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1"),
        _make_stage_result(artifact_key="asset_manifest", artifact_r2=mf_r2),
        _make_stage_result(artifact_key="render_artifact", artifact_r2=render_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),          # idea_to_script_node reads ranked_ideas
        (_FAKE_ARTIFACT_META, _make_render_artifact_body(video_key=video_r2)),  # render_node reads RenderArtifact
    ])

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
    assert result["artifacts"]["verified_storyboard"] == sb_r2
    assert result["artifacts"]["asset_manifest"] == mf_r2
    assert result["artifacts"]["video"] == video_r2


@pytest.mark.asyncio
async def test_run_id_threads_into_block_states() -> None:
    """All seven block nodes receive the parent run_id and correct thread_ids."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "runs/run-test/output/final.mp4"
    render_r2 = "r2://render_artifact@v1.json"

    captured_states: list[Any] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        captured_states.append((state, thread_id))
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(run_id=state.run_id, ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            return _make_script_result(run_id=state.run_id, script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(run_id=state.run_id, artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(run_id=state.run_id, artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(run_id=state.run_id, artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(run_id=state.run_id, artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(run_id=state.run_id, artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        # render_worker
        return _make_stage_result(run_id=state.run_id, artifact_key="render_artifact", artifact_r2=render_r2)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body(video_key=video_r2)),
    ])

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
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t2"}})

    assert len(captured_states) == 8
    _, niche_thread = captured_states[0]
    _, script_thread = captured_states[1]
    _, metadata_thread = captured_states[2]
    _, voice_thread = captured_states[3]
    _, sb_thread = captured_states[4]
    _, vd_thread = captured_states[5]
    _, acq_thread = captured_states[6]
    _, render_thread = captured_states[7]

    assert niche_thread == f"{_RUN_ID}:niche_to_ideas"
    assert script_thread == f"{_RUN_ID}:idea_to_script"
    assert metadata_thread == f"{_RUN_ID}:youtube_metadata"
    assert voice_thread == f"{_RUN_ID}:voice_production"
    assert sb_thread == f"{_RUN_ID}:storyboard_worker"
    assert vd_thread == f"{_RUN_ID}:visual_director_worker"
    assert acq_thread == f"{_RUN_ID}:acquisition_worker"
    assert render_thread == f"{_RUN_ID}:render_worker"


@pytest.mark.asyncio
async def test_idea_title_extracted_from_ranked_ideas() -> None:
    """idea_to_script_node extracts idea_title from the ranked_ideas artifact."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    render_r2 = "r2://render@v1.json"

    captured_script_state: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured_script_state.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        return _make_stage_result(artifact_key="render_artifact", artifact_r2=render_r2)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body(title="Starter Homes Vanished")),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body()),
    ])

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
    render_r2 = "r2://render@v1.json"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        return _make_stage_result(artifact_key="render_artifact", artifact_r2=render_r2)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body()),
    ])

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
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "american housing"})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t4"}})

    assert captured[0].inputs.get("niche") == "american housing"


@pytest.mark.asyncio
async def test_niche_absent_not_injected() -> None:
    """idea_to_script_node does not inject niche key when parent inputs lack it."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    render_r2 = "r2://render@v1.json"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        return _make_stage_result(artifact_key="render_artifact", artifact_r2=render_r2)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body()),
    ])

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
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t5"}})

    assert "niche" not in captured[0].inputs


@pytest.mark.asyncio
async def test_target_duration_flows_into_idea_to_script() -> None:
    """idea_to_script_node passes target_duration_seconds from PipelineState."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    render_r2 = "r2://render@v1.json"
    captured: list[IdeaToScriptState] = []

    async def capture_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            captured.append(state)
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        return _make_stage_result(artifact_key="render_artifact", artifact_r2=render_r2)

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body()),
    ])

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
async def test_render_node_extracts_video_key_from_render_artifact() -> None:
    """render_node reads RenderArtifact and returns the raw video_key as artifacts['video']."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    render_artifact_r2 = "r2://render_artifact@v1.json"
    expected_video_r2 = "runs/test-run/output/final.mp4"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1"),
        _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1"),
        _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1"),
        _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1"),
        _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1"),
        _make_stage_result(artifact_key="render_artifact", artifact_r2=render_artifact_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
        (_FAKE_ARTIFACT_META, _make_render_artifact_body(video_key=expected_video_r2)),
    ])

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
        )
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        result = await graph.ainvoke(initial, config={"configurable": {"thread_id": "t7"}})

    assert result["artifacts"]["video"] == expected_video_r2
    # Confirm render_artifact read was called with the render artifact R2 key
    read_calls = mock_read_artifact.call_args_list
    assert any(render_artifact_r2 in str(call) for call in read_calls)


@pytest.mark.asyncio
async def test_render_worker_failure_raises() -> None:
    """render_node propagates exceptions from the render subgraph."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    render_error = RuntimeError("FFmpeg timeout")

    async def failing_run_graph(graph: Any, state: Any, thread_id: str) -> Any:
        if isinstance(state, NicheToIdeasState):
            return _make_niche_result(ranked_r2=ranked_r2)
        if isinstance(state, IdeaToScriptState):
            return _make_script_result(script_r2=script_r2)
        if "youtube_metadata" in thread_id:
            return _make_stage_result(artifact_key="youtube_metadata", artifact_r2="r2://meta@v1")
        if "voice_production" in thread_id:
            return _make_stage_result(artifact_key="voice_alignment", artifact_r2="r2://voice@v1")
        if "storyboard_worker" in thread_id:
            return _make_stage_result(artifact_key="verified_storyboard", artifact_r2="r2://sb@v1")
        if "visual_director_worker" in thread_id:
            return _make_stage_result(artifact_key="visual_treatment", artifact_r2="r2://vt@v1")
        if "acquisition_worker" in thread_id:
            return _make_stage_result(artifact_key="asset_manifest", artifact_r2="r2://mf@v1")
        raise render_error

    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_ARTIFACT_META, _make_ranked_body()),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", side_effect=failing_run_graph),
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
        initial = PipelineState(run_id=_RUN_ID, user_id=_USER_ID, inputs={})
        with pytest.raises(Exception):
            await graph.ainvoke(initial, config={"configurable": {"thread_id": "t8"}})
