"""Platform-facing REST API routes for cf_platform, mounted under /platform in src/main.py."""

import logging
from datetime import datetime
from typing import Any, Literal, Optional

_logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, UploadFile
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
    format_footage_summary,
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
    format_youtube_metadata_block,
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
from cf_platform.workers.acquisition_worker import (
    ACQUISITION_WORKER_REGISTRATION,
    AssetManifestArtifact,
    build_acquisition_worker,
)
from cf_platform.workers.render_worker import (
    RENDER_WORKER_REGISTRATION,
    RenderArtifact,
    build_render_worker,
)
from cf_platform.workers.storyboard_worker import (
    STORYBOARD_WORKER_REGISTRATION,
    VerifiedStoryboardArtifact,
    build_storyboard_worker,
)
from cf_platform.workers.topic_selector import RankedIdeasArtifact
from cf_platform.workers.voice_production import VOICE_PRODUCTION_REGISTRATION, VoiceAlignmentArtifact, build_voice_production_worker
from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

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
_worker_registry.register("storyboard_worker", STORYBOARD_WORKER_REGISTRATION)
_worker_registry.register("acquisition_worker", ACQUISITION_WORKER_REGISTRATION)


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


class StoryboardWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/storyboard."""

    run_id: str
    script: str


class StoryboardWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/storyboard."""

    artifact_key: str
    scene_count: int
    prompt_version: str


@router.post("/workers/storyboard", response_model=StoryboardWorkerResponse)
async def storyboard_worker_endpoint(
    body: StoryboardWorkerRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> StoryboardWorkerResponse:
    """Generate a verified storyboard from a script text.

    Runs the full generate→review→patch internal cycle (prompt v0.12).
    Designed for future step-by-step manual UI and standalone testing.

    The script body is written as a temporary artifact at a known key so the
    worker can read it via the standard ArtifactStorage interface. The resulting
    VerifiedStoryboardArtifact is persisted to R2 and its key returned.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    script_artifact = ScriptArtifact(
        idea_title="",
        niche=None,
        script=body.script,
        word_count=len(body.script.split()),
        status="ok",
        generated_at=datetime.now(),
    )
    script_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="storyboard_request",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(),
    )
    script_record = await write_artifact(
        storage,
        script_artifact,
        name="script",
        stage="script",
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        lineage=script_lineage,
    )

    # Pick up voice alignment if the Voice stage has already run — gives accurate per-scene timing
    state_artifacts: dict[str, str] = {"script": script_record.r2_key}
    va_key = await _latest_artifact_key(storage, body.run_id, "voice", "voice_alignment")
    if va_key:
        state_artifacts["voice_alignment"] = va_key
        _logger.info("Voice alignment found for run %s — using Deepgram timestamps", body.run_id)

    worker = build_storyboard_worker(storage, settings.ANTHROPIC_API_KEY)
    state = StageState(
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs={},
        artifacts=state_artifacts,
    )
    output = await worker(state)
    result_artifact = output.artifact
    if not isinstance(result_artifact, VerifiedStoryboardArtifact):
        raise HTTPException(status_code=500, detail="StoryboardWorker returned unexpected artifact type")

    storyboard_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="storyboard_worker",
        worker_version=STORYBOARD_WORKER_REGISTRATION.worker_version,
        prompt_version=STORYBOARD_WORKER_REGISTRATION.prompt_version,
        model=STORYBOARD_WORKER_REGISTRATION.model,
        created_at=datetime.now(),
    )
    storyboard_record = await write_artifact(
        storage,
        result_artifact,
        name="verified_storyboard",
        stage="storyboard",
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        lineage=storyboard_lineage,
    )

    return StoryboardWorkerResponse(
        artifact_key=storyboard_record.r2_key,
        scene_count=result_artifact.scene_count,
        prompt_version=result_artifact.prompt_version,
    )


class VoiceWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/voice."""

    run_id: str
    script: str


class VoiceWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/voice."""

    artifact_key: str
    mp3_r2_key: str
    mp3_url: Optional[str]
    alignment_method: str
    total_duration_s: float
    word_count: int


@router.post("/workers/voice", response_model=VoiceWorkerResponse)
async def voice_worker_endpoint(
    body: VoiceWorkerRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> VoiceWorkerResponse:
    """Generate TTS voiceover and Deepgram word-level timestamps for a script.

    Writes both a script artifact (so the subsequent storyboard step can read it)
    and a voice_alignment artifact.  The storyboard worker will auto-detect the
    voice_alignment and use Deepgram timestamps for accurate per-scene durations.
    Falls back to proportional estimation if Gemini/Deepgram keys are absent.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    script_artifact = ScriptArtifact(
        idea_title="",
        niche=None,
        script=body.script,
        word_count=len(body.script.split()),
        status="ok",
        generated_at=datetime.now(),
    )
    script_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="voice_request",
        worker_version="1.0.0",
        prompt_version="v1",
        model="none",
        created_at=datetime.now(),
    )
    script_record = await write_artifact(
        storage,
        script_artifact,
        name="script",
        stage="script",
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        lineage=script_lineage,
    )

    worker = build_voice_production_worker(
        storage,
        gemini_api_key=settings.GEMINI_API_KEY,
        gemini_tts_voice=settings.GEMINI_TTS_VOICE,
        deepgram_api_key=settings.DEEPGRAM_API_KEY,
    )
    worker_state = StageState(
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs={},
        artifacts={"script": script_record.r2_key},
    )
    output = await worker(worker_state)
    result = output.artifact
    if not isinstance(result, VoiceAlignmentArtifact):
        raise HTTPException(status_code=500, detail="VoiceProductionWorker returned unexpected artifact type")

    voice_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="voice_production",
        worker_version=VOICE_PRODUCTION_REGISTRATION.worker_version,
        prompt_version=VOICE_PRODUCTION_REGISTRATION.prompt_version,
        model=VOICE_PRODUCTION_REGISTRATION.model,
        created_at=datetime.now(),
    )
    voice_record = await write_artifact(
        storage,
        result,
        name="voice_alignment",
        stage="voice",
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        lineage=voice_lineage,
    )

    mp3_url: Optional[str] = None
    if result.mp3_r2_key:
        try:
            mp3_url = await storage.generate_presigned_url(result.mp3_r2_key, expires_in=3600)
        except Exception:
            pass

    return VoiceWorkerResponse(
        artifact_key=voice_record.r2_key,
        mp3_r2_key=result.mp3_r2_key,
        mp3_url=mp3_url,
        alignment_method=result.alignment_method,
        total_duration_s=result.total_duration_s,
        word_count=len(result.word_timestamps),
    )


class AcquisitionWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/acquisition."""

    run_id: str


class AcquisitionWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/acquisition."""

    manifest_key: str
    footage_summary: dict
    acquired: int
    failed: int


@router.post("/workers/acquisition", response_model=AcquisitionWorkerResponse)
async def acquisition_worker_endpoint(
    body: AcquisitionWorkerRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> AcquisitionWorkerResponse:
    """Acquire assets for all scenes in an existing verified storyboard.

    Reads the latest verified_storyboard artifact for run_id, routes each scene
    by segment_type (Character/Event/B-roll), runs the three-tier STK cascade with
    a QA gate, and persists the asset_manifest artifact to R2. The run must have a
    verified_storyboard artifact written by a prior /platform/workers/storyboard call.

    Designed for future step-by-step manual UI and standalone testing; not wired into
    Telegram in this story.
    """
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    # Locate the latest verified_storyboard artifact for this run
    prefix = f"users/{_PLATFORM_USER_ID}/runs/{body.run_id}/storyboard/verified_storyboard@v"
    storyboard_keys = await storage.list_keys(prefix)
    if not storyboard_keys:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"No verified_storyboard artifact found for run_id={body.run_id!r}. "
                   "Run /platform/workers/storyboard first.",
        )
    storyboard_key = sorted(storyboard_keys)[-1]  # latest version

    worker = build_acquisition_worker(
        storage,
        pexels_api_key=settings.PEXELS_API_KEY,
        pixabay_api_key=settings.PIXABAY_API_KEY,
    )
    state = StageState(
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs={},
        artifacts={"verified_storyboard": storyboard_key},
    )
    output = await worker(state)
    result_artifact = output.artifact
    if not isinstance(result_artifact, AssetManifestArtifact):
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="AcquisitionWorker returned unexpected artifact type")

    manifest_lineage = LineageEnvelope(
        run_id=body.run_id,
        worker="acquisition_worker",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version=ACQUISITION_WORKER_REGISTRATION.prompt_version,
        model=ACQUISITION_WORKER_REGISTRATION.model,
        created_at=datetime.now(),
    )
    manifest_record = await write_artifact(
        storage,
        result_artifact,
        name="asset_manifest",
        stage="acquisition",
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        lineage=manifest_lineage,
    )

    return AcquisitionWorkerResponse(
        manifest_key=manifest_record.r2_key,
        footage_summary=result_artifact.footage_summary,
        acquired=result_artifact.acquired,
        failed=result_artifact.failed,
    )


