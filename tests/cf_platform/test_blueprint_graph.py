"""Tests for the idea_to_script Blueprint IR pipeline graph (P5-S6).

Covers:
- IdeaToScriptState: integrity_loops reducer uses operator.add
- IdeaToScriptState: integrity_verdict defaults to 'continue'
- _route_after_integrity: returns 'pass' when verdict is 'continue'
- _route_after_integrity: returns 'fail' when verdict is 'retry' and loops < MAX
- _route_after_integrity: returns 'manual_review' when verdict is 'retry' and loops >= MAX
- _increment_integrity_loops: returns {"integrity_loops": 1}
- register_idea_to_script_workers: all 12 workers present in registry
- build_idea_to_script_graph: compiles without error with registered workers
- build_idea_to_script_graph: raises WorkerNotRegisteredError without registered workers
- wrap() control_channel stores integrity_verdict in state (existing test from P5-S4)
- E2E graph run: passes through all nodes and reaches script_packager (stub workers)
- E2E graph run: integrity repair cycle increments integrity_loops correctly
- E2E graph run: manual_review path reached when loops exhausted
"""

import operator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from cf_platform.blocks.idea_to_script import (
    MAX_INTEGRITY_LOOPS,
    _increment_integrity_loops,
    _route_after_integrity,
    build_idea_to_script_graph,
    register_idea_to_script_workers,
)
from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    EvaluationArtifact,
    GeneratedScriptArtifact,
    HookVariantsArtifact,
    IntegrityReport,
    NarrativeLens,
    NormalizedContext,
    PatchSetArtifact,
    Section,
    SelectedHookArtifact,
)
from cf_platform.core.schemas import IdeaToScriptState, WorkerOutput
from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerNotRegisteredError, WorkerRegistry
from cf_platform.workers.script_packager import ScriptArtifact

_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)
_IDEA_TITLE = "Why Starter Homes Vanished"
_SCRIPT_TEXT = "In 1980 homes were affordable. Today they are not."


def _make_state(
    integrity_loops: int = 0,
    integrity_verdict: str = "continue",
) -> IdeaToScriptState:
    return IdeaToScriptState(
        run_id="run-001",
        user_id="operator",
        inputs={"idea_title": _IDEA_TITLE},
        integrity_loops=integrity_loops,
        integrity_verdict=integrity_verdict,  # type: ignore[arg-type]
    )


# ── IdeaToScriptState ──────────────────────────────────────────────────


def test_integrity_loops_uses_add_reducer():
    hints = IdeaToScriptState.__annotations__
    annotated = hints.get("integrity_loops")
    assert hasattr(annotated, "__metadata__")
    assert operator.add in annotated.__metadata__


def test_integrity_verdict_defaults_to_continue():
    state = IdeaToScriptState(run_id="r", user_id="u", inputs={})
    assert state.integrity_verdict == "continue"
    assert state.integrity_loops == 0


# ── _route_after_integrity ─────────────────────────────────────────────


def test_route_pass_when_verdict_continue():
    state = _make_state(integrity_loops=0, integrity_verdict="continue")
    assert _route_after_integrity(state) == "pass"


def test_route_fail_when_verdict_retry_and_loops_below_max():
    state = _make_state(integrity_loops=0, integrity_verdict="retry")
    assert _route_after_integrity(state) == "fail"


def test_route_fail_when_loops_at_one_below_max():
    state = _make_state(integrity_loops=MAX_INTEGRITY_LOOPS - 1, integrity_verdict="retry")
    assert _route_after_integrity(state) == "fail"


def test_route_manual_review_when_loops_at_max():
    state = _make_state(integrity_loops=MAX_INTEGRITY_LOOPS, integrity_verdict="retry")
    assert _route_after_integrity(state) == "manual_review"


def test_route_pass_overrides_when_verdict_is_continue_regardless_of_loops():
    """Even with high loop count, 'continue' verdict always routes to pass."""
    state = _make_state(integrity_loops=99, integrity_verdict="continue")
    assert _route_after_integrity(state) == "pass"


# ── _increment_integrity_loops ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_increment_integrity_loops_returns_one():
    state = _make_state()
    result = await _increment_integrity_loops(state)
    assert result == {"integrity_loops": 1}


