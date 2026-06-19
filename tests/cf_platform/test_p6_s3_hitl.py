"""Tests for P6-S3 — Human-in-the-loop gates.

Covers:
  - Gate node interrupt / bypass routing in full_pipeline.py
  - Resume with approve / reject
  - auto_approve_after_timeout coroutine
  - Telegram HITL formatters and parsers
  - POST /platform/runs/{run_id}/resume REST endpoint
"""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cf_platform.adapters.legacy_video import VideoResult
from cf_platform.core.schemas import (
    IdeaToScriptState,
    NicheToIdeasState,
    PipelineState,
    StageState,
)
from cf_platform.interfaces.api import (
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_platform_settings,
    get_trace_event_repository,
    get_worker_registry,
    router,
)
from cf_platform.interfaces.telegram import (
    format_hitl_approved,
    format_hitl_rejected,
    format_script_approval_request,
    parse_hitl_decision,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.orchestrator.hitl import auto_approve_after_timeout
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact

# ── Shared fixtures ────────────────────────────────────────────────────────────

_RUN_ID = "run-p6s3-test"
_USER_ID = "operator"
_FAKE_META: Any = MagicMock()


def _make_ranked_body(title: str = "Housing Crisis") -> dict:
    score = TopicScore(
        title=title, angle="explainer", novelty=8.0, audience_relevance=9.0,
        emotional_trigger=7.0, search_demand=8.5, competition=6.0,
        evergreen_potential=9.0, monetization_relevance=8.0, final_score=8.5,
    )
    return RankedIdeasArtifact(
        niche="american housing", generated_at=datetime.now(timezone.utc),
        selected=score, alternatives=[], mode="single",
    ).model_dump(mode="json")


def _make_script_body(script: str = "Housing prices are rising.") -> dict:
    return ScriptArtifact(
        idea_title="Housing Crisis", niche="american housing", script=script,
        word_count=4, generated_at=datetime.now(timezone.utc),
    ).model_dump(mode="json")


def _make_niche_result(ranked_r2: str = "r2://ranked@v1.json") -> NicheToIdeasState:
    return NicheToIdeasState(
        run_id=_RUN_ID, user_id=_USER_ID,
        inputs={"niche": "american housing"},
        artifacts={"ranked_ideas": ranked_r2},
    )


def _make_script_result(script_r2: str = "r2://script@v1.json") -> IdeaToScriptState:
    return IdeaToScriptState(
        run_id=_RUN_ID, user_id=_USER_ID,
        inputs={"idea_title": "Housing Crisis"},
        artifacts={"script": script_r2},
    )


def _make_voice_body(voice_r2: str = "r2://voice@v1.json") -> dict:
    return {
        "mp3_r2_key": f"runs/{_RUN_ID}/voiceover/generated.mp3",
        "word_timestamps": [],
        "alignment_method": "proportional_fallback",
        "total_duration_s": 30.0,
    }


def _make_voice_result(voice_r2: str = "r2://voice@v1.json") -> StageState:
    return StageState(
        run_id=_RUN_ID, user_id=_USER_ID,
        inputs={},
        artifacts={"voice_alignment": voice_r2},
    )


# ── Gate routing: hitl=False bypasses the gate ───────────────────────────────


@pytest.mark.asyncio
async def test_hitl_false_skips_gate_and_calls_legacy_render() -> None:
    """When hitl=False (default), the graph bypasses script_approval_gate directly."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"

    voice_r2 = "r2://voice@v1.json"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_voice_result(voice_r2=voice_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_META, _make_ranked_body()),
        (_FAKE_META, _make_voice_body()),
        (_FAKE_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(
        return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete")
    )

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(), registry=MagicMock(), executions=MagicMock(),
            artifact_repo=MagicMock(), adapters=[], trace_repo=MagicMock(),
            anthropic_api_key="key", legacy_adapter=mock_adapter,
        )
        initial = PipelineState(
            run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"}, hitl=False,
        )
        result = await graph.ainvoke(initial, config={"configurable": {"thread_id": "t-no-hitl"}})

    mock_adapter.render.assert_awaited_once()
    assert result["artifacts"]["video"] == video_r2


# ── Gate routing: hitl=True — test gate logic by patching interrupt ───────────
#
# LangGraph's interrupt() requires Python 3.11+ for async context propagation
# (uses contextvars features added in 3.11). The system CI target is Python 3.11
# (per CONVENTIONS.md), but local dev may run 3.9. These tests patch `interrupt`
# directly to unit-test the gate's decision logic without relying on LangGraph's
# interrupt machinery. The LangGraph interrupt integration is exercised in prod
# via DEV smoke tests.


def _build_hitl_graph(
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
            storage=MagicMock(), registry=MagicMock(), executions=MagicMock(),
            artifact_repo=MagicMock(), adapters=[], trace_repo=MagicMock(),
            anthropic_api_key="key", legacy_adapter=mock_adapter,
        )


@pytest.mark.asyncio
async def test_hitl_interrupt_called_with_run_id_and_script_key() -> None:
    """Gate node calls interrupt() with type, run_id, and script_r2_key."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://my-script@v1.json"
    video_r2 = "r2://video.mp4"

    captured: list[Any] = []

    def mock_interrupt(value: Any) -> Any:
        captured.append(value)
        return "approve"  # simulate operator approval

    voice_r2 = "r2://voice@v1.json"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_voice_result(voice_r2=voice_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_META, _make_ranked_body()),
        (_FAKE_META, _make_voice_body()),
        (_FAKE_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(
        return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete")
    )

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
        patch("cf_platform.orchestrator.full_pipeline.interrupt", side_effect=mock_interrupt),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(), registry=MagicMock(), executions=MagicMock(),
            artifact_repo=MagicMock(), adapters=[], trace_repo=MagicMock(),
            anthropic_api_key="key", legacy_adapter=mock_adapter,
        )
        initial = PipelineState(
            run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"}, hitl=True,
        )
        await graph.ainvoke(initial, config={"configurable": {"thread_id": "t-iv"}})

    assert len(captured) == 1
    assert captured[0]["type"] == "script_approval"
    assert captured[0]["run_id"] == _RUN_ID
    assert captured[0]["script_r2_key"] == script_r2


@pytest.mark.asyncio
async def test_hitl_approve_calls_legacy_render() -> None:
    """When the mocked interrupt returns 'approve', legacy_render is called."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"
    video_r2 = "r2://video.mp4"

    voice_r2 = "r2://voice@v1.json"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
        _make_voice_result(voice_r2=voice_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_META, _make_ranked_body()),
        (_FAKE_META, _make_voice_body()),
        (_FAKE_META, _make_script_body()),
    ])
    mock_adapter = MagicMock()
    mock_adapter.render = AsyncMock(
        return_value=VideoResult(r2_key=video_r2, legacy_run_id=_RUN_ID, status="complete")
    )

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
        patch("cf_platform.orchestrator.full_pipeline.interrupt", return_value="approve"),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(), registry=MagicMock(), executions=MagicMock(),
            artifact_repo=MagicMock(), adapters=[], trace_repo=MagicMock(),
            anthropic_api_key="key", legacy_adapter=mock_adapter,
        )
        initial = PipelineState(
            run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"}, hitl=True,
        )
        result = await graph.ainvoke(initial, config={"configurable": {"thread_id": "t-approve"}})

    mock_adapter.render.assert_awaited_once()
    assert result["artifacts"]["video"] == video_r2


@pytest.mark.asyncio
async def test_hitl_reject_raises_runtime_error() -> None:
    """When the mocked interrupt returns 'reject', gate raises RuntimeError."""
    ranked_r2 = "r2://ranked@v1.json"
    script_r2 = "r2://script@v1.json"

    mock_run_graph = AsyncMock(side_effect=[
        _make_niche_result(ranked_r2=ranked_r2),
        _make_script_result(script_r2=script_r2),
    ])
    mock_read_artifact = AsyncMock(side_effect=[
        (_FAKE_META, _make_ranked_body()),
    ])

    with (
        patch("cf_platform.orchestrator.full_pipeline.build_niche_to_ideas_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.build_idea_to_script_graph", return_value=MagicMock()),
        patch("cf_platform.orchestrator.full_pipeline.run_graph", mock_run_graph),
        patch("cf_platform.orchestrator.full_pipeline.read_artifact", mock_read_artifact),
        patch("cf_platform.orchestrator.full_pipeline.interrupt", return_value="reject"),
    ):
        graph = build_full_pipeline_graph(
            storage=MagicMock(), registry=MagicMock(), executions=MagicMock(),
            artifact_repo=MagicMock(), adapters=[], trace_repo=MagicMock(),
            anthropic_api_key="key", legacy_adapter=MagicMock(),
        )
        initial = PipelineState(
            run_id=_RUN_ID, user_id=_USER_ID, inputs={"niche": "housing"}, hitl=True,
        )
        with pytest.raises(Exception, match="rejected"):
            await graph.ainvoke(initial, config={"configurable": {"thread_id": "t-reject"}})


# ── auto_approve_after_timeout ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_approve_noop_when_timeout_zero() -> None:
    """auto_approve_after_timeout is a no-op when timeout_seconds=0."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    await auto_approve_after_timeout(run_id=_RUN_ID, timeout_seconds=0, graph=mock_graph)

    mock_graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_approve_noop_when_timeout_negative() -> None:
    """auto_approve_after_timeout is a no-op when timeout_seconds < 0."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    await auto_approve_after_timeout(run_id=_RUN_ID, timeout_seconds=-1, graph=mock_graph)

    mock_graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_approve_calls_graph_with_approve_command() -> None:
    """auto_approve_after_timeout calls graph.ainvoke(Command(resume='approve')) after delay."""
    from langgraph.types import Command

    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch("cf_platform.orchestrator.hitl.asyncio.sleep", AsyncMock()) as mock_sleep:
        await auto_approve_after_timeout(run_id=_RUN_ID, timeout_seconds=30, graph=mock_graph)

    mock_sleep.assert_awaited_once_with(30)
    mock_graph.ainvoke.assert_awaited_once()
    call_args = mock_graph.ainvoke.call_args
    command = call_args.args[0]
    assert isinstance(command, Command)
    assert command.resume == "approve"


@pytest.mark.asyncio
async def test_auto_approve_uses_run_id_as_thread_id_by_default() -> None:
    """auto_approve_after_timeout uses run_id as the thread_id when none is provided."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch("cf_platform.orchestrator.hitl.asyncio.sleep", AsyncMock()):
        await auto_approve_after_timeout(run_id=_RUN_ID, timeout_seconds=1, graph=mock_graph)

    config = mock_graph.ainvoke.call_args.kwargs["config"]
    assert config["configurable"]["thread_id"] == _RUN_ID


@pytest.mark.asyncio
async def test_auto_approve_uses_explicit_thread_id_when_provided() -> None:
    """auto_approve_after_timeout uses the explicit thread_id argument when given."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock()

    with patch("cf_platform.orchestrator.hitl.asyncio.sleep", AsyncMock()):
        await auto_approve_after_timeout(
            run_id=_RUN_ID, timeout_seconds=1, graph=mock_graph, thread_id="custom-thread"
        )

    config = mock_graph.ainvoke.call_args.kwargs["config"]
    assert config["configurable"]["thread_id"] == "custom-thread"


@pytest.mark.asyncio
async def test_auto_approve_swallows_graph_exception() -> None:
    """auto_approve_after_timeout logs and swallows exceptions from graph.ainvoke."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("graph crashed"))

    with patch("cf_platform.orchestrator.hitl.asyncio.sleep", AsyncMock()):
        # Should not raise
        await auto_approve_after_timeout(run_id=_RUN_ID, timeout_seconds=1, graph=mock_graph)


# ── Telegram HITL formatters ──────────────────────────────────────────────────


def test_format_script_approval_request_contains_run_id() -> None:
    """format_script_approval_request includes the run_id in the output."""
    text = format_script_approval_request(run_id="abc-123", script_preview="Short script.")
    assert "abc-123" in text


def test_format_script_approval_request_contains_approve_instruction() -> None:
    """format_script_approval_request instructs the operator to /approve or /reject."""
    text = format_script_approval_request(run_id="abc-123", script_preview="Short script.")
    assert "/approve" in text
    assert "/reject" in text


def test_format_script_approval_request_includes_preview() -> None:
    """format_script_approval_request includes the script preview text."""
    preview = "The housing market is broken."
    text = format_script_approval_request(run_id="abc-123", script_preview=preview)
    assert preview in text


def test_format_script_approval_request_truncates_long_preview() -> None:
    """format_script_approval_request truncates previews longer than 2000 chars."""
    long_script = "x" * 3000
    text = format_script_approval_request(run_id="abc-123", script_preview=long_script)
    assert "..." in text
    # The preview portion should not contain 3000 'x' chars
    assert "x" * 2001 not in text


def test_format_script_approval_request_does_not_truncate_short_preview() -> None:
    """format_script_approval_request preserves short scripts without truncation."""
    short_script = "Short."
    text = format_script_approval_request(run_id="abc-123", script_preview=short_script)
    assert "Short." in text
    assert "..." not in text


def test_parse_hitl_decision_approve() -> None:
    """parse_hitl_decision parses /approve <run_id>."""
    result = parse_hitl_decision("/approve abc-123")
    assert result == ("approve", "abc-123")


def test_parse_hitl_decision_reject() -> None:
    """parse_hitl_decision parses /reject <run_id>."""
    result = parse_hitl_decision("/reject abc-123")
    assert result == ("reject", "abc-123")


def test_parse_hitl_decision_with_whitespace() -> None:
    """parse_hitl_decision strips surrounding whitespace."""
    result = parse_hitl_decision("  /approve  my-run-id  ")
    assert result == ("approve", "my-run-id")


def test_parse_hitl_decision_missing_run_id_returns_none() -> None:
    """parse_hitl_decision returns None when run_id is absent."""
    assert parse_hitl_decision("/approve") is None
    assert parse_hitl_decision("/reject") is None


def test_parse_hitl_decision_unrecognized_returns_none() -> None:
    """parse_hitl_decision returns None for unrecognized commands."""
    assert parse_hitl_decision("/ideas starter homes") is None
    assert parse_hitl_decision("just some text") is None


def test_format_hitl_approved_contains_run_id() -> None:
    """format_hitl_approved includes the run_id in the reply."""
    text = format_hitl_approved("abc-123")
    assert "abc-123" in text


def test_format_hitl_rejected_contains_run_id() -> None:
    """format_hitl_rejected includes the run_id in the reply."""
    text = format_hitl_rejected("abc-123")
    assert "abc-123" in text


# ── REST /runs/{run_id}/resume endpoint ───────────────────────────────────────


def _make_resume_client(mock_graph: Any = None) -> TestClient:
    """Return a TestClient for the resume endpoint with all deps overridden.

    Uses `app.dependency_overrides` (FastAPI's DI override mechanism) rather
    than `patch` — FastAPI holds references to the original dependency callables,
    so module-level patching does not intercept DI-resolved parameters.
    """
    if mock_graph is None:
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value={})

    mock_settings = MagicMock()
    mock_settings.ANTHROPIC_API_KEY = "test-key"

    app = FastAPI()
    app.include_router(router, prefix="/platform")
    app.dependency_overrides[get_artifact_storage] = lambda: MagicMock()
    app.dependency_overrides[get_worker_registry] = lambda: MagicMock()
    app.dependency_overrides[get_execution_repository] = lambda: MagicMock()
    app.dependency_overrides[get_artifact_repository] = lambda: MagicMock()
    app.dependency_overrides[get_trace_event_repository] = lambda: MagicMock()
    app.dependency_overrides[get_graph_checkpointer] = lambda: MagicMock()
    app.dependency_overrides[get_platform_settings] = lambda: mock_settings
    app.dependency_overrides[get_discovery_adapters] = lambda: []
    return TestClient(app, raise_server_exceptions=True)