class RenderWorkerRequest(BaseModel):
    """Request body for POST /platform/workers/render."""

    run_id: str
    format_track: str = "landscape"


class RenderWorkerResponse(BaseModel):
    """Response body for POST /platform/workers/render (accepted — render runs async)."""

    status: str = "accepted"
    run_id: str


async def _run_render_background(
    run_id: str,
    job_id: str,
    state: StageState,
    worker: Any,
    storage: ArtifactStorage,
    settings: Any,
) -> None:
    """Background task: runs FFmpeg render and updates current_job.json in R2."""
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope

    job_key = f"runs/{run_id}/render/current_job.json"
    try:
        output = await worker(state)
        result_artifact = output.artifact
        if not isinstance(result_artifact, RenderArtifact):
            raise RuntimeError(f"RenderWorker returned unexpected artifact type: {type(result_artifact)}")

        render_lineage = LineageEnvelope(
            run_id=run_id,
            worker="render_worker",
            worker_version=RENDER_WORKER_REGISTRATION.worker_version,
            prompt_version=RENDER_WORKER_REGISTRATION.prompt_version,
            model=RENDER_WORKER_REGISTRATION.model,
            created_at=datetime.now(),
        )
        await write_artifact(
            storage,
            result_artifact,
            name="render_result",
            stage="render",
            run_id=run_id,
            user_id=_PLATFORM_USER_ID,
            lineage=render_lineage,
        )
        await storage.put_json(job_key, {
            "job_id": job_id,
            "status": "complete",
            "video_key": result_artifact.video_key,
            "scene_count": result_artifact.scene_count,
            "duration_s": result_artifact.duration_s,
        })
        _logger.info("RenderWorker background task complete for run %s job %s", run_id, job_id)
    except Exception as exc:
        _logger.exception("RenderWorker background task failed for run %s: %s", run_id, exc)
        try:
            await storage.put_json(job_key, {"job_id": job_id, "status": "error", "error": str(exc)})
        except Exception:
            pass