# ── register_idea_to_script_workers ───────────────────────────────────


def test_register_workers_adds_all_twelve():
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    expected = [
        "context_normalizer", "blueprint_generator", "evaluator",
        "blueprint_merger", "narrative_lens", "hook_generator", "hook_selector",
        "script_generator", "integrity_checker", "patch_generator",
        "patch_applier", "script_packager",
    ]
    for name in expected:
        reg = registry.resolve(name)
        assert reg is not None


# ── build_idea_to_script_graph ─────────────────────────────────────────


def test_build_graph_compiles_with_registered_workers():
    storage = InMemoryArtifactStorage()
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    executions = InMemoryExecutionRepository()
    artifact_repo = InMemoryArtifactRepository()

    graph = build_idea_to_script_graph(
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
        build_idea_to_script_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifact_repo,
            anthropic_api_key="fake-key",
        )


# ── E2E stub runs ──────────────────────────────────────────────────────


def _make_blueprints():
    return Blueprint(
        hook_angle="Starter homes dropped 70%",
        structure=[Section(title="Hook", key_points=["stat"])],
        claims=["Claim"],
        monetization_angle="Urgency",
        required_evidence=["Census data"],
        signal_summary="Summary",
        direction_alignment_notes="Notes",
    )


def _make_normalized_context():
    return NormalizedContext(
        primary_angle="Supply shortage",
        evidence_summary="Some evidence",
        top_signals=["signal 1"],
        controversies=[],
        hook_bias="Data-driven",
    )


def _make_evaluation():
    return EvaluationArtifact(
        score=8.0,
        factual_corrections=[],
        alignment_notes="Notes",
        evidence_additions=[],
        passed=True,
        notes="Good",
    )


def _make_generated_script():
    return GeneratedScriptArtifact(
        idea_title=_IDEA_TITLE,
        niche="housing",
        script=_SCRIPT_TEXT,
        word_count=len(_SCRIPT_TEXT.split()),
        target_duration_seconds=60,
        generated_at=_NOW,
    )


def _make_script_artifact(status: str = "ok"):
    return ScriptArtifact(
        idea_title=_IDEA_TITLE,
        niche="housing",
        script=_SCRIPT_TEXT,
        word_count=len(_SCRIPT_TEXT.split()),
        status=status,  # type: ignore[arg-type]
        generated_at=_NOW,
    )


@contextmanager
def _stub_all_workers(integrity_passes: bool = True, integrity_loops_before_pass: int = 0):
    """Patch all 12 builder functions with pure stubs."""
    call_count = {"integrity": 0}

    async def _stub_context_normalizer(state):
        return WorkerOutput(artifact=_make_normalized_context())

    async def _stub_blueprint_generator(state):
        return WorkerOutput(artifact=_make_blueprints())

    async def _stub_evaluator(state):
        return WorkerOutput(artifact=_make_evaluation())

    async def _stub_blueprint_merger(state):
        return WorkerOutput(artifact=_make_blueprints())

    async def _stub_narrative_lens(state):
        return WorkerOutput(artifact=NarrativeLens(
            identity_angle="Identity", contrarian_angle="Contrarian",
            philosophical_angle="Philosophical", emotional_angle="Emotional",
            story_devices=["device"],
        ))

    async def _stub_hook_generator(state):
        return WorkerOutput(artifact=HookVariantsArtifact(
            hooks=["Hook 1", "Hook 2"], generated_at=_NOW
        ))

    async def _stub_hook_selector(state):
        return WorkerOutput(artifact=SelectedHookArtifact(hook="Hook 1", generated_at=_NOW))

    async def _stub_script_generator(state):
        return WorkerOutput(artifact=_make_generated_script())

    async def _stub_integrity_checker(state):
        call_count["integrity"] += 1
        if integrity_passes or call_count["integrity"] > integrity_loops_before_pass:
            return WorkerOutput(artifact=IntegrityReport(passed=True, issues=[]), control="continue")  # type: ignore[arg-type]
        return WorkerOutput(artifact=IntegrityReport(passed=False, issues=[]), control="retry")  # type: ignore[arg-type]

    async def _stub_patch_generator(state):
        return WorkerOutput(artifact=PatchSetArtifact(patches=[], generated_at=_NOW))

    async def _stub_patch_applier(state):
        return WorkerOutput(artifact=_make_generated_script())

    async def _stub_script_packager(state):
        return WorkerOutput(artifact=_make_script_artifact())

    with (
        patch("cf_platform.blocks.idea_to_script.build_context_normalizer_worker", return_value=_stub_context_normalizer),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_generator_worker", return_value=_stub_blueprint_generator),
        patch("cf_platform.blocks.idea_to_script.build_evaluator_worker", return_value=_stub_evaluator),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_merger_worker", return_value=_stub_blueprint_merger),
        patch("cf_platform.blocks.idea_to_script.build_narrative_lens_worker", return_value=_stub_narrative_lens),
        patch("cf_platform.blocks.idea_to_script.build_hook_generator_worker", return_value=_stub_hook_generator),
        patch("cf_platform.blocks.idea_to_script.build_hook_selector_worker", return_value=_stub_hook_selector),
        patch("cf_platform.blocks.idea_to_script.build_script_generator_worker", return_value=_stub_script_generator),
        patch("cf_platform.blocks.idea_to_script.build_integrity_checker_worker", return_value=_stub_integrity_checker),
        patch("cf_platform.blocks.idea_to_script.build_patch_generator_worker", return_value=_stub_patch_generator),
        patch("cf_platform.blocks.idea_to_script.build_patch_applier_worker", return_value=_stub_patch_applier),
        patch("cf_platform.blocks.idea_to_script.build_script_packager_worker", return_value=_stub_script_packager),
    ):
        yield


