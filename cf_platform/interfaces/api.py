"""Platform-facing REST API routes for cf_platform, mounted under /platform in src/main.py."""

import logging
from datetime import datetime
from typing import Any, Literal, Optional

_logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from cf_platform.core.artifact_manager import (
    ArtifactRepository,
    ArtifactStorage,
    InMemoryArtifactRepository,
    R2ArtifactStorage,
    read_artifact,
)
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import check_db_health, get_checkpointer, get_pool
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
    PostgresTraceEventRepository,
)
from cf_platform.core.run_manager import (
    InMemoryRunRepository,
    RunNotFoundError,
    RunRepository,
    create_run,
    transition_run,
)
from cf_platform.blocks.idea_to_script import build_idea_to_script_graph, register_idea_to_script_workers
from cf_platform.blocks.niche_to_ideas import build_niche_to_ideas_graph, register_niche_to_ideas_workers
from cf_platform.core.schemas import IdeaToScriptState, NicheToIdeasState, SourceAdapter, StageState
from cf_platform.core.trace_repo import InMemoryTraceEventRepository, TraceEventRepository
from cf_platform.core.worker_registry import (
    ExecutionRepository,
    InMemoryExecutionRepository,
    WorkerRegistry,
    build_observed_node_graph,
)
from cf_platform.interfaces.telegram import (
    TelegramClient,
    format_ideas_running,
    format_ideas_usage,
    format_pick_running,
    format_pick_usage,
    format_produce_reply,
    format_produce_running,
    format_produce_usage,
    format_ranked_ideas,
    format_run_reply,
    format_run_running,
    format_run_usage,
    format_script_reply,
    format_script_running,
    format_script_usage,
    format_testvoice_reply,
    format_testvoice_running,
    format_unrecognized_command,
    is_chat_allowed,
    parse_ideas_command,
    parse_pick_command,
    parse_produce_args,
    parse_produce_command,
    parse_run_args,
    parse_run_command,
    parse_script_command,
    parse_script_duration_args,
    parse_testvoice_command,
)
from cf_platform.orchestrator.full_pipeline import build_full_pipeline_graph
from cf_platform.core.schemas import PipelineState
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.sources.google_trends import GoogleTrendsAdapter
from cf_platform.sources.reddit import RedditAdapter
from cf_platform.sources.youtube import YouTubeAdapter
from cf_platform.workers.echo import ECHO_REGISTRATION, echo_worker
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.voice_production import VOICE_PRODUCTION_REGISTRATION, build_voice_production_worker

router = APIRouter()

# Single-operator platform (multi-tenant isolation lands in S19) — fixed user_id for now.
_PLATFORM_USER_ID = "operator"

# In-memory fallback when DATABASE_URL is unset (D048) — process-local singletons.
_run_repository = InMemoryRunRepository()
_execution_repository = InMemoryExecutionRepository()
_artifact_repository = InMemoryArtifactRepository()
_trace_event_repository = InMemoryTraceEventRepository()
_worker_registry = WorkerRegistry()
_worker_registry.register("echo", ECHO_REGISTRATION)
register_niche_to_ideas_workers(_worker_registry)
register_idea_to_script_workers(_worker_registry)
_worker_registry.register("voice_production", VOICE_PRODUCTION_REGISTRATION)


@router.get("/health")
async def platform_health() -> dict:
    """Return the cf_platform subsystem health status, including a DB check (D048).

    The "status" field always reports "ok" for the platform subsystem itself —
    a database outage is reported via "database" but does not affect "status"
    (DB down != legacy down, P2-S1).
    """
    settings = get_platform_settings()
    database_status = await check_db_health(settings.DATABASE_URL)
    return {"status": "ok", "database": database_status}


def get_run_repository() -> RunRepository:
    """Return a Postgres-backed RunRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresRunRepository(pool)
    return _run_repository


def get_execution_repository() -> ExecutionRepository:
    """Return a Postgres-backed ExecutionRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresExecutionRepository(pool)
    return _execution_repository


def get_artifact_repository() -> ArtifactRepository:
    """Return a Postgres-backed ArtifactRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresArtifactRepository(pool)
    return _artifact_repository


def get_trace_event_repository() -> TraceEventRepository:
    """Return a Postgres-backed TraceEventRepository when DATABASE_URL is set, else the in-memory fallback (D048, D050)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresTraceEventRepository(pool)
    return _trace_event_repository


