"""Synchronous full-pipeline route — POST /pipeline/produce."""

from typing import Any

from fastapi import APIRouter, Depends
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.run_manager import RunRepository, create_run, transition_run
from cf_platform.core.schemas import PipelineState, SourceAdapter
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
    get_trace_event_repository,
    get_worker_registry,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph

_VIDEO_URL_EXPIRY = 86400  # 24 hours

router = APIRouter()


class ProduceRequest(BaseModel):
    """Request body for POST /platform/pipeline/produce."""

    niche: str
    target_duration_seconds: int = 60
    idea_title: str | None = None


class ProduceResponse(BaseModel):
    """Response body for POST /platform/pipeline/produce."""

    run_id: str
    video_r2_key: str
    video_url: str


@router.post("/pipeline/produce", response_model=ProduceResponse)
async def produce(
    body: ProduceRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
    settings: PlatformSettings = Depends(get_platform_settings),
    adapters: list[tuple[str, SourceAdapter]] = Depends(get_discovery_adapters),
) -> ProduceResponse:
    """Run the full niche→ideas→script→render pipeline and return a presigned video URL.

    Chains all three blocks (niche_to_ideas, idea_to_script, legacy_render) as a single
    PipelineState run.  Returns the R2 key and a presigned download URL (24-hour expiry)
    for the finished video file.  The caller is responsible for waiting — this endpoint
    is synchronous and will hold the connection for the duration of the pipeline run
    (~5–10 minutes).  For fire-and-forget use, prefer the Telegram `/produce` command.
    """
    run_inputs: dict[str, Any] = {"niche": body.niche}
    run = await create_run(PLATFORM_USER_ID, "full_pipeline", run_inputs, runs)
    run = await transition_run(run.run_id, "running", runs)

    graph = build_full_pipeline_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifacts,
        adapters=adapters,
        trace_repo=trace_events,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        checkpointer=checkpointer,
        gemini_api_key=settings.GEMINI_API_KEY,
        gemini_tts_voice=settings.GEMINI_TTS_VOICE,
        deepgram_api_key=settings.DEEPGRAM_API_KEY,
    )
    state = PipelineState(
        run_id=run.run_id,
        user_id=PLATFORM_USER_ID,
        inputs=run_inputs,
        target_duration_seconds=body.target_duration_seconds,
        idea_title=body.idea_title,
    )
    result = await run_graph(graph, state, thread_id=run.run_id)
    await transition_run(run.run_id, "complete", runs)

    video_r2_key: str = result.artifacts["video"]
    video_url = await storage.generate_presigned_url(video_r2_key, expires_in=_VIDEO_URL_EXPIRY)

    return ProduceResponse(run_id=run.run_id, video_r2_key=video_r2_key, video_url=video_url)