@router.post("/workers/render", response_model=RenderWorkerResponse, status_code=202)
async def render_worker_endpoint(
    body: RenderWorkerRequest,
    background_tasks: BackgroundTasks,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> RenderWorkerResponse:
    """Enqueue an FFmpeg render for an acquired run (returns 202 immediately).

    The actual render runs as a background task — FFmpeg can take several minutes.
    Poll GET /platform/studio/runs/{run_id}/render/status for progress.
    """
    import uuid as _uuid_mod

    def _latest_key(keys: list[str]) -> str:
        return sorted(keys)[-1]

    sb_prefix = f"users/{_PLATFORM_USER_ID}/runs/{body.run_id}/storyboard/verified_storyboard@v"
    sb_keys = await storage.list_keys(sb_prefix)
    if not sb_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No verified_storyboard artifact for run_id={body.run_id!r}.",
        )

    mf_prefix = f"users/{_PLATFORM_USER_ID}/runs/{body.run_id}/acquisition/asset_manifest@v"
    mf_keys = await storage.list_keys(mf_prefix)
    if not mf_keys:
        raise HTTPException(
            status_code=404,
            detail=f"No asset_manifest artifact for run_id={body.run_id!r}. "
                   "Run /platform/workers/acquisition first.",
        )

    artifacts: dict[str, str] = {
        "verified_storyboard": _latest_key(sb_keys),
        "asset_manifest": _latest_key(mf_keys),
    }

    va_prefix = f"users/{_PLATFORM_USER_ID}/runs/{body.run_id}/voice/voice_alignment@v"
    va_keys = await storage.list_keys(va_prefix)
    if va_keys:
        artifacts["voice_alignment"] = _latest_key(va_keys)

    worker = build_render_worker(
        storage,
        color_grade_preset=settings.COLOR_GRADE_PRESET,
        blur_fill_enabled=settings.BLUR_FILL_ENABLED,
        ffmpeg_timeout_seconds=settings.FFMPEG_TIMEOUT_SECONDS,
    )
    state = StageState(
        run_id=body.run_id,
        user_id=_PLATFORM_USER_ID,
        inputs={"format_track": body.format_track},
        artifacts=artifacts,
    )

    # Write job marker BEFORE enqueuing so the status endpoint knows a fresh render is running.
    # This prevents the old final.mp4 (from a previous killed render) from being returned
    # as "complete" before the new FFmpeg job finishes.
    job_id = str(_uuid_mod.uuid4())
    await storage.put_json(
        f"runs/{body.run_id}/render/current_job.json",
        {"job_id": job_id, "status": "running"},
    )

    background_tasks.add_task(_run_render_background, body.run_id, job_id, state, worker, storage, settings)
    _logger.info("RenderWorker background task enqueued for run %s job %s", body.run_id, job_id)
    return RenderWorkerResponse(status="accepted", run_id=body.run_id)


# ── Studio read/patch endpoints ───────────────────────────────────────────────


async def _latest_artifact_key(storage: ArtifactStorage, run_id: str, stage: str, name: str) -> Optional[str]:
    """Return the R2 key for the latest version of an artifact, or None if absent."""
    prefix = f"users/{_PLATFORM_USER_ID}/runs/{run_id}/{stage}/{name}@v"
    keys = await storage.list_keys(prefix)
    return sorted(keys)[-1] if keys else None


