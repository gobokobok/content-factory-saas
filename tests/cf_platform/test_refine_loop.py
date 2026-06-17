"""Tests for the idea_to_script refine loop and convergence logic (P5-S4).

Covers:
- IdeaToScriptState schema: defaults, iteration reducer (Annotated[int, operator.add])
- IdeaToScriptState: scorer_verdict / factcheck_verdict default to "continue"
- IdeaToScriptState: all six typed channels present and correct defaults
- _route_after_evaluation: "done" when iteration >= max_iterations
- _route_after_evaluation: "done" when both verdicts are "continue"
- _route_after_evaluation: "retry" when scorer_verdict is "retry"
- _route_after_evaluation: "retry" when factcheck_verdict is "retry"
- _route_after_evaluation: "done" overrides verdict check when cap reached
- register_idea_to_script_workers: all 4 workers present in registry
- build_refine_loop_graph: compiles without error with registered workers
- build_refine_loop_graph: raises WorkerNotRegisteredError with empty registry
- control_channel in wrap(): stores control signal in state field
- Loop run: converges to END when both workers return "continue" on first pass
- Loop run: stops at max_iterations even when workers keep returning "retry"
- Loop run: iteration counter increments correctly across retries
- Artifact keys: script_drafts, script_scores, factcheck_report present after run
"""

import json
import operator
from datetime import datetime, timezone
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.blocks.idea_to_script import (
    _increment_iteration,
    _route_after_evaluation,
    build_refine_loop_graph,
    register_idea_to_script_workers,
)
from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.schemas import IdeaToScriptState, StageState
from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerNotRegisteredError, WorkerRegistry
from cf_platform.workers.fact_checker import ClaimVerification, FactcheckReportArtifact
from cf_platform.workers.script_quality_scorer import ScriptDraftScore, ScriptScoresArtifact
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)
_IDEA_TITLE = "Why Starter Homes Vanished"


# ── Helpers ────────────────────────────────────────────────────────────


def _make_state(
    iteration: int = 0,
    max_iterations: int = 3,
    scorer_verdict: str = "continue",
    factcheck_verdict: str = "continue",
) -> IdeaToScriptState:
    return IdeaToScriptState(
        run_id="run-001",
        user_id="operator",
        inputs={"idea_title": _IDEA_TITLE},
        iteration=iteration,
        max_iterations=max_iterations,
        scorer_verdict=scorer_verdict,  # type: ignore[arg-type]
        factcheck_verdict=factcheck_verdict,  # type: ignore[arg-type]
    )


def _drafts_json(script: str = "Test script.") -> str:
    return json.dumps([{"draft_number": 1, "script": script}])


def _scores_json(overall: float = 8.5, control: str = "continue") -> str:
    return json.dumps(
        [
            {
                "draft_number": 1,
                "hook_strength": 8.0,
                "data_quality": 8.0,
                "narrative_flow": 8.0,
                "virality_potential": 9.0,
                "overall_score": overall,
            }
        ]
    )


def _factcheck_json() -> str:
    return json.dumps({"claims": []})


def _mock_text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    block.type = "text"
    response = MagicMock()
    response.content = [block]
    return response


# ── IdeaToScriptState schema ───────────────────────────────────────────


def test_idea_to_script_state_defaults():
    state = IdeaToScriptState(
        run_id="r", user_id="u", inputs={}
    )
    assert state.iteration == 0
    assert state.max_iterations == 3
    assert state.quality_threshold == 0.8
    assert state.unverified_threshold == 0.3
    assert state.scorer_verdict == "continue"
    assert state.factcheck_verdict == "continue"


def test_iteration_uses_add_reducer():
    """Annotated[int, operator.add] is the declared annotation on iteration."""
    hints = IdeaToScriptState.__annotations__
    annotated = hints.get("iteration")
    # The metadata should be operator.add
    assert hasattr(annotated, "__metadata__")
    assert operator.add in annotated.__metadata__


def test_artifacts_reducer_inherited():
    """StageState.artifacts reducer (merge_refs) is preserved in the subclass."""
    from cf_platform.core.schemas import merge_refs

    hints = IdeaToScriptState.__annotations__
    artifacts_hint = hints.get("artifacts", None)
    # Inherited — look in parent
    if artifacts_hint is None:
        from cf_platform.core.schemas import StageState as _SS

        artifacts_hint = _SS.__annotations__.get("artifacts")
    assert hasattr(artifacts_hint, "__metadata__")
    assert merge_refs in artifacts_hint.__metadata__


# ── _route_after_evaluation ────────────────────────────────────────────


def test_route_done_when_iteration_at_cap():
    state = _make_state(iteration=3, max_iterations=3, scorer_verdict="retry")
    assert _route_after_evaluation(state) == "done"


