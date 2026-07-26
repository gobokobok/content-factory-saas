"""idea_to_script block — Blueprint IR pipeline (P5-S6/P5-S7, D058/D059/D060).

Replaces the cyclic write→score→fact-check→refine loop with a deterministic
content compiler: context → blueprint → eval → merge → narrative lens → hook
→ script → integrity check → targeted patch repair (max 2 cycles) → package.

Graph topology (build_idea_to_script_graph):

  START
    → context_normalization   [0] deterministic
    → blueprint_generation    [1] Sonnet
    → evaluation              [2] Sonnet
    → blueprint_merge         [3] deterministic
    → narrative_lens          [4] Haiku — storytelling angles from verified facts only (D059)
    → hook_generation         [5] Haiku
    → hook_selection          [6] Haiku
    → script_generation       [7] Sonnet — single pass, never retried
    → integrity_check         [8] Haiku
        "continue" → script_packager → END
        "retry"    → _increment_integrity_loops
                    → patch_generator   [9]  Haiku
                    → apply_patch       [10] deterministic
                    → integrity_check   (cycle, max MAX_INTEGRITY_LOOPS=2)
        "manual_review" → script_packager → END (status=manual_review)

`integrity_verdict` is a typed control channel on IdeaToScriptState (D057).
`integrity_loops` uses Annotated[int, operator.add] so the increment node is
a pure non-worker that returns {"integrity_loops": 1}.

Canonical spec: docs/v2_platform_plan.md §5 · D058/D059/D060.
"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.schemas import IdeaToScriptState
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry, wrap
from cf_platform.workers.blueprint_generator import (
    BLUEPRINT_GENERATOR_REGISTRATION,
    build_blueprint_generator_worker,
)
from cf_platform.workers.blueprint_merger import (
    BLUEPRINT_MERGER_REGISTRATION,
    build_blueprint_merger_worker,
)
from cf_platform.workers.context_normalizer import (
    CONTEXT_NORMALIZER_REGISTRATION,
    build_context_normalizer_worker,
)
from cf_platform.workers.evaluator import EVALUATOR_REGISTRATION, build_evaluator_worker
from cf_platform.workers.hook_generator import (
    HOOK_GENERATOR_REGISTRATION,
    build_hook_generator_worker,
)
from cf_platform.workers.hook_selector import (
    HOOK_SELECTOR_REGISTRATION,
    build_hook_selector_worker,
)
from cf_platform.workers.integrity_checker import (
    INTEGRITY_CHECKER_REGISTRATION,
    build_integrity_checker_worker,
)
from cf_platform.workers.narrative_lens import (
    NARRATIVE_LENS_REGISTRATION,
    build_narrative_lens_worker,
)
from cf_platform.workers.patch_applier import (
    PATCH_APPLIER_REGISTRATION,
    build_patch_applier_worker,
)
from cf_platform.workers.patch_generator import (
    PATCH_GENERATOR_REGISTRATION,
    build_patch_generator_worker,
)
from cf_platform.workers.script_generator import (
    SCRIPT_GENERATOR_REGISTRATION,
    build_script_generator_worker,
)
from cf_platform.workers.script_packager import (
    SCRIPT_PACKAGER_REGISTRATION,
    build_script_packager_worker,
)

# Maximum number of patch-repair cycles before routing to manual_review (D058).
MAX_INTEGRITY_LOOPS = 2


def register_idea_to_script_workers(registry: WorkerRegistry) -> None:
    """Register all 12 idea_to_script workers in registry (idempotent re-register is fine).

    Workers: context_normalizer, blueprint_generator, evaluator, blueprint_merger,
    narrative_lens, hook_generator, hook_selector, script_generator,
    integrity_checker, patch_generator, patch_applier, script_packager.

    Call once at startup before building the graph factory.
    """
    registry.register("context_normalizer", CONTEXT_NORMALIZER_REGISTRATION)
    registry.register("blueprint_generator", BLUEPRINT_GENERATOR_REGISTRATION)
    registry.register("evaluator", EVALUATOR_REGISTRATION)
    registry.register("blueprint_merger", BLUEPRINT_MERGER_REGISTRATION)
    registry.register("narrative_lens", NARRATIVE_LENS_REGISTRATION)
    registry.register("hook_generator", HOOK_GENERATOR_REGISTRATION)
    registry.register("hook_selector", HOOK_SELECTOR_REGISTRATION)
    registry.register("script_generator", SCRIPT_GENERATOR_REGISTRATION)
    registry.register("integrity_checker", INTEGRITY_CHECKER_REGISTRATION)
    registry.register("patch_generator", PATCH_GENERATOR_REGISTRATION)
    registry.register("patch_applier", PATCH_APPLIER_REGISTRATION)
    registry.register("script_packager", SCRIPT_PACKAGER_REGISTRATION)


def _route_after_integrity(state: IdeaToScriptState) -> str:
    """Conditional edge after integrity_check: route to pass, repair, or manual_review.

    Returns:
      "pass"          — integrity passed; go to script_packager
      "manual_review" — integrity failed and repair budget is exhausted; go to
                        script_packager with status=manual_review
      "fail"          — integrity failed and budget remains; go to repair cycle

    This function is a pure graph edge, not a worker — emits no artifact and
    records no WorkerExecution (D056 / D057).
    """
    if state.integrity_verdict == "continue":  # integrity_check set "continue" = pass
        return "pass"
    if state.integrity_loops >= MAX_INTEGRITY_LOOPS:
        return "manual_review"
    return "fail"


async def _increment_integrity_loops(state: IdeaToScriptState) -> dict[str, Any]:
    """Non-worker node: increment integrity_loops before the patch repair cycle.

    Returns {"integrity_loops": 1}; the Annotated[int, operator.add] reducer
    on IdeaToScriptState.integrity_loops accumulates the total count (D057).
    """
    return {"integrity_loops": 1}


def build_idea_to_script_graph(
    *,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    anthropic_api_key: str,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile the full idea→script Blueprint IR StateGraph over IdeaToScriptState (P5-S6/P5-S7).

    Topology:
      START → context_normalization → blueprint_generation → evaluation
            → blueprint_merge → narrative_lens → hook_generation → hook_selection
            → script_generation → integrity_check
            → conditional(_route_after_integrity):
                "pass"          → script_packager → END
                "fail"          → _increment_integrity_loops
                                → patch_generator → apply_patch
                                → integrity_check (cycle)
                "manual_review" → script_packager → END

    The caller must call register_idea_to_script_workers() before calling this
    function. `checkpointer` defaults to MemorySaver().

    Raises WorkerNotRegisteredError at build time if any required worker is absent.
    """
    graph: StateGraph = StateGraph(IdeaToScriptState)

    _w = lambda worker, node, builder: wrap(  # noqa: E731
        worker,
        node,
        builder,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    graph.add_node(
        "context_normalization",
        _w("context_normalizer", "normalized_context", build_context_normalizer_worker()),
    )
    graph.add_node(
        "blueprint_generation",
        _w(
            "blueprint_generator",
            "blueprint",
            build_blueprint_generator_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "evaluation",
        _w("evaluator", "evaluation", build_evaluator_worker(storage, anthropic_api_key)),
    )
    graph.add_node(
        "blueprint_merge",
        _w("blueprint_merger", "merged_blueprint", build_blueprint_merger_worker(storage)),
    )
    graph.add_node(
        "narrative_lens",
        _w(
            "narrative_lens",
            "narrative_lens",
            build_narrative_lens_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "hook_generation",
        _w(
            "hook_generator",
            "hook_variants",
            build_hook_generator_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "hook_selection",
        _w(
            "hook_selector",
            "selected_hook",
            build_hook_selector_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "script_generation",
        _w(
            "script_generator",
            "generated_script",
            build_script_generator_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "integrity_check",
        wrap(
            "integrity_checker",
            "integrity_report",
            build_integrity_checker_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
            control_channel="integrity_verdict",
        ),
    )
    graph.add_node("_increment_integrity_loops", _increment_integrity_loops)
    graph.add_node(
        "patch_generation",
        _w(
            "patch_generator",
            "patches",
            build_patch_generator_worker(storage, anthropic_api_key),
        ),
    )
    graph.add_node(
        "apply_patch",
        _w("patch_applier", "generated_script", build_patch_applier_worker(storage)),
    )
    graph.add_node(
        "script_packager",
        _w("script_packager", "script", build_script_packager_worker(storage)),
    )

    # Linear spine
    graph.add_edge(START, "context_normalization")
    graph.add_edge("context_normalization", "blueprint_generation")
    graph.add_edge("blueprint_generation", "evaluation")
    graph.add_edge("evaluation", "blueprint_merge")
    graph.add_edge("blueprint_merge", "narrative_lens")
    graph.add_edge("narrative_lens", "hook_generation")
    graph.add_edge("hook_generation", "hook_selection")
    graph.add_edge("hook_selection", "script_generation")
    graph.add_edge("script_generation", "integrity_check")

    # Conditional routing after integrity_check
    graph.add_conditional_edges(
        "integrity_check",
        _route_after_integrity,
        {
            "pass": "script_packager",
            "fail": "_increment_integrity_loops",
            "manual_review": "script_packager",
        },
    )

    # Patch repair cycle
    graph.add_edge("_increment_integrity_loops", "patch_generation")
    graph.add_edge("patch_generation", "apply_patch")
    graph.add_edge("apply_patch", "integrity_check")

    # Terminal
    graph.add_edge("script_packager", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
