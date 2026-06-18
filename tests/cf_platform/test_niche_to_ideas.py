"""Tests for the niche_to_ideas StateGraph assembly (P4-S4).

Covers:
- NicheToIdeasState schema: defaults, mode/top_n fields, artifacts reducer inherited
- register_niche_to_ideas_workers: all 4 workers present in registry after call
- build_niche_to_ideas_graph: compiles without error with registered workers
- End-to-end run: 4 artifacts in state, 4 execution rows, correct artifact keys
- Artifact names: discovery, candidate_topics, scored_topics, ranked_ideas
- Checkpointing: same thread_id reuse returns persisted state (MemorySaver)
- WorkerNotRegisteredError raised at build time if registry is empty
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from cf_platform.blocks.niche_to_ideas import (
    build_niche_to_ideas_graph,
    register_niche_to_ideas_workers,
)
from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.schemas import NicheToIdeasState, Signal, StageState
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerNotRegisteredError, WorkerRegistry
from cf_platform.workers.discovery import SignalsArtifact
from cf_platform.workers.opportunity_scorer import ScoredTopicsArtifact, TopicScore
from cf_platform.workers.topic_generator import CandidateTopic, CandidateTopicsArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact


# ── Fixtures & helpers ─────────────────────────────────────────────────

_NOW = datetime(2026, 6, 17, 12, 0, 0, tzinfo=timezone.utc)


def _make_topic_score(title: str = "Test Topic", final_score: float = 8.0) -> TopicScore:
    return TopicScore(
        title=title,
        angle="A compelling housing angle",
        novelty=8.0,
        audience_relevance=7.0,
        emotional_trigger=6.0,
        search_demand=9.0,
        competition=5.0,
        evergreen_potential=7.0,
        monetization_relevance=6.0,
        final_score=final_score,
    )


def _stub_signals_artifact() -> SignalsArtifact:
    return SignalsArtifact(
        niche="starter homes",
        generated_at=_NOW,
        signals=[Signal(source="youtube", title="Why starter homes vanished", score=500_000.0)],
    )


def _stub_candidate_topics_artifact() -> CandidateTopicsArtifact:
    return CandidateTopicsArtifact(
        niche="starter homes",
        generated_at=_NOW,
        topics=[CandidateTopic(title="Starter Homes Crisis", angle="Economic analysis")],
    )


def _stub_scored_topics_artifact() -> ScoredTopicsArtifact:
    return ScoredTopicsArtifact(
        niche="starter homes",
        generated_at=_NOW,
        scored_topics=[_make_topic_score("Starter Homes Crisis", 8.5)],
    )


def _stub_ranked_ideas_artifact() -> RankedIdeasArtifact:
    return RankedIdeasArtifact(
        niche="starter homes",
        generated_at=_NOW,
        selected=_make_topic_score("Starter Homes Crisis", 8.5),
        alternatives=[],
        mode="single",
    )


def _build_infra():
    """Return (storage, artifact_repo, executions, trace_repo) all in-memory."""
    return (
        InMemoryArtifactStorage(),
        InMemoryArtifactRepository(),
        InMemoryExecutionRepository(),
        InMemoryTraceEventRepository(),
    )


def _registered_registry() -> WorkerRegistry:
    registry = WorkerRegistry()
    register_niche_to_ideas_workers(registry)
    return registry


# ── NicheToIdeasState ──────────────────────────────────────────────────


class TestNicheToIdeasState:
    """NicheToIdeasState schema validates correctly and inherits StageState fields."""

    def test_defaults(self):
        """mode defaults to 'single' and top_n to 3."""
        state = NicheToIdeasState(run_id="r1", user_id="u1", inputs={"niche": "housing"})
        assert state.mode == "single"
        assert state.top_n == 3

    def test_custom_mode_and_top_n(self):
        """mode and top_n are overridable."""
        state = NicheToIdeasState(run_id="r1", user_id="u1", inputs={}, mode="top_n", top_n=5)
        assert state.mode == "top_n"
        assert state.top_n == 5

    def test_artifacts_reducer_merges(self):
        """artifacts field uses the merge_refs reducer from StageState (additive)."""
        state = NicheToIdeasState(
            run_id="r1", user_id="u1", inputs={}, artifacts={"discovery": "key1"}
        )
        assert state.artifacts == {"discovery": "key1"}

    def test_is_subclass_of_stage_state(self):
        """NicheToIdeasState IS-A StageState."""
        state = NicheToIdeasState(run_id="r1", user_id="u1", inputs={})
        assert isinstance(state, StageState)

    def test_empty_artifacts_default(self):
        """artifacts defaults to empty dict."""
        state = NicheToIdeasState(run_id="r1", user_id="u1", inputs={})
        assert state.artifacts == {}


# ── Worker registration ────────────────────────────────────────────────


class TestRegisterNicheToIdeasWorkers:
    """register_niche_to_ideas_workers populates the registry with all 4 workers."""

    def test_all_four_workers_registered(self):
        """discovery, topic_generator, opportunity_scorer, and topic_selector are all in registry after call."""
        registry = WorkerRegistry()
        register_niche_to_ideas_workers(registry)

        for worker_name in ("discovery", "topic_generator", "opportunity_scorer", "topic_selector"):
            reg = registry.resolve(worker_name)
            assert reg is not None, f"{worker_name} not registered"

    def test_idempotent_double_register(self):
        """Calling register_niche_to_ideas_workers twice does not raise."""
        registry = WorkerRegistry()
        register_niche_to_ideas_workers(registry)
        register_niche_to_ideas_workers(registry)
        assert registry.resolve("discovery").worker_version == "1.0.0"

    def test_worker_versions_pinned(self):
        """Each worker pins its expected worker_version."""
        registry = _registered_registry()
        assert registry.resolve("discovery").worker_version == "1.0.0"
        assert registry.resolve("topic_generator").worker_version == "1.1.0"
        assert registry.resolve("opportunity_scorer").worker_version == "1.1.0"
        assert registry.resolve("topic_selector").worker_version == "1.0.0"


# ── Graph compilation ──────────────────────────────────────────────────


class TestBuildNicheToIdeasGraph:
    """build_niche_to_ideas_graph compiles the StateGraph without error."""

    def _build_with_stubs(self, registry: WorkerRegistry):
        """Build the graph with factory functions patched to return simple stubs."""
        from cf_platform.core.schemas import WorkerOutput

        storage, artifact_repo, executions, trace_repo = _build_infra()

        async def _disc_stub(state):
            return WorkerOutput(artifact=_stub_signals_artifact())

        async def _tgen_stub(state):
            return WorkerOutput(artifact=_stub_candidate_topics_artifact())

        async def _scorer_stub(state):
            return WorkerOutput(artifact=_stub_scored_topics_artifact())

        async def _sel_stub(state):
            return WorkerOutput(artifact=_stub_ranked_ideas_artifact())

        with (
            patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_disc_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel_stub),
        ):
            graph = build_niche_to_ideas_graph(
                storage=storage,
                registry=registry,
                executions=executions,
                artifact_repo=artifact_repo,
                adapters=[],
                trace_repo=trace_repo,
                anthropic_api_key="test-key",
            )
        return graph, storage, artifact_repo, executions

    def test_compiles_with_registered_workers(self):
        """Graph compiles and returns a CompiledStateGraph when all workers are registered."""
        from langgraph.graph.state import CompiledStateGraph

        registry = _registered_registry()
        graph, _, _, _ = self._build_with_stubs(registry)
        assert isinstance(graph, CompiledStateGraph)

    def test_raises_if_workers_not_registered(self):
        """Build raises WorkerNotRegisteredError immediately if any worker is absent from registry."""
        registry = WorkerRegistry()  # empty — nothing registered

        with pytest.raises(WorkerNotRegisteredError):
            build_niche_to_ideas_graph(
                storage=InMemoryArtifactStorage(),
                registry=registry,
                executions=InMemoryExecutionRepository(),
                artifact_repo=InMemoryArtifactRepository(),
                adapters=[],
                trace_repo=InMemoryTraceEventRepository(),
                anthropic_api_key="x",
            )


# ── End-to-end graph run ───────────────────────────────────────────────


class TestNicheToIdeasGraphRun:
    """Running the assembled graph produces 4 artifacts, 4 executions, correct keys."""

    async def _run_graph_with_stubs(self, run_id: str = "run-1"):
        from cf_platform.core.schemas import WorkerOutput

        storage, artifact_repo, executions, trace_repo = _build_infra()
        registry = _registered_registry()

        async def _disc_stub(state):
            return WorkerOutput(artifact=_stub_signals_artifact())

        async def _tgen_stub(state):
            return WorkerOutput(artifact=_stub_candidate_topics_artifact())

        async def _scorer_stub(state):
            return WorkerOutput(artifact=_stub_scored_topics_artifact())

        async def _sel_stub(state):
            return WorkerOutput(artifact=_stub_ranked_ideas_artifact())

        with (
            patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_disc_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel_stub),
        ):
            graph = build_niche_to_ideas_graph(
                storage=storage,
                registry=registry,
                executions=executions,
                artifact_repo=artifact_repo,
                adapters=[],
                trace_repo=trace_repo,
                anthropic_api_key="test-key",
            )

        state = NicheToIdeasState(run_id=run_id, user_id="user-1", inputs={"niche": "starter homes"})
        result = await run_graph(graph, state, thread_id=run_id)
        return result, artifact_repo, executions

    @pytest.mark.asyncio
    async def test_four_artifact_refs_in_state(self):
        """Resulting state has exactly 4 artifact refs after all nodes complete."""
        result, _, _ = await self._run_graph_with_stubs()
        assert len(result.artifacts) == 4

    @pytest.mark.asyncio
    async def test_artifact_keys_match_contract(self):
        """Artifact keys in state are discovery, candidate_topics, scored_topics, ranked_ideas."""
        result, _, _ = await self._run_graph_with_stubs()
        assert set(result.artifacts.keys()) == {
            "discovery",
            "candidate_topics",
            "scored_topics",
            "ranked_ideas",
        }

    @pytest.mark.asyncio
    async def test_four_execution_rows(self):
        """Exactly 4 WorkerExecution rows are recorded — one per node."""
        result, _, executions = await self._run_graph_with_stubs()
        exec_rows = await executions.list_for_run("run-1")
        assert len(exec_rows) == 4

    @pytest.mark.asyncio
    async def test_four_artifact_records_in_repo(self):
        """Exactly 4 Artifact records are written to the artifact repository."""
        result, artifact_repo, _ = await self._run_graph_with_stubs()
        art_records = await artifact_repo.list_for_run("run-1")
        assert len(art_records) == 4

    @pytest.mark.asyncio
    async def test_state_mode_preserved(self):
        """NicheToIdeasState.mode and top_n survive the graph run unchanged."""
        from cf_platform.core.schemas import WorkerOutput

        storage, artifact_repo, executions, trace_repo = _build_infra()
        registry = _registered_registry()

        async def _stub(state):
            return WorkerOutput(artifact=_stub_signals_artifact())

        async def _tgen(state):
            return WorkerOutput(artifact=_stub_candidate_topics_artifact())

        async def _scorer(state):
            return WorkerOutput(artifact=_stub_scored_topics_artifact())

        async def _sel(state):
            return WorkerOutput(artifact=_stub_ranked_ideas_artifact())

        with (
            patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen),
            patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel),
        ):
            graph = build_niche_to_ideas_graph(
                storage=storage,
                registry=registry,
                executions=executions,
                artifact_repo=artifact_repo,
                adapters=[],
                trace_repo=trace_repo,
                anthropic_api_key="test-key",
            )

        state = NicheToIdeasState(
            run_id="run-mode", user_id="user-1", inputs={"niche": "housing"}, mode="top_n", top_n=5
        )
        result = await run_graph(graph, state, thread_id="run-mode")
        assert result.mode == "top_n"
        assert result.top_n == 5

    @pytest.mark.asyncio
    async def test_execution_workers_are_correct(self):
        """Each execution row has the correct worker name."""
        result, _, executions = await self._run_graph_with_stubs()
        exec_rows = await executions.list_for_run("run-1")
        worker_names = {ex.worker for ex in exec_rows}
        assert worker_names == {"discovery", "topic_generator", "opportunity_scorer", "topic_selector"}


# ── Checkpointing / resume ─────────────────────────────────────────────


class TestNicheToIdeasCheckpointing:
    """Graph compiles with a custom checkpointer and persists state after completion."""

    @pytest.mark.asyncio
    async def test_checkpointer_stores_state_after_completion(self):
        """After a completed run, the checkpointer has a stored checkpoint for the thread_id.

        This is the property that makes restart-resumability possible: if the process
        restarts mid-run, LangGraph loads the latest checkpoint for the thread_id and
        continues from the last completed node.
        """
        from langgraph.checkpoint.memory import MemorySaver

        from cf_platform.core.schemas import WorkerOutput

        storage, artifact_repo, executions, trace_repo = _build_infra()
        registry = _registered_registry()
        checkpointer = MemorySaver()

        async def _disc(state):
            return WorkerOutput(artifact=_stub_signals_artifact())

        async def _tgen(state):
            return WorkerOutput(artifact=_stub_candidate_topics_artifact())

        async def _scorer(state):
            return WorkerOutput(artifact=_stub_scored_topics_artifact())

        async def _sel(state):
            return WorkerOutput(artifact=_stub_ranked_ideas_artifact())

        with (
            patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_disc),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen),
            patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel),
        ):
            graph = build_niche_to_ideas_graph(
                storage=storage,
                registry=registry,
                executions=executions,
                artifact_repo=artifact_repo,
                adapters=[],
                trace_repo=trace_repo,
                anthropic_api_key="test-key",
                checkpointer=checkpointer,
            )

        state = NicheToIdeasState(run_id="run-cp", user_id="user-1", inputs={"niche": "housing"})
        result = await run_graph(graph, state, thread_id="run-cp")
        assert len(result.artifacts) == 4

        # The checkpointer must have a stored checkpoint for this thread_id.
        # LangGraph uses this to resume an interrupted run after process restart.
        config = {"configurable": {"thread_id": "run-cp"}}
        checkpoint = checkpointer.get(config)
        assert checkpoint is not None, "Checkpointer has no stored state — graph is not checkpointing"

    @pytest.mark.asyncio
    async def test_graph_accepts_custom_checkpointer(self):
        """build_niche_to_ideas_graph passes the caller-supplied checkpointer to the graph."""
        from langgraph.checkpoint.memory import MemorySaver

        from cf_platform.core.schemas import WorkerOutput

        storage, artifact_repo, executions, trace_repo = _build_infra()
        registry = _registered_registry()
        custom_checkpointer = MemorySaver()

        async def _stub(state):
            return WorkerOutput(artifact=_stub_signals_artifact())

        async def _tgen(state):
            return WorkerOutput(artifact=_stub_candidate_topics_artifact())

        async def _scorer(state):
            return WorkerOutput(artifact=_stub_scored_topics_artifact())

        async def _sel(state):
            return WorkerOutput(artifact=_stub_ranked_ideas_artifact())

        with (
            patch("cf_platform.blocks.niche_to_ideas.build_discovery_worker", return_value=_stub),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_generator_worker", return_value=_tgen),
            patch("cf_platform.blocks.niche_to_ideas.build_opportunity_scorer_worker", return_value=_scorer),
            patch("cf_platform.blocks.niche_to_ideas.build_topic_selector_worker", return_value=_sel),
        ):
            graph = build_niche_to_ideas_graph(
                storage=storage,
                registry=registry,
                executions=executions,
                artifact_repo=artifact_repo,
                adapters=[],
                trace_repo=trace_repo,
                anthropic_api_key="test-key",
                checkpointer=custom_checkpointer,
            )

        state = NicheToIdeasState(run_id="run-custom", user_id="u1", inputs={"niche": "housing"})
        await run_graph(graph, state, thread_id="run-custom")

        # custom_checkpointer should have the checkpoint, not some default one
        config = {"configurable": {"thread_id": "run-custom"}}
        assert custom_checkpointer.get(config) is not None
