"""Full pipeline orchestrator (P6-S2, P6-S3, P7-S2, P9-S5) — niche_to_ideas → idea_to_script
→ [gate?] → youtube_metadata → voice_production → storyboard_worker → acquisition_worker
→ render_worker.

Composes the three pipeline blocks as a parent graph over PipelineState, followed by three
native production workers (P9-S5 — InProcessLegacyVideoAdapter retired from active call path).

P6-S3 adds the HITL script-approval gate between idea_to_script and youtube_metadata:
  - hitl=False (default): gate is bypassed; fully autonomous path unchanged.
  - hitl=True: gate calls interrupt(); graph pauses until operator resumes via
    POST /runs/{id}/resume.  Auto-approve via HITL_TIMEOUT_SECONDS is wired by
    the caller (cf_platform/orchestrator/hitl.py).

Lineage threads end-to-end via run_id:
  niche_to_ideas        → parent.artifacts["ranked_ideas"]
  idea_to_script        → parent.artifacts["script"]
  script_approval_gate  → (no artifact — gate is IO/control only, D057)
  youtube_metadata      → parent.artifacts["youtube_metadata"]
  voice_production      → parent.artifacts["voice_alignment"]
  storyboard_worker     → parent.artifacts["verified_storyboard"]
  acquisition_worker    → parent.artifacts["asset_manifest"]
  render_worker         → parent.artifacts["video"]   (R2 key for final.mp4)

Canonical spec: docs/v2_platform_plan.md §5 · PipelineState contract.
"""