def get_worker_registry() -> WorkerRegistry:
    """Return the process-local WorkerRegistry, pre-populated with the echo and discovery workers."""
    return _worker_registry


def build_discovery_adapters(settings: PlatformSettings) -> list[tuple[str, SourceAdapter]]:
    """Return the (source_name, SourceAdapter) pairs for the discovery worker (D050).

    Adapters are constructed unconditionally even with empty credentials — a
    missing credential surfaces as an "error" trace event for that one source
    (partial-failure isolation, AC #3) rather than at construction time.
    """
    return [
        ("reddit", RedditAdapter(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET, settings.REDDIT_USER_AGENT)),
        ("google_trends", GoogleTrendsAdapter()),
        ("youtube", YouTubeAdapter(settings.YOUTUBE_API_KEY)),
    ]


def get_discovery_adapters(
    settings: PlatformSettings = Depends(get_platform_settings),
) -> list[tuple[str, SourceAdapter]]:
    """FastAPI dependency wrapping build_discovery_adapters — overridable with stub adapters in tests."""
    return build_discovery_adapters(settings)


async def get_graph_checkpointer() -> BaseCheckpointSaver:
    """Return a Postgres-backed checkpointer when DATABASE_URL is set, else MemorySaver (D048, P2-S4).

    Async because AsyncPostgresSaver's constructor requires a running event loop
    (asyncio.get_running_loop()) — FastAPI runs async dependencies on the loop
    directly, whereas sync dependencies run in a worker thread without one.
    """
    return get_checkpointer(get_platform_settings().DATABASE_URL)


def get_artifact_storage() -> ArtifactStorage:
    """Return an R2ArtifactStorage built from cf_platform's own settings (D047)."""
    settings = get_platform_settings()
    return R2ArtifactStorage(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )


class EchoRequest(BaseModel):
    """Request body for POST /platform/echo."""

    text: str


class EchoResponse(BaseModel):
    """Response body for POST /platform/echo."""

    run_id: str
    artifact_key: str


@router.post("/echo", response_model=EchoResponse)
async def echo(
    body: EchoRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
) -> EchoResponse:
    """Mint a run, execute the echo graph, and return the run_id + resulting artifact key.

    Proves the full P1 spine: Run Manager -> LangGraph execution engine (Layer A) ->
    observability wrapper (Layer B) -> real, versioned R2 artifact + WorkerExecution.
    When DATABASE_URL is set (P2-S3), the run, artifact, and execution rows are
    persisted to Postgres as the lineage index; R2 stays the artifact body truth.
    The graph is checkpointed via Postgres when DATABASE_URL is set (P2-S4), so a
    run resumes from its last checkpoint after a process restart.
    """
    run = await create_run(_PLATFORM_USER_ID, "echo", {"text": body.text}, runs)
    run = await transition_run(run.run_id, "running", runs)

    graph = build_observed_node_graph(
        "echo",
        "echo",
        echo_worker,
        registry=registry,
        storage=storage,
        executions=executions,
        artifact_repo=artifacts,
        checkpointer=checkpointer,
    )
    state = StageState(run_id=run.run_id, user_id=_PLATFORM_USER_ID, inputs={"message": body.text})
    result = await run_graph(graph, state, thread_id=run.run_id)

    await transition_run(run.run_id, "complete", runs)

    return EchoResponse(run_id=run.run_id, artifact_key=result.artifacts["echo"])


class NicheToIdeasRequest(BaseModel):
    """Request body for POST /platform/blocks/niche-to-ideas."""

    niche: str
    audience: Optional[str] = None
    mode: Optional[str] = "single"


class NicheToIdeasResponse(BaseModel):
    """Response body for POST /platform/blocks/niche-to-ideas."""

    run_id: str
    ranked_ideas_artifact_key: str
    selected: TopicScore
    alternatives: list[TopicScore]