def test_resume_endpoint_returns_202() -> None:
    """POST /platform/runs/{run_id}/resume returns 202 with the expected body."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    client = _make_resume_client(mock_graph)

    with patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=mock_graph):
        response = client.post(
            f"/platform/runs/{_RUN_ID}/resume",
            json={"decision": "approve"},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["run_id"] == _RUN_ID
    assert data["decision"] == "approve"
    assert data["status"] == "resuming"


def test_resume_endpoint_reject_returns_202() -> None:
    """POST /platform/runs/{run_id}/resume with 'reject' also returns 202."""
    mock_graph = MagicMock()
    mock_graph.ainvoke = AsyncMock(return_value={})
    client = _make_resume_client(mock_graph)

    with patch("cf_platform.interfaces.api.build_full_pipeline_graph", return_value=mock_graph):
        response = client.post(
            f"/platform/runs/{_RUN_ID}/resume",
            json={"decision": "reject"},
        )

    assert response.status_code == 202
    assert response.json()["decision"] == "reject"


def test_resume_endpoint_invalid_decision_returns_422() -> None:
    """POST /platform/runs/{run_id}/resume with an invalid decision returns 422."""
    client = _make_resume_client()
    response = client.post(
        f"/platform/runs/{_RUN_ID}/resume",
        json={"decision": "maybe"},
    )
    assert response.status_code == 422
