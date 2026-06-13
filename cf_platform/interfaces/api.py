"""Platform-facing REST API routes for cf_platform, mounted under /platform in src/main.py."""

from fastapi import APIRouter, Depends
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from cf_platform.core.artifact_manager import (
    ArtifactRepository,
    ArtifactStorage,
    InMemoryArtifactRepository,
    R2ArtifactStorage,
)
from cf_platform.core.config import get_platform_settings
from cf_platform.core.db import check_db_health, get_checkpointer, get_pool
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
)
from cf_platform.core.run_manager import InMemoryRunRepository, RunRepository, create_run, transition_run
from cf_platform.core.schemas import StageState
from cf_platform.core.worker_registry import (
    ExecutionRepository,
    InMemoryExecutionRepository,
    WorkerRegistry,
    build_observed_node_graph,
)
from cf_platform.workers.echo import ECHO_REGISTRATION, echo_worker

router = APIRouter()

# Single-operator platform (multi-tenant isolation lands in S19) — fixed user_id for now.
_PLATFORM_USER_ID = "operator"

# In-memory fallback when DATABASE_URL is unset (D048) — process-local singletons.
_run_repository = InMemoryRunRepository()
_execution_repository = InMemoryExecutionRepository()
_artifact_repository = InMemoryArtifactRepository()
_worker_registry = WorkerRegistry()
_worker_registry.register("echo", ECHO_REGISTRATION)


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


def get_worker_registry() -> WorkerRegistry:
    """Return the process-local WorkerRegistry, pre-populated with the echo worker."""
    return _worker_registry


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
