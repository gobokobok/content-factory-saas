"""Block routes — POST /blocks/niche-to-ideas, POST /blocks/idea-to-script."""

from typing import Any

from fastapi import APIRouter, Depends
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel

from cf_platform.blocks.idea_to_script import build_idea_to_script_graph, register_idea_to_script_workers  # noqa: F401
from cf_platform.blocks.niche_to_ideas import build_niche_to_ideas_graph, register_niche_to_ideas_workers  # noqa: F401
from cf_platform.core.artifact_manager import (
    ArtifactRepository,
    ArtifactStorage,
    read_artifact,
)
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.run_manager import RunRepository, create_run, transition_run
from cf_platform.core.schemas import IdeaToScriptState, NicheToIdeasState, SourceAdapter
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
from cf_platform.workers.opportunity_scorer import TopicScore
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.topic_selector import RankedIdeasArtifact

router = APIRouter()


class NicheToIdeasRequest(BaseModel):
    """Request body for POST /platform/blocks/niche-to-ideas."""

    niche: str
    audience: str | None = None
    mode: str | None = "single"


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

    run = await create_run(PLATFORM_USER_ID, "niche_to_ideas", run_inputs, runs)
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
        user_id=PLATFORM_USER_ID,
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
    niche: str | None = None
    angle: str | None = None
    supporting_points: list[str] | None = None
    max_iterations: int | None = None
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

    run = await create_run(PLATFORM_USER_ID, "idea_to_script", run_inputs, runs)
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
        user_id=PLATFORM_USER_ID,
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
