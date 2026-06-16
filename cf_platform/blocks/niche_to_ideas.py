"""niche_to_ideas StateGraph (P4-S4) — discovery → topic_generator → opportunity_scorer → topic_selector.

Assembles the Niche→Ideas block as a 4-node linear LangGraph StateGraph over
NicheToIdeasState. One run produces 4 artifacts and 4 WorkerExecution rows:
  discovery          → state.artifacts["discovery"]        (SignalsArtifact)
  topic_generator    → state.artifacts["candidate_topics"] (CandidateTopicsArtifact)
  opportunity_scorer → state.artifacts["scored_topics"]    (ScoredTopicsArtifact)
  topic_selector     → state.artifacts["ranked_ideas"]     (RankedIdeasArtifact, terminal)

Each node is wrapped via the Layer B observability wrapper (wrap()), which writes the
artifact to R2, records the lineage row in Postgres, and records a WorkerExecution.

Canonical spec: docs/v2_platform_plan.md §5.
"""

from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.schemas import NicheToIdeasState, SourceAdapter
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry, wrap
from cf_platform.workers.discovery import DISCOVERY_REGISTRATION, build_discovery_worker
from cf_platform.workers.opportunity_scorer import OPPORTUNITY_SCORER_REGISTRATION, build_opportunity_scorer_worker
from cf_platform.workers.topic_generator import TOPIC_GENERATOR_REGISTRATION, build_topic_generator_worker
from cf_platform.workers.topic_selector import TOPIC_SELECTOR_REGISTRATION, build_topic_selector_worker


def register_niche_to_ideas_workers(registry: WorkerRegistry) -> None:
    """Register all four niche_to_ideas workers in registry (idempotent re-register is fine).

    Call once at startup — must be done before build_niche_to_ideas_graph() is called,
    because wrap() resolves each worker's pinned config from the registry at graph-build time.
    """
    registry.register("discovery", DISCOVERY_REGISTRATION)
    registry.register("topic_generator", TOPIC_GENERATOR_REGISTRATION)
    registry.register("opportunity_scorer", OPPORTUNITY_SCORER_REGISTRATION)
    registry.register("topic_selector", TOPIC_SELECTOR_REGISTRATION)


def build_niche_to_ideas_graph(
    *,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    adapters: list[tuple[str, SourceAdapter]],
    trace_repo: TraceEventRepository,
    anthropic_api_key: str,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Compile the niche→ideas StateGraph over NicheToIdeasState.

    Nodes run sequentially: START → discovery → topic_generator → opportunity_scorer
    → topic_selector → END. Each node is wrapped via the Layer B observability wrapper,
    so each execution writes one versioned R2 artifact, one Postgres lineage row (via
    artifact_repo), and one WorkerExecution (via executions).

    The caller must register the four workers in registry before calling this function
    (use register_niche_to_ideas_workers). The `checkpointer` defaults to MemorySaver()
    (in-process); pass a PostgresSaver for durable, restart-resumable checkpoints
    (P2-S4 pattern).

    Raises WorkerNotRegisteredError immediately at build time if any worker is absent
    from registry.
    """
    graph = StateGraph(NicheToIdeasState)

    graph.add_node(
        "discovery",
        wrap(
            "discovery",
            "discovery",
            build_discovery_worker(adapters, trace_repo),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "topic_generator",
        wrap(
            "topic_generator",
            "candidate_topics",
            build_topic_generator_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "opportunity_scorer",
        wrap(
            "opportunity_scorer",
            "scored_topics",
            build_opportunity_scorer_worker(storage, anthropic_api_key),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_node(
        "topic_selector",
        wrap(
            "topic_selector",
            "ranked_ideas",
            build_topic_selector_worker(storage),
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )

    graph.add_edge(START, "discovery")
    graph.add_edge("discovery", "topic_generator")
    graph.add_edge("topic_generator", "opportunity_scorer")
    graph.add_edge("opportunity_scorer", "topic_selector")
    graph.add_edge("topic_selector", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
