"""Full pipeline orchestrator (P6-S2) — niche_to_ideas → idea_to_script → legacy_render.

Composes the three pipeline blocks as a 3-node parent graph over PipelineState.
Each block runs as a wrapper node that constructs a block-specific state, invokes
the block's subgraph, and returns only the terminal artifact ref to the parent.
The legacy_render node is a plain async node (adapter is IO, not a worker — D057).

Lineage threads end-to-end via run_id:
  niche_to_ideas   → parent.artifacts["ranked_ideas"]
  idea_to_script   → parent.artifacts["script"]
  legacy_render    → parent.artifacts["video"]

Canonical spec: docs/v2_platform_plan.md §5 · PipelineState contract.
"""

import logging
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cf_platform.adapters.legacy_video import InProcessLegacyVideoAdapter, LegacyVideoAdapter
from cf_platform.blocks.idea_to_script import build_idea_to_script_graph
from cf_platform.blocks.niche_to_ideas import build_niche_to_ideas_graph
from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage, read_artifact
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.schemas import IdeaToScriptState, NicheToIdeasState, PipelineState, SourceAdapter
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact

logger = logging.getLogger(__name__)


def build_full_pipeline_graph(
    *,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    adapters: list[tuple[str, SourceAdapter]],
    trace_repo: TraceEventRepository,
    anthropic_api_key: str,
    legacy_adapter: Optional[LegacyVideoAdapter] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> CompiledStateGraph:
    """Compile the full pipeline StateGraph over PipelineState (P6-S2).

    Topology:
      START → niche_to_ideas → idea_to_script → legacy_render → END

    Each block node builds a block-specific initial state from PipelineState,
    runs the corresponding compiled subgraph, and writes only the terminal
    artifact ref back to the parent state.  The legacy_render node calls the
    adapter and writes `video` directly — the adapter is IO, not a worker (D057).

    `legacy_adapter` defaults to InProcessLegacyVideoAdapter() (lazy settings
    load).  Inject a mock or HTTP impl for testing or future HTTP swap-out.

    The caller must have already registered all block workers in `registry`
    (register_niche_to_ideas_workers + register_idea_to_script_workers).
    `checkpointer` defaults to MemorySaver() (in-process).
    """
    niche_graph = build_niche_to_ideas_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifact_repo,
        adapters=adapters,
        trace_repo=trace_repo,
        anthropic_api_key=anthropic_api_key,
    )
    script_graph = build_idea_to_script_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifact_repo,
        anthropic_api_key=anthropic_api_key,
    )
    _adapter: LegacyVideoAdapter = legacy_adapter or InProcessLegacyVideoAdapter()

    async def niche_to_ideas_node(state: PipelineState) -> dict[str, Any]:
        """Run the niche→ideas block; return ranked_ideas artifact ref."""
        block_state = NicheToIdeasState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs=state.inputs,
            artifacts={},
        )
        result = await run_graph(
            niche_graph,
            block_state,
            thread_id=f"{state.run_id}:niche_to_ideas",
        )
        return {"artifacts": {"ranked_ideas": result.artifacts["ranked_ideas"]}}

    async def idea_to_script_node(state: PipelineState) -> dict[str, Any]:
        """Run the idea→script block; return script artifact ref.

        Reads the ranked_ideas artifact to extract the selected idea_title so that
        context_normalizer receives a clean inputs dict (idea_title + niche).
        Passes target_duration_seconds from PipelineState into IdeaToScriptState.
        """
        ranked_r2_key = state.artifacts["ranked_ideas"]
        _, ranked_body = await read_artifact(storage, ranked_r2_key)
        ranked = RankedIdeasArtifact.model_validate(ranked_body)

        block_inputs: dict[str, Any] = {"idea_title": ranked.selected.title}
        niche = state.inputs.get("niche")
        if niche:
            block_inputs["niche"] = niche

        block_state = IdeaToScriptState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs=block_inputs,
            artifacts={},
            target_duration_seconds=state.target_duration_seconds,
        )
        result = await run_graph(
            script_graph,
            block_state,
            thread_id=f"{state.run_id}:idea_to_script",
        )
        return {"artifacts": {"script": result.artifacts["script"]}}

    async def legacy_render_node(state: PipelineState) -> dict[str, Any]:
        """Call the legacy video adapter; return video r2_key.

        The adapter is IO, not a worker (D057) — it emits TraceEvents, not
        platform artifacts.  This node bridges the adapter result into the
        parent state by writing the R2 key directly into artifacts["video"].
        """
        script_r2_key = state.artifacts["script"]
        _, script_body = await read_artifact(storage, script_r2_key)
        script_artifact = ScriptArtifact.model_validate(script_body)

        result = await _adapter.render(
            run_id=state.run_id,
            script=script_artifact.script,
            trace_repo=trace_repo,
        )
        if result.status == "failed":
            raise RuntimeError(f"Legacy render failed: {result.error}")
        return {"artifacts": {"video": result.r2_key}}

    graph: StateGraph = StateGraph(PipelineState)
    graph.add_node("niche_to_ideas", niche_to_ideas_node)
    graph.add_node("idea_to_script", idea_to_script_node)
    graph.add_node("legacy_render", legacy_render_node)

    graph.add_edge(START, "niche_to_ideas")
    graph.add_edge("niche_to_ideas", "idea_to_script")
    graph.add_edge("idea_to_script", "legacy_render")
    graph.add_edge("legacy_render", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
