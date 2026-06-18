"""idea_to_script block — writer → scorer → refine (cyclic) → fact_checker → packager.

Provides two graph factories:

  build_refine_loop_graph  (P5-S4) — cyclic loop only (writer/scorer/refiner), ends at
                                      END after convergence. Used by loop-isolation tests.
                                      fact_checker is NOT in the loop — it runs once in
                                      build_idea_to_script_graph on the final draft only.

  build_idea_to_script_graph (P5-S5) — full assembled block; fact_checker runs once after
                                        the refinement loop converges, then script_packager
                                        emits the final `ScriptArtifact`. Use for REST +
                                        Telegram.

Graph topology (build_idea_to_script_graph):

  START → script_writer → script_scorer
        → conditional(_route_after_scorer):
            "done"  → fact_checker → script_packager → END
            "retry" → increment_iteration → script_refiner → script_writer (cycle)

Canonical spec: docs/v2_platform_plan.md §5.
"""

from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.schemas import IdeaToScriptState
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry, wrap
from cf_platform.workers.fact_checker import FACT_CHECKER_REGISTRATION, build_fact_checker_worker
from cf_platform.workers.script_packager import SCRIPT_PACKAGER_REGISTRATION, build_script_packager_worker
from cf_platform.workers.script_quality_scorer import (
    SCRIPT_QUALITY_SCORER_REGISTRATION,
    build_script_quality_scorer_worker,
)
from cf_platform.workers.script_refiner import SCRIPT_REFINER_REGISTRATION, build_script_refiner_worker
from cf_platform.workers.script_writer import SCRIPT_WRITER_REGISTRATION, build_script_writer_worker


def register_idea_to_script_workers(registry: WorkerRegistry) -> None:
    """Register all five idea_to_script workers in registry (idempotent re-register is fine).

    Registers: script_writer, script_scorer, fact_checker, script_refiner, script_packager.
    Call once at startup before building either graph factory in this module.
    """
    registry.register("script_writer", SCRIPT_WRITER_REGISTRATION)
    registry.register("script_scorer", SCRIPT_QUALITY_SCORER_REGISTRATION)
    registry.register("fact_checker", FACT_CHECKER_REGISTRATION)
    registry.register("script_refiner", SCRIPT_REFINER_REGISTRATION)
    registry.register("script_packager", SCRIPT_PACKAGER_REGISTRATION)


def _route_after_scorer(state: IdeaToScriptState) -> str:
    """Conditional edge after script_scorer: decide whether to refine or accept.

    Returns "done" when:
      - `state.iteration >= state.max_iterations` (hard cap, never infinite), OR
      - `scorer_verdict == "continue"` (quality threshold met)

    Returns "retry" otherwise — graph increments iteration, runs refiner, loops
    back to writer.

    fact_checker is NOT consulted here — it runs exactly once on the "done" path
    after the loop exits (build_idea_to_script_graph), keeping it out of the hot
    refinement cycle to avoid repeated expensive web-search round-trips.

    This function is a pure graph edge, not a worker — it emits no artifact and
    records no WorkerExecution (D056 / D057).
    """
    if state.iteration >= state.max_iterations:
        return "done"
    if state.scorer_verdict == "continue":
        return "done"
    return "retry"


async def _increment_iteration(state: IdeaToScriptState) -> dict[str, Any]:
    """Non-worker node that increments the iteration counter on the retry path.

    Returns {"iteration": 1}; the Annotated[int, operator.add] reducer on
    IdeaToScriptState.iteration accumulates the total count (D057).
    """
    return {"iteration": 1}


def build_refine_loop_graph(
    *,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    anthropic_api_key: str,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Compile the idea→script cyclic StateGraph over IdeaToScriptState.

    Topology (loop-isolation only — no fact_checker):
      START → script_writer → script_scorer
            → conditional(_route_after_scorer):
                "done"  → END
                "retry" → increment_iteration → script_refiner → script_writer (cycle)

    fact_checker is intentionally excluded so loop-convergence tests remain
    fast and do not require web-search stubs. For the full pipeline including
    fact_checker use build_idea_to_script_graph().

    The caller must call register_idea_to_script_workers() before calling this
    function. The `checkpointer` defaults to MemorySaver().

    Raises WorkerNotRegisteredError at build time if any required worker is absent.
    """
    graph: StateGraph = StateGraph(IdeaToScriptState)

    graph.add_node(
        "script_writer",
        wrap(
            "script_writer",
            "script_drafts",
            build_script_writer_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "script_scorer",
        wrap(
            "script_scorer",
            "script_scores",
            build_script_quality_scorer_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
            control_channel="scorer_verdict",
        ),
    )
    graph.add_node("increment_iteration", _increment_iteration)
    graph.add_node(
        "script_refiner",
        wrap(
            "script_refiner",
            "script_drafts",
            build_script_refiner_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )

    graph.add_edge(START, "script_writer")
    graph.add_edge("script_writer", "script_scorer")
    graph.add_conditional_edges(
        "script_scorer",
        _route_after_scorer,
        {"done": END, "retry": "increment_iteration"},
    )
    graph.add_edge("increment_iteration", "script_refiner")
    graph.add_edge("script_refiner", "script_writer")

    return graph.compile(checkpointer=checkpointer or MemorySaver())


def build_idea_to_script_graph(
    *,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    anthropic_api_key: str,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Compile the full idea→script StateGraph with fact_checker + script_packager (P5-S5).

    fact_checker runs ONCE after the refinement loop converges, not on every iteration.
    This avoids repeated expensive web-search round-trips during refinement.

      START → script_writer → script_scorer
            → conditional(_route_after_scorer):
                "done"  → fact_checker → script_packager → END
                "retry" → increment_iteration → script_refiner → script_writer (cycle)

    Use this factory for the REST endpoint and Telegram handler.
    `build_refine_loop_graph()` (P5-S4) provides a fact_checker-free loop for
    loop-convergence tests.

    The caller must register all five workers with `register_idea_to_script_workers()`
    before calling this function. The `checkpointer` defaults to MemorySaver().

    Raises WorkerNotRegisteredError at build time if any worker is absent.
    """
    graph: StateGraph = StateGraph(IdeaToScriptState)

    graph.add_node(
        "script_writer",
        wrap(
            "script_writer",
            "script_drafts",
            build_script_writer_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "script_scorer",
        wrap(
            "script_scorer",
            "script_scores",
            build_script_quality_scorer_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
            control_channel="scorer_verdict",
        ),
    )
    graph.add_node(
        "fact_checker",
        wrap(
            "fact_checker",
            "factcheck_report",
            build_fact_checker_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
            control_channel="factcheck_verdict",
        ),
    )
    graph.add_node("increment_iteration", _increment_iteration)
    graph.add_node(
        "script_refiner",
        wrap(
            "script_refiner",
            "script_drafts",
            build_script_refiner_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "script_packager",
        wrap(
            "script_packager",
            "script",
            build_script_packager_worker(storage),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )

    graph.add_edge(START, "script_writer")
    graph.add_edge("script_writer", "script_scorer")
    graph.add_conditional_edges(
        "script_scorer",
        _route_after_scorer,
        {"done": "fact_checker", "retry": "increment_iteration"},
    )
    graph.add_edge("fact_checker", "script_packager")
    graph.add_edge("increment_iteration", "script_refiner")
    graph.add_edge("script_refiner", "script_writer")
    graph.add_edge("script_packager", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