def test_route_done_when_both_continue():
    state = _make_state(iteration=0, scorer_verdict="continue", factcheck_verdict="continue")
    assert _route_after_evaluation(state) == "done"


def test_route_retry_when_scorer_retries():
    state = _make_state(iteration=0, scorer_verdict="retry", factcheck_verdict="continue")
    assert _route_after_evaluation(state) == "retry"


def test_route_retry_when_factcheck_retries():
    state = _make_state(iteration=0, scorer_verdict="continue", factcheck_verdict="retry")
    assert _route_after_evaluation(state) == "retry"


def test_route_done_cap_overrides_retry_verdict():
    state = _make_state(iteration=3, max_iterations=3, scorer_verdict="retry", factcheck_verdict="retry")
    assert _route_after_evaluation(state) == "done"


def test_route_retry_before_cap():
    state = _make_state(iteration=2, max_iterations=3, scorer_verdict="retry", factcheck_verdict="continue")
    assert _route_after_evaluation(state) == "retry"


# ── _increment_iteration ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_increment_iteration_returns_one():
    state = _make_state(iteration=0)
    result = await _increment_iteration(state)
    assert result == {"iteration": 1}


# ── register_idea_to_script_workers ───────────────────────────────────


def test_register_workers_adds_all_four():
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    for name in ("script_writer", "script_scorer", "fact_checker", "script_refiner"):
        reg = registry.resolve(name)
        assert reg is not None


# ── build_refine_loop_graph ────────────────────────────────────────────


def test_build_graph_compiles_with_registered_workers():
    storage = InMemoryArtifactStorage()
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    executions = InMemoryExecutionRepository()
    artifact_repo = InMemoryArtifactRepository()

    graph = build_refine_loop_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifact_repo,
        anthropic_api_key="fake-key",
    )
    assert graph is not None


def test_build_graph_raises_for_empty_registry():
    storage = InMemoryArtifactStorage()
    registry = WorkerRegistry()  # nothing registered
    executions = InMemoryExecutionRepository()
    artifact_repo = InMemoryArtifactRepository()

    with pytest.raises(WorkerNotRegisteredError):
        build_refine_loop_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifact_repo,
            anthropic_api_key="fake-key",
        )


# ── control_channel in wrap() ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrap_emits_control_signal_when_channel_set():
    """wrap() with control_channel includes the signal in its return dict."""
    from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
    from cf_platform.core.schemas import WorkerOutput
    from cf_platform.core.worker_registry import (
        InMemoryExecutionRepository,
        WorkerRegistry,
        WorkerRegistration,
        wrap,
    )
    from cf_platform.workers.script_writer import ScriptDraftsArtifact

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
        control_channel="scorer_verdict",
    )

    state = StageState(run_id="r1", user_id="u", inputs={})
    result = await wrapped(state)

    assert result["scorer_verdict"] == "retry"
    assert "artifacts" in result


@pytest.mark.asyncio
async def test_wrap_no_control_channel_omits_signal():
    """wrap() without control_channel does not include any extra field."""
    from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
    from cf_platform.core.schemas import WorkerOutput
    from cf_platform.core.worker_registry import (
        InMemoryExecutionRepository,
        WorkerRegistry,
        WorkerRegistration,
        wrap,
    )
    from cf_platform.workers.script_writer import ScriptDraftsArtifact

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


# ── End-to-end loop runs ───────────────────────────────────────────────