@router.get("/studio/runs/{run_id}/script")
async def studio_get_script(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest script artifact body for a Studio run."""
    key = await _latest_artifact_key(storage, run_id, "script", "script")
    if not key:
        raise HTTPException(status_code=404, detail="No script artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return body


@router.get("/studio/runs/{run_id}/storyboard")
async def studio_get_storyboard(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest verified_storyboard artifact body for a Studio run."""
    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard artifact found for this run.")
    _, body = await read_artifact(storage, key)
    return body


@router.get("/studio/runs/{run_id}/manifest")
async def studio_get_manifest(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest asset_manifest artifact body, enriched with 1-hour presigned URLs.

    Each manifest entry gains an asset_url field so the Studio UI can render
    preview links without a second round-trip per scene.
    """
    key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not key:
        raise HTTPException(status_code=404, detail="No asset manifest found for this run.")
    _, body = await read_artifact(storage, key)
    for entry in body.get("manifest", {}).get("entries", []):
        file_key: Optional[str] = entry.get("file_key")
        if file_key:
            try:
                entry["asset_url"] = await storage.generate_presigned_url(file_key, expires_in=3600)
            except Exception:
                entry["asset_url"] = None
    return body


@router.get("/studio/runs/{run_id}/voice")
async def studio_get_voice(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return the latest voice_alignment artifact for a Studio run, with a presigned audio URL."""
    key = await _latest_artifact_key(storage, run_id, "voice", "voice_alignment")
    if not key:
        raise HTTPException(status_code=404, detail="No voice artifact found for this run.")
    _, body = await read_artifact(storage, key)
    mp3_url: Optional[str] = None
    mp3_r2_key: str = body.get("mp3_r2_key", "")
    if mp3_r2_key:
        try:
            mp3_url = await storage.generate_presigned_url(mp3_r2_key, expires_in=3600)
        except Exception:
            pass
    return {
        "artifact_key": key,
        "mp3_r2_key": mp3_r2_key,
        "mp3_url": mp3_url,
        "alignment_method": body.get("alignment_method", ""),
        "total_duration_s": body.get("total_duration_s", 0.0),
        "word_count": len(body.get("word_timestamps", [])),
    }


@router.get("/studio/runs/{run_id}/video")
async def studio_get_video_url(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Return a 24-hour presigned URL for this run's final.mp4."""
    video_key = f"runs/{run_id}/output/final.mp4"
    try:
        url = await storage.generate_presigned_url(video_key, expires_in=86400)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Video not found for this run: {exc}")
    return {"video_url": url, "video_key": video_key}


@router.get("/studio/runs/{run_id}/render/status")
async def studio_get_render_status(
    run_id: str,
    storage: ArtifactStorage = Depends(get_artifact_storage),
) -> dict:
    """Poll render progress.  Returns {status: running|complete|error, video_url?, error?}.

    Uses current_job.json written by the render endpoint as the source of truth so that
    a stale final.mp4 from a previously-killed render is not mistaken for a completed job.
    """
    job_key = f"runs/{run_id}/render/current_job.json"
    try:
        job = await storage.get_json(job_key)
        if job:
            if job.get("status") == "complete":
                video_key = job.get("video_key", f"runs/{run_id}/output/final.mp4")
                try:
                    url = await storage.generate_presigned_url(video_key, expires_in=86400)
                except Exception:
                    url = None
                return {
                    "status": "complete",
                    "video_url": url,
                    "video_key": video_key,
                    "scene_count": job.get("scene_count"),
                    "duration_s": job.get("duration_s"),
                }
            if job.get("status") == "error":
                return {"status": "error", "error": job.get("error", "Render failed")}
            # status == "running"
            return {"status": "running"}
    except Exception:
        pass

    # Fallback for runs rendered before the background-task refactor
    video_key = f"runs/{run_id}/output/final.mp4"
    try:
        url = await storage.generate_presigned_url(video_key, expires_in=86400)
        return {"status": "complete", "video_url": url, "video_key": video_key}
    except Exception:
        pass

    return {"status": "running"}


class ScenePatchRequest(BaseModel):
    """Fields that can be patched on a single storyboard scene via the Studio UI."""

    on_screen_text: Optional[str] = None
    on_screen_text_type: Optional[str] = None
    primary_stk: Optional[str] = None
    context_stk: Optional[str] = None
    concept_stk: Optional[str] = None
    clear_on_screen_text: bool = False


@router.patch("/studio/runs/{run_id}/storyboard/scenes/{scene_id}")
async def studio_patch_scene(
    run_id: str,
    scene_id: str,
    body: ScenePatchRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
) -> dict:
    """Patch one scene's editable fields and write a new storyboard artifact version.

    Recomputes render_options for all scenes (cumulative timing must stay coherent)
    using the same _patch_storyboard logic as the StoryboardWorker's internal cycle.
    """
    from cf_platform.workers.storyboard_worker import _apply_patches_and_render_options, _sanitize_storyboard_data, VerifiedStoryboardArtifact
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope
    from src.models import Storyboard

    key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not key:
        raise HTTPException(status_code=404, detail="No storyboard found — run storyboard generation first.")

    _, artifact_body = await read_artifact(storage, key)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(artifact_body["storyboard"]))

    patches: list[dict] = []
    if body.clear_on_screen_text:
        patches += [
            {"scene_id": scene_id, "field": "on_screen_text", "value": None},
            {"scene_id": scene_id, "field": "on_screen_text_type", "value": None},
        ]
    else:
        if body.on_screen_text is not None:
            patches.append({"scene_id": scene_id, "field": "on_screen_text", "value": body.on_screen_text})
        if body.on_screen_text_type is not None:
            patches.append({"scene_id": scene_id, "field": "on_screen_text_type", "value": body.on_screen_text_type})
    if body.primary_stk is not None:
        patches.append({"scene_id": scene_id, "field": "primary_stk", "value": body.primary_stk})
    if body.context_stk is not None:
        patches.append({"scene_id": scene_id, "field": "context_stk", "value": body.context_stk})
    if body.concept_stk is not None:
        patches.append({"scene_id": scene_id, "field": "concept_stk", "value": body.concept_stk})

    if not patches:
        raise HTTPException(status_code=400, detail="No patchable fields provided.")

    patched_storyboard = _apply_patches_and_render_options(storyboard, patches)

    new_artifact = VerifiedStoryboardArtifact(
        prompt_version=artifact_body.get("prompt_version", "patched"),
        scene_count=len(patched_storyboard.scenes),
        storyboard=patched_storyboard.model_dump(by_alias=True, mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_patch",
        worker_version="1.0.0",
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )
    record = await write_artifact(
        storage, new_artifact,
        name="verified_storyboard", stage="storyboard",
        run_id=run_id, user_id=_PLATFORM_USER_ID, lineage=lineage,
    )
    return {"artifact_key": record.r2_key, "scene_count": new_artifact.scene_count}


# ── Per-scene asset override endpoints (P10-S2) ───────────────────────────────


class SceneReacquireRequest(BaseModel):
    """Request body for POST /studio/runs/{run_id}/scenes/{scene_n}/reacquire."""

    query: str


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/reacquire")
async def studio_reacquire_scene(
    run_id: str,
    scene_n: str,
    body: SceneReacquireRequest,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Re-acquire a single scene's asset using a custom query.

    Reads the latest verified_storyboard and asset_manifest. Overrides the scene's
    primary_stk with the supplied query, re-runs acquisition for that one scene, writes
    a new asset_manifest artifact version, emits an operator_asset_override TraceEvent,
    and returns the updated entry with a 1-hour presigned preview URL.
    """
    import time
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope, TraceEvent
    from cf_platform.workers.acquisition_worker import (
        _acquire_single_scene,
        ACQUISITION_WORKER_REGISTRATION,
        AssetManifestArtifact,
        _compute_footage_summary,
    )
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact, _sanitize_storyboard_data
    from src.models import AssetManifest, ManifestEntry, Storyboard
    from src.pexels import PexelsClient
    from src.pixabay_client import PixabayClient
    from src.wikimedia_client import WikimediaClient

    if not body.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")

    # Load storyboard
    sb_key = await _latest_artifact_key(storage, run_id, "storyboard", "verified_storyboard")
    if not sb_key:
        raise HTTPException(status_code=404, detail="No storyboard found for this run.")
    _, sb_body = await read_artifact(storage, sb_key)
    sb_artifact = VerifiedStoryboardArtifact.model_validate(sb_body)
    storyboard = Storyboard.model_validate(_sanitize_storyboard_data(sb_artifact.storyboard))

    scene = next((s for s in storyboard.scenes if str(s.scene) == scene_n), None)
    if scene is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in storyboard.")

    # Load manifest
    mf_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not mf_key:
        raise HTTPException(status_code=404, detail="No asset manifest found — run acquisition first.")
    _, mf_body = await read_artifact(storage, mf_key)
    manifest = AssetManifest.model_validate(mf_body["manifest"])

    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        # Bootstrap a new entry if the manifest predates this scene
        entry = ManifestEntry(
            scene_id=scene.scene,
            clip_type=scene.clip_type,
            segment_type=scene.segment_type,
            primary_stk=body.query.strip(),
            context_stk=scene.context_stk,
            concept_stk=scene.concept_stk,
            person_name=scene.person_name,
            person_title=scene.person_title,
            duration_s=scene.duration_s,
            historic=scene.historic,
            asset_tier=scene.asset_tier,
        )
        manifest.entries.append(entry)

    original_query = entry.primary_stk
    entry.primary_stk = body.query.strip()

    pexels = PexelsClient(api_key=settings.PEXELS_API_KEY)
    pixabay: Optional[PixabayClient] = PixabayClient(api_key=settings.PIXABAY_API_KEY) if settings.PIXABAY_API_KEY else None
    wikimedia = WikimediaClient()

    t0 = time.monotonic()
    await _acquire_single_scene(scene, entry, pexels, pixabay, wikimedia, storage, run_id)
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Write new manifest artifact version
    footage_summary = _compute_footage_summary(manifest.entries)
    acquired = sum(1 for e in manifest.entries if e.status == "acquired")
    new_artifact = AssetManifestArtifact(
        scene_count=len(manifest.entries),
        acquired=acquired,
        failed=len(manifest.entries) - acquired,
        footage_summary=footage_summary,
        manifest=manifest.model_dump(mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_reacquire",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )
    await write_artifact(
        storage, new_artifact,
        name="asset_manifest", stage="acquisition",
        run_id=run_id, user_id=_PLATFORM_USER_ID, lineage=lineage,
    )

    # Emit operator override trace event
    await trace_events.record(TraceEvent(
        run_id=run_id,
        worker="studio_reacquire",
        source="operator",
        op="operator_asset_override",
        latency_ms=latency_ms,
        status="ok" if entry.status == "acquired" else "error",
        meta={
            "scene_n": scene_n,
            "reason": "reacquire",
            "original_query": original_query,
            "override_query": body.query.strip(),
        },
    ))

    preview_url: Optional[str] = None
    if entry.file_key:
        try:
            preview_url = await storage.generate_presigned_url(entry.file_key, expires_in=3600)
        except Exception:
            pass

    return {
        "scene_n": scene_n,
        "file_key": entry.file_key,
        "source": entry.source,
        "qa_passed": entry.qa_passed,
        "preview_url": preview_url,
    }


@router.post("/studio/runs/{run_id}/scenes/{scene_n}/upload")
async def studio_upload_scene_asset(
    run_id: str,
    scene_n: str,
    file: UploadFile,
    storage: ArtifactStorage = Depends(get_artifact_storage),
    settings: PlatformSettings = Depends(get_platform_settings),
    trace_events: TraceEventRepository = Depends(get_trace_event_repository),
) -> dict:
    """Upload an operator-supplied asset for a single scene.

    Validates MIME type and size (≤200 MB), stores to R2, patches the asset_manifest
    entry for this scene, writes a new manifest version, and emits an
    operator_asset_override TraceEvent. Returns the updated entry with a presigned URL.
    """
    import time
    from cf_platform.core.artifact_manager import write_artifact
    from cf_platform.core.schemas import LineageEnvelope, TraceEvent
    from cf_platform.workers.acquisition_worker import (
        ACQUISITION_WORKER_REGISTRATION,
        AssetManifestArtifact,
        _compute_footage_summary,
    )
    from src.models import AssetManifest, ManifestEntry

    _ALLOWED_MIME_TYPES = {
        "video/mp4", "video/webm",
        "image/jpeg", "image/png", "image/webp",
    }
    _MIME_TO_EXT = {
        "video/mp4": ".mp4", "video/webm": ".webm",
        "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    }
    _MAX_BYTES = 200 * 1024 * 1024  # 200 MB

    content_type = (file.content_type or "").split(";")[0].strip()
    if content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type: {content_type!r}. Allowed: mp4, webm, jpg, png, webp.")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=422, detail=f"File too large ({len(data) // (1024*1024)} MB). Maximum is 200 MB.")

    ext = _MIME_TO_EXT[content_type]
    is_video = content_type.startswith("video/")
    folder = "video" if is_video else "images"
    r2_key = f"runs/{run_id}/{folder}/scene_{scene_n.zfill(2)}_op{ext}"

    await storage.put_bytes(r2_key, data, content_type=content_type)

    # Load and patch manifest
    mf_key = await _latest_artifact_key(storage, run_id, "acquisition", "asset_manifest")
    if not mf_key:
        raise HTTPException(status_code=404, detail="No asset manifest found — run acquisition first.")
    _, mf_body = await read_artifact(storage, mf_key)
    manifest = AssetManifest.model_validate(mf_body["manifest"])

    entry = next((e for e in manifest.entries if str(e.scene_id) == scene_n), None)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Scene {scene_n!r} not found in manifest.")

    entry.file_key = r2_key
    entry.source = "operator_upload"
    entry.status = "acquired"
    entry.qa_passed = True
    entry.fallback_used = False

    footage_summary = _compute_footage_summary(manifest.entries)
    acquired = sum(1 for e in manifest.entries if e.status == "acquired")
    new_artifact = AssetManifestArtifact(
        scene_count=len(manifest.entries),
        acquired=acquired,
        failed=len(manifest.entries) - acquired,
        footage_summary=footage_summary,
        manifest=manifest.model_dump(mode="json"),
        generated_at=datetime.now(),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="studio_upload",
        worker_version=ACQUISITION_WORKER_REGISTRATION.worker_version,
        prompt_version="manual",
        model="none",
        created_at=datetime.now(),
    )

    t0 = time.monotonic()
    await write_artifact(
        storage, new_artifact,
        name="asset_manifest", stage="acquisition",
        run_id=run_id, user_id=_PLATFORM_USER_ID, lineage=lineage,
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    await trace_events.record(TraceEvent(
        run_id=run_id,
        worker="studio_upload",
        source="operator",
        op="operator_asset_override",
        latency_ms=latency_ms,
        status="ok",
        meta={"scene_n": scene_n, "reason": "upload", "r2_key": r2_key},
    ))

    try:
        preview_url = await storage.generate_presigned_url(r2_key, expires_in=3600)
    except Exception:
        preview_url = None

    return {
        "scene_n": scene_n,
        "file_key": r2_key,
        "preview_url": preview_url,
    }


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
    format_track: str = "portrait",
    command_name: str = "pipeline",
) -> None:
    """Run the full pipeline in the background and push a video URL reply to Telegram.

    Separated from webhook handlers so they can return {"ok": True} immediately —
    full pipeline runs take 5–10 minutes (LLM calls + ffmpeg render).

    `display_label` is shown in the Telegram reply (niche for /run, idea title for /produce
    and /pick). `niche` and `idea_title` are passed to PipelineState; when `idea_title` is
    set the orchestrator skips niche_to_ideas (P7-S1). `format_track` selects portrait
    (1080×1920, default) or landscape (1920×1080) output. `command_name` is used only in
    error messages for operator clarity.
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
            pexels_api_key=settings.PEXELS_API_KEY,
            pixabay_api_key=settings.PIXABAY_API_KEY,
            color_grade_preset=settings.COLOR_GRADE_PRESET,
            blur_fill_enabled=settings.BLUR_FILL_ENABLED,
            ffmpeg_timeout_seconds=settings.FFMPEG_TIMEOUT_SECONDS,
        )
        state = PipelineState(
            run_id=run.run_id,
            user_id=_PLATFORM_USER_ID,
            inputs=run_inputs,
            target_duration_seconds=target_duration_seconds,
            idea_title=idea_title,
            format_track=format_track,
        )
        result = await run_graph(graph, state, thread_id=run.run_id)
        await transition_run(run.run_id, "complete", runs)

        video_r2_key: str = result.artifacts["video"]
        video_url = await storage.generate_presigned_url(video_r2_key, expires_in=_VIDEO_URL_EXPIRY)

        # Read youtube_metadata artifact when present; absent or failed → reply without it.
        metadata: Optional[YoutubeMetadataArtifact] = None
        meta_key = result.artifacts.get("youtube_metadata")
        if meta_key:
            try:
                _, meta_body = await read_artifact(storage, meta_key)
                metadata = YoutubeMetadataArtifact.model_validate(meta_body)
            except Exception as meta_exc:  # noqa: BLE001
                _logger.warning(
                    "_run_pipeline_and_reply: could not read youtube_metadata for run_id=%s: %s",
                    run.run_id,
                    meta_exc,
                )

        # Read footage_summary side-car written by the legacy adapter (P8-S5).
        # Written to R2 as runs/{run_id}/footage_summary.json; absent in tests and
        # non-acquisition environments — graceful fallback to None (no coverage line).
        footage_summary: Optional[dict] = None
        try:
            footage_summary = await storage.get_json(f"runs/{run.run_id}/footage_summary.json")
        except Exception:  # noqa: BLE001
            pass

        reply = format_produce_reply(display_label, run.run_id, video_url, metadata, footage_summary)
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
    format_track: str = "portrait",
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
        format_track=format_track,
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
            parsed_niche, duration, run_format = parse_run_args(run_args)
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
                    format_track=run_format,
                    command_name="run",
                )
    elif produce_args is not None:
        if not produce_args:
            await client.send_message(chat_id, format_produce_usage())
        else:
            parsed_title, duration, produce_format = parse_produce_args(produce_args)
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
                    format_track=produce_format,
                    command_name="produce",
                )
    elif pick_result is not None:
        original_run_id, idea_number, pick_duration, pick_format = pick_result
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
            format_track=pick_format,
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