def _build_infra():
    return (
        InMemoryArtifactStorage(),
        InMemoryArtifactRepository(),
        InMemoryExecutionRepository(),
    )


def _build_graph(storage, executions, artifact_repo):
    registry = WorkerRegistry()
    register_idea_to_script_workers(registry)
    return build_idea_to_script_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifact_repo,
        anthropic_api_key="fake-key",
    )


@pytest.mark.asyncio
async def test_e2e_integrity_passes_on_first_check():
    """Integrity passes immediately — graph reaches script_packager with integrity_loops=0."""
    storage, artifact_repo, executions = _build_infra()
    with _stub_all_workers(integrity_passes=True):
        graph = _build_graph(storage, executions, artifact_repo)
        state = IdeaToScriptState(
            run_id="run-e2e-1",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
        )
        final_state = await run_graph(graph, state, "run-e2e-1")

    assert "script" in final_state.artifacts
    assert final_state.integrity_loops == 0


@pytest.mark.asyncio
async def test_e2e_integrity_fails_then_passes_after_one_repair():
    """Integrity fails once → one repair cycle → passes on re-check."""
    storage, artifact_repo, executions = _build_infra()
    # integrity_loops_before_pass=1 means first call returns fail, second returns pass
    with _stub_all_workers(integrity_passes=False, integrity_loops_before_pass=1):
        graph = _build_graph(storage, executions, artifact_repo)
        state = IdeaToScriptState(
            run_id="run-e2e-2",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
        )
        final_state = await run_graph(graph, state, "run-e2e-2")

    assert "script" in final_state.artifacts
    assert final_state.integrity_loops == 1


@pytest.mark.asyncio
async def test_e2e_integrity_always_fails_reaches_manual_review():
    """Integrity never passes → graph exhausts MAX_INTEGRITY_LOOPS and routes to script_packager."""
    storage, artifact_repo, executions = _build_infra()
    # Never pass integrity
    with _stub_all_workers(integrity_passes=False, integrity_loops_before_pass=999):
        graph = _build_graph(storage, executions, artifact_repo)
        state = IdeaToScriptState(
            run_id="run-e2e-3",
            user_id="operator",
            inputs={"idea_title": _IDEA_TITLE},
        )
        final_state = await run_graph(graph, state, "run-e2e-3")

    # Should still reach script_packager (graceful exit), loops should be capped
    assert "script" in final_state.artifacts
    assert final_state.integrity_loops >= MAX_INTEGRITY_LOOPS
