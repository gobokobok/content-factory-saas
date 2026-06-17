"""idea_to_script refine loop (P5-S4) — writer → scorer → fact_checker → refine (cyclic).

Assembles the cyclic Idea→Script loop as a LangGraph StateGraph over
IdeaToScriptState. Each iteration runs:

  script_writer     → state.artifacts["script_drafts"]  (ScriptDraftsArtifact)
  script_scorer     → state.artifacts["script_scores"]   (ScriptScoresArtifact)
                                                          state.scorer_verdict
  fact_checker      → state.artifacts["factcheck_report"](FactcheckReportArtifact)
                                                          state.factcheck_verdict

After each scorer+fact_checker pass the graph checks `_route_after_evaluation`:
  - "done"  if iteration >= max_iterations OR both verdicts are "continue"
  - "retry" otherwise → increment_iteration node sets {"iteration": 1}
              → script_refiner produces improved script_drafts → back to writer

The terminal "script" artifact and REST/Telegram interface land in P5-S5.

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
from cf_platform.workers.script_quality_scorer import (
    SCRIPT_QUALITY_SCORER_REGISTRATION,
    build_script_quality_scorer_worker,
)
from cf_platform.workers.script_refiner import SCRIPT_REFINER_REGISTRATION, build_script_refiner_worker
from cf_platform.workers.script_writer import SCRIPT_WRITER_REGISTRATION, build_script_writer_worker


def register_idea_to_script_workers(registry: WorkerRegistry) -> None:
    """Register all four idea_to_script workers in registry (idempotent re-register is fine).

    Call once at startup before build_refine_loop_graph() — wrap() resolves each
    worker's pinned config from the registry at graph-build time.
    """
    registry.register("script_writer", SCRIPT_WRITER_REGISTRATION)
    registry.register("script_scorer", SCRIPT_QUALITY_SCORER_REGISTRATION)
    registry.register("fact_checker", FACT_CHECKER_REGISTRATION)
    registry.register("script_refiner", SCRIPT_REFINER_REGISTRATION)


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