@router.post("/blocks/niche-to-ideas", response_model=NicheToIdeasResponse)
async def niche_to_ideas(
    body: NicheToIdeasRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
    settings: PlatformSettings = Depends(get_platform_settings),
    adapters: list[tuple[str, SourceAdapter]] = Depends(get_discovery_adapters),
) -> NicheToIdeasResponse:
    """Run the full niche→ideas block and return the ranked ideas.

    Executes all four workers (discovery → topic_generator → opportunity_scorer →
    topic_selector) as a single LangGraph run, producing 4 artifacts and 4
    WorkerExecution rows. Returns the selected idea and alternatives from the terminal
    `ranked_ideas` artifact so callers get structured data without a second request.

    `audience` is stored in run inputs for future use; `mode` is passed into
    NicheToIdeasState to control single-vs-top_n selection routing (P4-S4).
    """
    run_inputs: dict[str, Any] = {"niche": body.niche}
    if body.audience:
        run_inputs["audience"] = body.audience

    run = await create_run(_PLATFORM_USER_ID, "niche_to_ideas", run_inputs, runs)
    run = await transition_run(run.run_id, "running", runs)

    graph = build_niche_to_ideas_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifacts,
        adapters=adapters,
        trace_repo=trace_events,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        checkpointer=checkpointer,
    )
    mode = body.mode if body.mode in ("single", "top_n") else "single"
    state = NicheToIdeasState(
        run_id=run.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs=run_inputs,
        mode=mode,  # type: ignore[arg-type]
    )
    result = await run_graph(graph, state, thread_id=run.run_id)

    await transition_run(run.run_id, "complete", runs)

    ranked_key = result.artifacts["ranked_ideas"]
    _, body_dict = await read_artifact(storage, ranked_key)
    ranked_artifact = RankedIdeasArtifact.model_validate(body_dict)

    return NicheToIdeasResponse(
        run_id=run.run_id,
        ranked_ideas_artifact_key=ranked_key,
        selected=ranked_artifact.selected,
        alternatives=ranked_artifact.alternatives,
    )


class IdeaToScriptRequest(BaseModel):
    """Request body for POST /platform/blocks/idea-to-script."""

    idea_title: str
    niche: Optional[str] = None
    angle: Optional[str] = None
    supporting_points: Optional[list[str]] = None
    max_iterations: Optional[int] = None
    target_duration_seconds: int = 60


class IdeaToScriptResponse(BaseModel):
    """Response body for POST /platform/blocks/idea-to-script."""

    run_id: str
    script_artifact_key: str
    script: str
    iterations: int


