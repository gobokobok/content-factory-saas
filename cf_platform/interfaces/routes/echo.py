"""Echo route — POST /echo. Proves the LangGraph + observability + artifact spine end to end."""

from fastapi import APIRouter, Depends
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.run_manager import RunRepository, create_run, transition_run
from cf_platform.core.schemas import StageState
from cf_platform.core.worker_registry import (
    ExecutionRepository,
    WorkerRegistry,
    build_observed_node_graph,
)
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_repository,
    get_artifact_storage,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
    get_worker_registry,
)
from cf_platform.workers.echo import echo_worker

router = APIRouter()


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
    run = await create_run(PLATFORM_USER_ID, "echo", {"text": body.text}, runs)
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
    state = StageState(run_id=run.run_id, user_id=PLATFORM_USER_ID, inputs={"message": body.text})
    result = await run_graph(graph, state, thread_id=run.run_id)

    await transition_run(run.run_id, "complete", runs)

    return EchoResponse(run_id=run.run_id, artifact_key=result.artifacts["echo"])