def _make_stub_workers(quality_above_threshold: bool, all_claims_verified: bool):
    """Return a context manager that patches all four builder functions with pure stubs.

    Stubs return pre-built artifacts without calling Claude, so each worker's
    control signal is deterministic for loop-convergence tests.
    """
    from cf_platform.core.schemas import WorkerOutput
    from cf_platform.workers.fact_checker import ClaimVerification, FactcheckReportArtifact
    from cf_platform.workers.script_quality_scorer import ScriptDraftScore, ScriptScoresArtifact
    from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact

    overall_score = 9.0 if quality_above_threshold else 5.0
    quality_threshold = 0.8
    quality_control = "continue" if overall_score / 10.0 >= quality_threshold else "retry"

    if all_claims_verified:
        claims: list = []
        factcheck_control = "continue"
    else:
        claims = [
            ClaimVerification(claim="Bad stat", verdict="refuted", source="", note="Wrong.")
        ] * 5
        factcheck_control = "retry"

    def _drafts_artifact():
        return ScriptDraftsArtifact(
            niche="housing", idea_title=_IDEA_TITLE, idea_angle=None,
            drafts=[ScriptDraft(draft_number=1, script="Test script.")],
            generated_at=_NOW,
        )

    def _scores_artifact():
        return ScriptScoresArtifact(
            idea_title=_IDEA_TITLE,
            scored_drafts=[ScriptDraftScore(
                draft_number=1, hook_strength=8.0, data_quality=8.0,
                narrative_flow=8.0, virality_potential=9.0, overall_score=overall_score,
            )],
            best_draft_number=1,
            best_score=overall_score,
            generated_at=_NOW,
        )

    def _factcheck_artifact():
        return FactcheckReportArtifact(
            idea_title=_IDEA_TITLE, draft_number=1,
            claims=claims,
            verified_count=0, refuted_count=len(claims), unverifiable_count=0,
            checked_at=_NOW,
        )

    def _refined_artifact():
        return ScriptDraftsArtifact(
            niche="housing", idea_title=_IDEA_TITLE, idea_angle=None,
            drafts=[ScriptDraft(draft_number=1, script="Refined script.")],
            generated_at=_NOW,
        )

    async def _stub_writer(state):
        return WorkerOutput(artifact=_drafts_artifact())

    async def _stub_scorer(state):
        return WorkerOutput(artifact=_scores_artifact(), control=quality_control)  # type: ignore[arg-type]

    async def _stub_fact_checker(state):
        return WorkerOutput(artifact=_factcheck_artifact(), control=factcheck_control)  # type: ignore[arg-type]

    async def _stub_refiner(state):
        return WorkerOutput(artifact=_refined_artifact())

    return (
        patch("cf_platform.blocks.idea_to_script.build_script_writer_worker", return_value=_stub_writer),
        patch("cf_platform.blocks.idea_to_script.build_script_quality_scorer_worker", return_value=_stub_scorer),
        patch("cf_platform.blocks.idea_to_script.build_fact_checker_worker", return_value=_stub_fact_checker),
        patch("cf_platform.blocks.idea_to_script.build_script_refiner_worker", return_value=_stub_refiner),
    )


def _build_infra():
    return (
        InMemoryArtifactStorage(),
        InMemoryArtifactRepository(),
        InMemoryExecutionRepository(),
    )


def _build_loop_graph(storage, executions, artifact_repo):
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    return build_refine_loop_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifact_repo,
        anthropic_api_key="fake-key",
    )


@pytest.mark.asyncio
async def test_loop_converges_on_first_pass_when_quality_passes():
    """Both workers return continue → graph reaches END after one iteration (no refine)."""
    storage, artifact_repo, executions = _build_infra()

    p1, p2, p3, p4 = _make_stub_workers(quality_above_threshold=True, all_claims_verified=True)
    with p1, p2, p3, p4:
        graph = _build_loop_graph(storage, executions, artifact_repo)
        initial_state = IdeaToScriptState(
            run_id="run-loop-1",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
            quality_threshold=0.8,
            unverified_threshold=0.3,
            max_iterations=3,
        )
        final_state = await run_graph(graph, initial_state, "run-loop-1")

    assert final_state.iteration == 0  # no retries
    assert "script_drafts" in final_state.artifacts
    assert "script_scores" in final_state.artifacts
    assert "factcheck_report" in final_state.artifacts


@pytest.mark.asyncio
async def test_loop_stops_at_max_iterations():
    """Workers keep returning retry; loop must stop at max_iterations."""
    storage, artifact_repo, executions = _build_infra()

    p1, p2, p3, p4 = _make_stub_workers(quality_above_threshold=False, all_claims_verified=False)
    with p1, p2, p3, p4:
        graph = _build_loop_graph(storage, executions, artifact_repo)
        initial_state = IdeaToScriptState(
            run_id="run-loop-2",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
            quality_threshold=0.8,
            unverified_threshold=0.3,
            max_iterations=2,  # low cap for speed
        )
        final_state = await run_graph(graph, initial_state, "run-loop-2")

    assert final_state.iteration >= initial_state.max_iterations


@pytest.mark.asyncio
async def test_iteration_counter_increments_on_retry():
    """Each retry path increments iteration by exactly 1."""
    storage, artifact_repo, executions = _build_infra()

    p1, p2, p3, p4 = _make_stub_workers(quality_above_threshold=False, all_claims_verified=False)
    with p1, p2, p3, p4:
        graph = _build_loop_graph(storage, executions, artifact_repo)
        initial_state = IdeaToScriptState(
            run_id="run-loop-3",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
            quality_threshold=0.8,
            unverified_threshold=0.3,
            max_iterations=1,  # force exactly one retry then cap
        )
        final_state = await run_graph(graph, initial_state, "run-loop-3")

    assert final_state.iteration == 1
