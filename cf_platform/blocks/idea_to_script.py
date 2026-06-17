"""idea_to_script block — writer → scorer → fact_checker → refine (cyclic) → packager.

Provides two graph factories:

  build_refine_loop_graph  (P5-S4) — cyclic loop only, ends at END after convergence.
                                      Used by loop-isolation tests.

  build_idea_to_script_graph (P5-S5) — full assembled block; routes "done" to a
                                        terminal script_packager node that emits the
                                        final `ScriptArtifact`. Use for REST + Telegram.

Graph topology (build_idea_to_script_graph):

  START → script_writer → script_scorer → fact_checker
        → conditional(_route_after_evaluation):
            "done"  → script_packager → END
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


def _route_after_evaluation(state: IdeaToScriptState) -> str:
    """Conditional edge: decide whether to accept the current drafts or retry.

    Returns "done" when:
      - `state.iteration >= state.max_iterations` (hard cap, never infinite), OR
      - both scorer_verdict and factcheck_verdict are "continue" (quality passed)

    Returns "retry" otherwise — graph will increment the iteration counter and
    run the refiner before looping back to the writer.

    This function is a pure graph edge, not a worker — it emits no artifact and
    records no WorkerExecution (D056 / D057).
    """
    if state.iteration >= state.max_iterations:
        return "done"
    if state.scorer_verdict == "continue" and state.factcheck_verdict == "continue":
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

    Graph topology:
      START → script_writer → script_scorer → fact_checker
            → conditional(route_after_evaluation):
                "done"  → END
                "retry" → increment_iteration → script_refiner → script_writer (cycle)

    Each worker node is wrapped via the Layer B observability wrapper so every
    execution writes one versioned R2 artifact, one Postgres lineage row, and one
    WorkerExecution row.

    scorer and fact_checker wrap() calls supply control_channel so their routing
    signals are stored as typed state fields on IdeaToScriptState (D057).

    The caller must register the four workers with register_idea_to_script_workers()
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

    graph.add_edge(START, "script_writer")
    graph.add_edge("script_writer", "script_scorer")
    graph.add_edge("script_scorer", "fact_checker")
    graph.add_conditional_edges(
        "fact_checker",
        _route_after_evaluation,
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
    """Compile the full idea→script StateGraph with terminal script_packager (P5-S5).

    Extends the refine loop with a `script_packager` node on the "done" path so the
    graph always terminates with a `ScriptArtifact` in `state.artifacts["script"]`:

      START → script_writer → script_scorer → fact_checker
            → conditional(route_after_evaluation):
                "done"  → script_packager → END
                "retry" → increment_iteration → script_refiner → script_writer (cycle)

    Use this factory for the REST endpoint and Telegram handler.
    `build_refine_loop_graph()` (P5-S4) remains unchanged for loop-isolation tests.

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
    graph.add_edge("script_scorer", "fact_checker")
    graph.add_conditional_edges(
        "fact_checker",
        _route_after_evaluation,
        {"done": "script_packager", "retry": "increment_iteration"},
    )
    graph.add_edge("increment_iteration", "script_refiner")
    graph.add_edge("script_refiner", "script_writer")
    graph.add_edge("script_packager", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