@router.post("/blocks/idea-to-script", response_model=IdeaToScriptResponse)
async def idea_to_script(
    body: IdeaToScriptRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> IdeaToScriptResponse:
    """Run the full idea→script block and return the terminal script artifact.

    Executes the cyclic write→score→fact-check→refine loop (bounded by
    `max_iterations`, default 3) followed by the terminal `script_packager` node
    that selects the best draft and writes the `ScriptArtifact` to R2.

    Returns the selected script text, the R2 artifact key, and the number of
    refine iterations performed. The REST caller gets the full script body inline
    so a second request is not needed.

    `max_iterations` overrides the default of 3 when provided.
    """
    run_inputs: dict[str, Any] = {"idea_title": body.idea_title}
    if body.niche:
        run_inputs["niche"] = body.niche
    if body.angle:
        run_inputs["angle"] = body.angle
    if body.supporting_points:
        run_inputs["supporting_points"] = body.supporting_points

    run = await create_run(_PLATFORM_USER_ID, "idea_to_script", run_inputs, runs)
    run = await transition_run(run.run_id, "running", runs)

    state_kwargs: dict[str, Any] = {"target_duration_seconds": body.target_duration_seconds}
    if body.max_iterations is not None:
        state_kwargs["max_iterations"] = body.max_iterations

    graph = build_idea_to_script_graph(
        storage=storage,
        registry=registry,
        executions=executions,
        artifact_repo=artifacts,
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
        checkpointer=checkpointer,
    )
    state = IdeaToScriptState(
        run_id=run.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs=run_inputs,
        **state_kwargs,
    )
    result = await run_graph(graph, state, thread_id=run.run_id)
    await transition_run(run.run_id, "complete", runs)

    script_key = result.artifacts["script"]
    _, body_dict = await read_artifact(storage, script_key)
    script_artifact = ScriptArtifact.model_validate(body_dict)

    return IdeaToScriptResponse(
        run_id=run.run_id,
        script_artifact_key=script_key,
        script=script_artifact.script,
        iterations=result.iteration,
    )


class RunSummary(BaseModel):
    """Lineage summary for one run, as returned by GET /platform/runs."""

    run_id: str
    user_id: str
    block: str
    status: str
    inputs: dict[str, Any]
    error: Optional[str] = None
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


class TelegramChat(BaseModel):
    """Minimal Telegram `chat` object — only the `id` is needed to reply (D049)."""

    id: int


class TelegramMessage(BaseModel):
    """Minimal Telegram `message` object — chat + optional text (D049)."""

    chat: TelegramChat
    text: Optional[str] = None


class TelegramUpdate(BaseModel):
    """Minimal Telegram `Update` object — only the `message` field is consumed (D049)."""

    message: Optional[TelegramMessage] = None


async def _run_ideas_and_reply(
    chat_id: int,
    niche: str,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Run the full niche→ideas block in the background and push the reply to Telegram.

    Separated from the webhook handler so the handler can return {"ok": True} immediately —
    Telegram's webhook has a 60-second response timeout; LLM graph runs take 25–55 s and
    would trigger retries and duplicate runs if awaited inline.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run = await create_run(_PLATFORM_USER_ID, "niche_to_ideas", {"niche": niche}, runs)
        run = await transition_run(run.run_id, "running", runs)

        graph = build_niche_to_ideas_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifacts,
            adapters=adapters,
            trace_repo=trace_events,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            checkpointer=checkpointer,
        )
        state = NicheToIdeasState(
            run_id=run.run_id, user_id=_PLATFORM_USER_ID, inputs={"niche": niche}
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        ranked_key = result.artifacts["ranked_ideas"]
        _, body_dict = await read_artifact(storage, ranked_key)
        ranked_artifact = RankedIdeasArtifact.model_validate(body_dict)
        reply = format_ranked_ideas(niche, run.run_id, ranked_key, ranked_artifact)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_ideas_and_reply failed for niche=%r chat_id=%s: %s", niche, chat_id, exc)
        short = str(exc)[:200]
        reply = f"Error running /ideas: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


async def _run_script_and_reply(
    chat_id: int,
    idea_title: str,
    settings: PlatformSettings,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    checkpointer: BaseCheckpointSaver,
    target_duration_seconds: int = 60,
) -> None:
    """Run the full idea→script block in the background and push the script to Telegram.

    Separated from the webhook handler so the handler can return {"ok": True} immediately —
    Telegram's 60-second response timeout is too short for a multi-iteration LLM graph.
    `target_duration_seconds` is parsed from the `/script ... --duration <n>` flag (P6-S5).
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run_inputs: dict[str, Any] = {"idea_title": idea_title}
        run = await create_run(_PLATFORM_USER_ID, "idea_to_script", run_inputs, runs)
        run = await transition_run(run.run_id, "running", runs)

        graph = build_idea_to_script_graph(
            storage=storage,
            registry=registry,
            executions=executions,
            artifact_repo=artifacts,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
            checkpointer=checkpointer,
        )
        state = IdeaToScriptState(
            run_id=run.run_id,
            user_id=_PLATFORM_USER_ID,
            inputs=run_inputs,
            target_duration_seconds=target_duration_seconds,
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        script_key = result.artifacts["script"]
        _, body_dict = await read_artifact(storage, script_key)
        script_artifact = ScriptArtifact.model_validate(body_dict)
        reply = format_script_reply(script_artifact)
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "_run_script_and_reply failed for idea_title=%r chat_id=%s: %s",
            idea_title,
            chat_id,
            exc,
        )
        short = str(exc)[:200]
        reply = f"Error running /script: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


_VIDEO_URL_EXPIRY = 86400  # 24 hours


async def _run_pipeline_and_reply(
    chat_id: int,
    display_label: str,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
    niche: str = "",
    idea_title: Optional[str] = None,
    target_duration_seconds: int = 60,
    command_name: str = "pipeline",
) -> None:
    """Run the full pipeline in the background and push a video URL reply to Telegram.

    Separated from webhook handlers so they can return {"ok": True} immediately —
    full pipeline runs take 5–10 minutes (LLM calls + ffmpeg render).

    `display_label` is shown in the Telegram reply (niche for /run, idea title for /produce
    and /pick). `niche` and `idea_title` are passed to PipelineState; when `idea_title` is
    set the orchestrator skips niche_to_ideas (P7-S1). `command_name` is used only in error
    messages for operator clarity.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        run_inputs: dict[str, Any] = {}
        if niche:
            run_inputs["niche"] = niche
        if idea_title:
            run_inputs["idea_title"] = idea_title

        run = await create_run(_PLATFORM_USER_ID, "full_pipeline", run_inputs, runs)
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
            user_id=_PLATFORM_USER_ID,
            inputs=run_inputs,
            target_duration_seconds=target_duration_seconds,
            idea_title=idea_title,
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        video_r2_key: str = result.artifacts["video"]
        video_url = await storage.generate_presigned_url(video_r2_key, expires_in=_VIDEO_URL_EXPIRY)
        reply = (
            f'Video ready — "{display_label}"\n'
            f"Run: {run.run_id}\n\n"
            f"Download (expires 24 h):\n{video_url}"
        )
    except Exception as exc:  # noqa: BLE001
        _logger.exception(
            "_run_pipeline_and_reply failed for label=%r chat_id=%s: %s", display_label, chat_id, exc
        )
        short = str(exc)[:200]
        reply = f"Error running /{command_name}: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


async def _run_pick_and_reply(
    chat_id: int,
    original_run_id: str,
    idea_number: int,
    settings: PlatformSettings,
    adapters: list,
    storage: ArtifactStorage,
    registry: WorkerRegistry,
    runs: RunRepository,
    executions: ExecutionRepository,
    artifacts: ArtifactRepository,
    trace_events: TraceEventRepository,
    checkpointer: BaseCheckpointSaver,
    target_duration_seconds: int = 60,
) -> None:
    """Read the ranked_ideas artifact from original_run_id, extract idea N, and produce a video.

    Validates that idea_number is in range for the artifact, sends an ack, then calls
    _run_pipeline_and_reply with idea_title set so niche_to_ideas is skipped (P7-S1).
    Niche is read from the ranked_ideas artifact for prompt context downstream.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        artifact_records = await artifacts.list_for_run(original_run_id)
        ranked_records = [a for a in artifact_records if a.name == "ranked_ideas"]
        if not ranked_records:
            await client.send_message(chat_id, f"No ideas found for run {original_run_id}. Run /ideas first.")
            return
        ranked_r2_key = max(ranked_records, key=lambda a: a.version).r2_key
        _, ranked_body = await read_artifact(storage, ranked_r2_key)
        ranked_artifact = RankedIdeasArtifact.model_validate(ranked_body)

        all_ideas = [ranked_artifact.selected] + list(ranked_artifact.alternatives)
        if idea_number > len(all_ideas):
            await client.send_message(chat_id, f"Idea {idea_number} not found — run {original_run_id} only has {len(all_ideas)} ideas.")
            return

        chosen = all_ideas[idea_number - 1]
        niche: str = ranked_artifact.niche

        await client.send_message(chat_id, format_pick_running(original_run_id, chosen.title))
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_pick_and_reply failed for run_id=%r idea_number=%s chat_id=%s: %s", original_run_id, idea_number, chat_id, exc)
        short = str(exc)[:200]
        try:
            await client.send_message(chat_id, f"Error running /pick: {type(exc).__name__}: {short}")
        except Exception:  # noqa: BLE001
            pass
        return

    await _run_pipeline_and_reply(
        chat_id=chat_id,
        display_label=chosen.title,
        settings=settings,
        adapters=adapters,
        storage=storage,
        registry=registry,
        runs=runs,
        executions=executions,
        artifacts=artifacts,
        trace_events=trace_events,
        checkpointer=checkpointer,
        niche=niche,
        idea_title=chosen.title,
        target_duration_seconds=target_duration_seconds,
        command_name="pick",
    )


_TESTVOICE_MP3_URL_EXPIRY = 3600  # 1 hour


async def _run_testvoice_and_reply(
    chat_id: int,
    run_id: str,
    settings: PlatformSettings,
    storage: ArtifactStorage,
    artifacts: ArtifactRepository,
) -> None:
    """Read the script artifact for run_id, generate voice, and reply with a presigned MP3 URL.

    Calls voice_production_worker directly (not through the full graph) so the
    operator can test voice in isolation without re-running the whole pipeline.
    Reads the latest 'script' artifact for the run from the artifact repository,
    then invokes build_voice_production_worker with GEMINI_API_KEY + GEMINI_TTS_VOICE
    from settings.  Returns a presigned URL with a 1-hour expiry.

    Fault isolation: if no script artifact is found, or TTS fails, sends an error
    reply rather than crashing silently.
    """
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)
    try:
        # Look up the latest 'script' artifact for this run.
        artifact_records = await artifacts.list_for_run(run_id)
        script_records = [a for a in artifact_records if a.name == "script"]
        if not script_records:
            await client.send_message(chat_id, f"No script artifact found for run {run_id}. Run /produce first.")
            return
        # Take the highest version.
        script_r2_key = max(script_records, key=lambda a: a.version).r2_key

        voice_worker = build_voice_production_worker(
            storage,
            gemini_api_key=settings.GEMINI_API_KEY,
            gemini_tts_voice=settings.GEMINI_TTS_VOICE,
            deepgram_api_key=settings.DEEPGRAM_API_KEY,
        )
        state = StageState(
            run_id=run_id,
            user_id=_PLATFORM_USER_ID,
            inputs={},
            artifacts={"script": script_r2_key},
        )
        result = await voice_worker(state)
        mp3_r2_key: str = result.artifact.mp3_r2_key  # type: ignore[union-attr]
        if not mp3_r2_key:
            await client.send_message(chat_id, f"Voice generated with proportional fallback (no TTS key). No MP3 to download for run {run_id}.")
            return
        mp3_url = await storage.generate_presigned_url(mp3_r2_key, expires_in=_TESTVOICE_MP3_URL_EXPIRY)
        reply = format_testvoice_reply(run_id, mp3_url)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("_run_testvoice_and_reply failed for run_id=%r chat_id=%s: %s", run_id, chat_id, exc)
        short = str(exc)[:200]
        reply = f"Error running /testvoice: {type(exc).__name__}: {short}"

    try:
        await client.send_message(chat_id, reply)
    except Exception as exc:  # noqa: BLE001
        _logger.exception("TelegramClient.send_message failed for chat_id=%s: %s", chat_id, exc)


class ProduceRequest(BaseModel):
    """Request body for POST /platform/pipeline/produce."""

    niche: str
    target_duration_seconds: int = 60
    idea_title: Optional[str] = None


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
    run = await create_run(_PLATFORM_USER_ID, "full_pipeline", run_inputs, runs)
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
        user_id=_PLATFORM_USER_ID,
        inputs=run_inputs,
        target_duration_seconds=body.target_duration_seconds,
        idea_title=body.idea_title,
    )
    result = await run_graph(graph, state, thread_id=run.run_id)
    await transition_run(run.run_id, "complete", runs)

    video_r2_key: str = result.artifacts["video"]
    video_url = await storage.generate_presigned_url(video_r2_key, expires_in=_VIDEO_URL_EXPIRY)

    return ProduceResponse(run_id=run.run_id, video_r2_key=video_r2_key, video_url=video_url)


@router.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(
    update: TelegramUpdate,
    request: Request,
    background_tasks: BackgroundTasks,
    settings: PlatformSettings = Depends(get_platform_settings),
    adapters: list[tuple[str, SourceAdapter]] = Depends(get_discovery_adapters),
    storage: ArtifactStorage = Depends(get_artifact_storage),
    registry: WorkerRegistry = Depends(get_worker_registry),
    runs: RunRepository = Depends(get_run_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    artifacts: ArtifactRepository = Depends(get_artifact_repository),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
    checkpointer: BaseCheckpointSaver = Depends(get_graph_checkpointer),
) -> dict:
    """Validate Telegram's secret token, parse trigger commands, and reply via a formatter (D049).

    `/ideas <niche>` schedules the full niche→ideas block as a FastAPI BackgroundTask so
    the webhook returns {"ok": True} immediately — well within Telegram's 60 s timeout.
    The graph result is pushed to chat via `TelegramClient.send_message` when done.

    TELEGRAM_ALLOWED_CHAT_IDS (temporary single-operator allowlist ahead of S19):
    updates from chats not on the list are acked with no reply sent.
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret token")

    if update.message is None or update.message.text is None:
        return {"ok": True}

    if not is_chat_allowed(update.message.chat.id, settings.TELEGRAM_ALLOWED_CHAT_IDS):
        return {"ok": True}

    chat_id = update.message.chat.id
    client = TelegramClient(settings.TELEGRAM_BOT_TOKEN)

    run_args = parse_run_command(update.message.text)
    produce_args = parse_produce_command(update.message.text)
    pick_result = parse_pick_command(update.message.text)
    niche = parse_ideas_command(update.message.text)
    idea_title = parse_script_command(update.message.text)
    testvoice_run_id = parse_testvoice_command(update.message.text)

    if run_args is not None:
        if not run_args:
            await client.send_message(chat_id, format_run_usage())
        else:
            parsed_niche, duration = parse_run_args(run_args)
            if not parsed_niche:
                await client.send_message(chat_id, format_run_usage())
            else:
                await client.send_message(chat_id, format_run_running(parsed_niche))
                background_tasks.add_task(
                    _run_pipeline_and_reply,
                    chat_id=chat_id,
                    display_label=parsed_niche,
                    settings=settings,
                    adapters=adapters,
                    storage=storage,
                    registry=registry,
                    runs=runs,
                    executions=executions,
                    artifacts=artifacts,
                    trace_events=trace_events,
                    checkpointer=checkpointer,
                    niche=parsed_niche,
                    target_duration_seconds=duration,
                    command_name="run",
                )
    elif produce_args is not None:
        if not produce_args:
            await client.send_message(chat_id, format_produce_usage())
        else:
            parsed_title, duration = parse_produce_args(produce_args)
            if not parsed_title:
                await client.send_message(chat_id, format_produce_usage())
            else:
                await client.send_message(chat_id, format_produce_running(parsed_title))
                background_tasks.add_task(
                    _run_pipeline_and_reply,
                    chat_id=chat_id,
                    display_label=parsed_title,
                    settings=settings,
                    adapters=adapters,
                    storage=storage,
                    registry=registry,
                    runs=runs,
                    executions=executions,
                    artifacts=artifacts,
                    trace_events=trace_events,
                    checkpointer=checkpointer,
                    idea_title=parsed_title,
                    target_duration_seconds=duration,
                    command_name="produce",
                )
    elif pick_result is not None:
        original_run_id, idea_number, pick_duration = pick_result
        background_tasks.add_task(
            _run_pick_and_reply,
            chat_id=chat_id,
            original_run_id=original_run_id,
            idea_number=idea_number,
            settings=settings,
            adapters=adapters,
            storage=storage,
            registry=registry,
            runs=runs,
            executions=executions,
            artifacts=artifacts,
            trace_events=trace_events,
            checkpointer=checkpointer,
            target_duration_seconds=pick_duration,
        )
    elif niche is not None:
        if not niche:
            await client.send_message(chat_id, format_ideas_usage())
        else:
            await client.send_message(chat_id, format_ideas_running(niche))
            background_tasks.add_task(
                _run_ideas_and_reply,
                chat_id=chat_id,
                niche=niche,
                settings=settings,
                adapters=adapters,
                storage=storage,
                registry=registry,
                runs=runs,
                executions=executions,
                artifacts=artifacts,
                trace_events=trace_events,
                checkpointer=checkpointer,
            )
    elif idea_title is not None:
        if not idea_title:
            await client.send_message(chat_id, format_script_usage())
        else:
            parsed_title, duration = parse_script_duration_args(idea_title)
            await client.send_message(chat_id, format_script_running(parsed_title))
            background_tasks.add_task(
                _run_script_and_reply,
                chat_id=chat_id,
                idea_title=parsed_title,
                settings=settings,
                storage=storage,
                registry=registry,
                runs=runs,
                executions=executions,
                artifacts=artifacts,
                checkpointer=checkpointer,
                target_duration_seconds=duration,
            )
    elif testvoice_run_id is not None:
        if not testvoice_run_id:
            await client.send_message(chat_id, "Usage: /testvoice <run_id> — e.g. /testvoice abc-123")
        else:
            await client.send_message(chat_id, format_testvoice_running(testvoice_run_id))
            background_tasks.add_task(
                _run_testvoice_and_reply,
                chat_id=chat_id,
                run_id=testvoice_run_id,
                settings=settings,
                storage=storage,
                artifacts=artifacts,
            )
    else:
        await client.send_message(chat_id, format_unrecognized_command(update.message.text))

    return {"ok": True}