import logging
from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from cf_platform.adapters.legacy_video import InProcessLegacyVideoAdapter, LegacyVideoAdapter
from cf_platform.blocks.idea_to_script import build_idea_to_script_graph
from cf_platform.blocks.niche_to_ideas import build_niche_to_ideas_graph
from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage, read_artifact
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.schemas import IdeaToScriptState, NicheToIdeasState, PipelineState, SourceAdapter, StageState
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry, build_observed_node_graph
from cf_platform.workers.acquisition_worker import (
    ACQUISITION_WORKER_REGISTRATION,
    build_acquisition_worker,
)
from cf_platform.workers.render_worker import (
    RENDER_WORKER_REGISTRATION,
    RenderArtifact,
    build_render_worker,
)
from cf_platform.workers.storyboard_worker import (
    STORYBOARD_WORKER_REGISTRATION,
    build_storyboard_worker,
)
from cf_platform.workers.visual_director_worker import (
    VISUAL_DIRECTOR_REGISTRATION,
    build_visual_director_worker,
)
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.voice_production import (
    VOICE_PRODUCTION_REGISTRATION,
    build_voice_production_worker,
)
from cf_platform.workers.youtube_metadata import (
    YOUTUBE_METADATA_REGISTRATION,
    build_youtube_metadata_worker,
)

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
    legacy_adapter: Optional[LegacyVideoAdapter] = None,  # DEPRECATED — no longer used (P9-S5)
    checkpointer: Optional[BaseCheckpointSaver] = None,
    gemini_api_key: str = "",
    gemini_tts_voice: str = "",
    deepgram_api_key: str = "",
    pexels_api_key: str = "",
    pixabay_api_key: str = "",
    color_grade_preset: str = "neutral",
    blur_fill_enabled: bool = True,
    ffmpeg_timeout_seconds: int = 1800,
) -> CompiledStateGraph:
    """Compile the full pipeline StateGraph over PipelineState (P6-S2, P9-S5).

    Topology:
      START → niche_to_ideas → idea_to_script → [gate?] → youtube_metadata
            → voice_production → storyboard_worker → acquisition_worker → render_worker → END

    Nodes:
      niche_to_ideas / idea_to_script — delegate to compiled subgraphs via run_graph.
      script_approval_gate — HITL interrupt when PipelineState.hitl=True.
      youtube_metadata — observed worker graph (Haiku, single call).
      voice_production — Gemini TTS + Deepgram alignment; observed via wrap().
      storyboard_worker — observed worker graph; generate→review→patch; emits verified_storyboard.
      acquisition_worker — observed worker graph; segment routing + QA gate; emits asset_manifest.
      render_worker — observed worker graph; reads render_options; emits render_script.sh + final.mp4.

    `legacy_adapter` is accepted for backward compatibility but is NOT used (P9-S5 — native
    production chain replaces InProcessLegacyVideoAdapter in the active call path).

    Gemini / Deepgram keys default to empty (D048 fault isolation); a missing key causes
    voice_production to use proportional_fallback timestamps instead.

    The caller must have already registered all block workers in `registry`
    (register_niche_to_ideas_workers + register_idea_to_script_workers + voice_production).
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

    # ── YouTube metadata — build observed graph once at compile time ─────
    registry.register("youtube_metadata", YOUTUBE_METADATA_REGISTRATION)
    metadata_worker = build_youtube_metadata_worker(
        storage=storage,
        anthropic_api_key=anthropic_api_key,
    )
    metadata_graph = build_observed_node_graph(
        "youtube_metadata",
        "youtube_metadata",
        metadata_worker,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    # ── Voice production — build observed graph once at compile time ──────
    registry.register("voice_production", VOICE_PRODUCTION_REGISTRATION)
    voice_worker = build_voice_production_worker(
        storage=storage,
        gemini_api_key=gemini_api_key,
        gemini_tts_voice=gemini_tts_voice,
        deepgram_api_key=deepgram_api_key,
    )
    voice_graph = build_observed_node_graph(
        "voice_alignment",
        "voice_production",
        voice_worker,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    # ── Native storyboard worker — build observed graph once at compile time ─
    registry.register("storyboard_worker", STORYBOARD_WORKER_REGISTRATION)
    storyboard_worker_fn = build_storyboard_worker(
        storage=storage,
        anthropic_api_key=anthropic_api_key,
    )
    storyboard_graph = build_observed_node_graph(
        "verified_storyboard",
        "storyboard_worker",
        storyboard_worker_fn,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    # ── Visual Director worker — build observed graph once at compile time ──────
    registry.register("visual_director_worker", VISUAL_DIRECTOR_REGISTRATION)
    visual_director_worker_fn = build_visual_director_worker(
        storage=storage,
        anthropic_api_key=anthropic_api_key,
    )
    visual_director_graph = build_observed_node_graph(
        "visual_treatment",
        "visual_director_worker",
        visual_director_worker_fn,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    # ── Native acquisition worker — build observed graph once at compile time ─
    registry.register("acquisition_worker", ACQUISITION_WORKER_REGISTRATION)
    acquisition_worker_fn = build_acquisition_worker(
        storage=storage,
        pexels_api_key=pexels_api_key,
        pixabay_api_key=pixabay_api_key,
    )
    acquisition_graph = build_observed_node_graph(
        "asset_manifest",
        "acquisition_worker",
        acquisition_worker_fn,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

    # ── Native render worker — build observed graph once at compile time ─────
    registry.register("render_worker", RENDER_WORKER_REGISTRATION)
    render_worker_fn = build_render_worker(
        storage=storage,
        color_grade_preset=color_grade_preset,
        blur_fill_enabled=blur_fill_enabled,
        ffmpeg_timeout_seconds=ffmpeg_timeout_seconds,
    )
    render_graph = build_observed_node_graph(
        "render_artifact",
        "render_worker",
        render_worker_fn,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifact_repo,
    )

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

        When PipelineState.idea_title is set (P7-S1 /pick flow), uses it directly
        and skips reading the ranked_ideas artifact. Otherwise reads ranked_ideas to
        extract the selected title from the niche→ideas block output.
        Passes target_duration_seconds from PipelineState into IdeaToScriptState.
        """
        if state.idea_title:
            block_inputs: dict[str, Any] = {"idea_title": state.idea_title}
            niche = state.inputs.get("niche")
            if niche:
                block_inputs["niche"] = niche
        else:
            ranked_r2_key = state.artifacts["ranked_ideas"]
            _, ranked_body = await read_artifact(storage, ranked_r2_key)
            ranked = RankedIdeasArtifact.model_validate(ranked_body)
            block_inputs = {"idea_title": ranked.selected.title}
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

    async def youtube_metadata_node(state: PipelineState) -> dict[str, Any]:
        """Generate YouTube metadata from the script artifact; return youtube_metadata ref."""
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={"niche": state.inputs.get("niche", "")},
            artifacts={"script": state.artifacts["script"]},
        )
        result = await run_graph(metadata_graph, block_state, thread_id=f"{state.run_id}:youtube_metadata")
        return {"artifacts": {"youtube_metadata": result.artifacts["youtube_metadata"]}}

    async def voice_production_node(state: PipelineState) -> dict[str, Any]:
        """Run TTS + alignment; return voice_alignment artifact ref.

        Bridges PipelineState → StageState so the observed voice_production graph
        can run with the script artifact key as its only input, then merges the
        resulting voice_alignment key back into the parent state.
        """
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={},
            artifacts={"script": state.artifacts["script"]},
        )
        result = await run_graph(voice_graph, block_state, thread_id=f"{state.run_id}:voice_production")
        return {"artifacts": {"voice_alignment": result.artifacts["voice_alignment"]}}

    async def script_approval_gate(state: PipelineState) -> dict[str, Any]:
        """Pause for operator script approval when PipelineState.hitl=True (P6-S3).

        Calls interrupt() with the run_id and script R2 key so the caller can
        surface the script to the operator (via Telegram or REST) without the
        gate needing a Telegram/notification dependency.

        Resume values:
          "approve" → returns empty dict; execution continues to youtube_metadata.
          "reject"  → raises RuntimeError; run fails.

        The gate emits no artifact and writes nothing to state (D057 — gate is
        control-only; the script artifact was already produced by idea_to_script).
        """
        decision = interrupt(
            {
                "type": "script_approval",
                "run_id": state.run_id,
                "script_r2_key": state.artifacts["script"],
            }
        )
        if decision == "reject":
            raise RuntimeError(f"Script rejected by operator for run {state.run_id}")
        return {}

    async def storyboard_node(state: PipelineState) -> dict[str, Any]:
        """Run the StoryboardWorker; return verified_storyboard artifact ref.

        Passes script + optional voice_alignment into the observed storyboard graph.
        The worker runs generate→review→patch internally and emits a single
        verified_storyboard artifact with render_options populated per scene.
        """
        sb_artifacts: dict[str, str] = {"script": state.artifacts["script"]}
        if state.artifacts.get("voice_alignment"):
            sb_artifacts["voice_alignment"] = state.artifacts["voice_alignment"]
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={"format_track": state.format_track},
            artifacts=sb_artifacts,
        )
        result = await run_graph(storyboard_graph, block_state, thread_id=f"{state.run_id}:storyboard_worker")
        return {"artifacts": {"verified_storyboard": result.artifacts["verified_storyboard"]}}

    async def visual_director_node(state: PipelineState) -> dict[str, Any]:
        """Run the VisualDirectorWorker; return visual_treatment artifact ref.

        Receives the enriched verified_storyboard; produces a per-scene visual plan
        (shot type, search terms, motion, diversity strategy) consumed by the
        AcquisitionWorker.
        """
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={},
            artifacts={"verified_storyboard": state.artifacts["verified_storyboard"]},
        )
        result = await run_graph(
            visual_director_graph, block_state, thread_id=f"{state.run_id}:visual_director_worker"
        )
        return {"artifacts": {"visual_treatment": result.artifacts["visual_treatment"]}}

    async def acquisition_node(state: PipelineState) -> dict[str, Any]:
        """Run the AcquisitionWorker; return asset_manifest artifact ref.

        Reads verified_storyboard and optional visual_treatment from state; routes each
        scene by segment_type; prefers Visual Director search_terms; three-tier STK
        cascade with QA gate. Also writes footage_summary.json side-car to R2 for
        Telegram reply consumption.
        """
        acq_artifacts: dict[str, str] = {
            "verified_storyboard": state.artifacts["verified_storyboard"],
        }
        if state.artifacts.get("visual_treatment"):
            acq_artifacts["visual_treatment"] = state.artifacts["visual_treatment"]
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={},
            artifacts=acq_artifacts,
        )
        result = await run_graph(acquisition_graph, block_state, thread_id=f"{state.run_id}:acquisition_worker")
        return {"artifacts": {"asset_manifest": result.artifacts["asset_manifest"]}}

    async def render_node(state: PipelineState) -> dict[str, Any]:
        """Run the RenderWorker; return the final.mp4 R2 key as artifacts["video"].

        Passes verified_storyboard + asset_manifest + optional voice_alignment to the
        observed render graph. Reads the resulting RenderArtifact to extract the raw
        video_key (R2 path to final.mp4) and surfaces it as "video" in PipelineState
        so _run_pipeline_and_reply can generate a presigned URL directly.
        """
        render_artifacts: dict[str, str] = {
            "verified_storyboard": state.artifacts["verified_storyboard"],
            "asset_manifest": state.artifacts["asset_manifest"],
        }
        if state.artifacts.get("voice_alignment"):
            render_artifacts["voice_alignment"] = state.artifacts["voice_alignment"]
        block_state = StageState(
            run_id=state.run_id,
            user_id=state.user_id,
            inputs={"format_track": state.format_track},
            artifacts=render_artifacts,
        )
        result = await run_graph(render_graph, block_state, thread_id=f"{state.run_id}:render_worker")
        # Extract the actual MP4 R2 key from the RenderArtifact envelope.
        render_artifact_key = result.artifacts["render_artifact"]
        _, render_body = await read_artifact(storage, render_artifact_key)
        render_art = RenderArtifact.model_validate(render_body)
        return {"artifacts": {"video": render_art.video_key}}

    def _route_start(state: PipelineState) -> str:
        """Skip niche_to_ideas when idea_title is already known (P7-S1 /pick flow)."""
        return "idea_to_script" if state.idea_title else "niche_to_ideas"

    def _route_after_script(state: PipelineState) -> str:
        """Route to the HITL gate when hitl=True; otherwise go to youtube_metadata."""
        return "script_approval_gate" if state.hitl else "youtube_metadata"

    graph: StateGraph = StateGraph(PipelineState)
    graph.add_node("niche_to_ideas", niche_to_ideas_node)
    graph.add_node("idea_to_script", idea_to_script_node)
    graph.add_node("script_approval_gate", script_approval_gate)
    graph.add_node("youtube_metadata", youtube_metadata_node)
    graph.add_node("voice_production", voice_production_node)
    graph.add_node("storyboard_worker", storyboard_node)
    graph.add_node("visual_director_worker", visual_director_node)
    graph.add_node("acquisition_worker", acquisition_node)
    graph.add_node("render_worker", render_node)

    graph.add_conditional_edges(START, _route_start, {"niche_to_ideas": "niche_to_ideas", "idea_to_script": "idea_to_script"})
    graph.add_edge("niche_to_ideas", "idea_to_script")
    graph.add_conditional_edges(
        "idea_to_script",
        _route_after_script,
        {"script_approval_gate": "script_approval_gate", "youtube_metadata": "youtube_metadata"},
    )
    graph.add_edge("script_approval_gate", "youtube_metadata")
    graph.add_edge("youtube_metadata", "voice_production")
    graph.add_edge("voice_production", "storyboard_worker")
    graph.add_edge("storyboard_worker", "visual_director_worker")
    graph.add_edge("visual_director_worker", "acquisition_worker")
    graph.add_edge("acquisition_worker", "render_worker")
    graph.add_edge("render_worker", END)

    return graph.compile(checkpointer=checkpointer or MemorySaver())
