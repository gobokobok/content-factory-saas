"""Run lineage routes — GET /runs, GET /runs/{run_id}, POST /runs/{run_id}/resume."""

import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.run_manager import RunNotFoundError, RunRepository
from cf_platform.core.schemas import SourceAdapter
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import ExecutionRepository, WorkerRegistry
from cf_platform.interfaces.dependencies import (
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

_logger = logging.getLogger(__name__)

router = APIRouter()


class RunSummary(BaseModel):
    """Lineage summary for one run, as returned by GET /platform/runs."""

    run_id: str
    user_id: str
    block: str
    status: str
    inputs: dict[str, Any]
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ArtifactSummary(BaseModel):
    """One artifact's lineage index row, as returned by GET /platform/runs/{run_id}."""

    name: str
    stage: str
    version: int
    r2_key: str
    worker: str
    worker_version: str
    prompt_version: str
    model: str


class WorkerExecutionSummary(BaseModel):
    """One worker execution's cost/latency/version row, as returned by GET /platform/runs/{run_id}."""

    worker: str
    worker_version: str
    prompt_version: str
    model: str
    status: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    started_at: datetime
    finished_at: datetime


class RunDetailResponse(BaseModel):
    """Full lineage detail for one run, as returned by GET /platform/runs/{run_id}."""

    run: RunSummary
    artifacts: list[ArtifactSummary]
    executions: list[WorkerExecutionSummary]


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(runs: RunRepository = Depends(get_run_repository)) -> list[RunSummary]:
    """Return all platform runs, most recently created first."""
    records = await runs.list_runs()
    return [RunSummary.model_validate(record.model_dump()) for record in records]


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
async def get_run(
    run_id: str,
    runs: RunRepository = Depends(get_run_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
) -> RunDetailResponse:
    """Return a run's status, artifact list (R2 keys), and per-worker cost/latency/version.

    Raises 404 if run_id is unknown.
    """
    try:
        run = await runs.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    artifact_records = await artifacts.list_for_run(run_id)
    execution_records = await executions.list_for_run(run_id)

    return RunDetailResponse(
        run=RunSummary.model_validate(run.model_dump()),
        artifacts=[
            ArtifactSummary(
                name=artifact.name,
                stage=artifact.stage,
                version=artifact.version,
                r2_key=artifact.r2_key,
                worker=artifact.lineage.worker,
                worker_version=artifact.lineage.worker_version,
                prompt_version=artifact.lineage.prompt_version,
                model=artifact.lineage.model,
            )
            for artifact in artifact_records
        ],
        executions=[
            WorkerExecutionSummary.model_validate(execution.model_dump())
            for execution in execution_records
        ],
    )


class ResumeRequest(BaseModel):
    """Request body for POST /platform/runs/{run_id}/resume (P6-S3)."""

    decision: Literal["approve", "reject"]


class ResumeResponse(BaseModel):
    """Response body for POST /platform/runs/{run_id}/resume (P6-S3)."""

    run_id: str
    decision: str
    status: str


@router.post("/runs/{run_id}/resume", status_code=202, response_model=ResumeResponse)
async def resume_run(
    run_id: str,
    body: ResumeRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
    settings: PlatformSettings = Depends(get_platform_settings),
    adapters: list[tuple[str, SourceAdapter]] = Depends(get_discovery_adapters),
) -> ResumeResponse:
    """Resume an interrupted pipeline run with the given decision (P6-S3).

    Rebuilds the full pipeline graph with the Postgres checkpointer and resumes
    from the saved checkpoint under thread_id=run_id. Accepted decisions:
      "approve" — continue to legacy_render.
      "reject"  — cancel the run (raises RuntimeError inside the gate node).

    Returns 202 immediately; the resumed pipeline continues as a BackgroundTask.
    """

    async def _resume() -> None:
        config = {"configurable": {"thread_id": run_id}}
        try:
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
            await graph.ainvoke(Command(resume=body.decision), config=config)
        except Exception as exc:
            _logger.error("resume_run failed for run_id=%s decision=%s: %s", run_id, body.decision, exc)

    background_tasks.add_task(_resume)
    return ResumeResponse(run_id=run_id, decision=body.decision, status="resuming")
