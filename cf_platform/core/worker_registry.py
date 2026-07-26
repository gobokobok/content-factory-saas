"""Worker Registry + observability wrapper (P1-S5) — Layer B.

Wraps a pure `WorkerNode` (Layer A, P1-S4) into a LangGraph node function that:
resolves `worker_version`/`prompt_version`/`model`/`sampling_params` from the
`WorkerRegistry`, times the call, persists `WorkerOutput.artifact` as a real,
versioned R2 artifact via the Artifact Manager (P1-S3), records exactly one
`WorkerExecution`, and injects `{node_name: r2_key}` into `StageState.artifacts`.
The worker body never sees or assigns its own `r2_key` (D056). Prompt bodies are
indexed by `worker@prompt_version` so older versions remain retrievable for replay
(D055).
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactRepository, ArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState, WorkerExecution, WorkerNode


class WorkerRegistration(BaseModel):
    """Pinned version/model/prompt configuration for one worker (D055)."""

    worker_version: str
    prompt_version: str
    prompt: str
    model: str
    sampling_params: dict[str, Any] = {}


class WorkerNotRegisteredError(Exception):
    """Raised when resolve() or wrap() is called for an unregistered worker name."""


class PromptVersionNotFoundError(Exception):
    """Raised when get_prompt() is called for a worker/prompt_version not on record."""


class ExecutionRepository(Protocol):
    """Persistence interface for WorkerExecution records — in-memory until P2."""

    async def record(self, execution: WorkerExecution) -> WorkerExecution:
        """Persist execution and return it."""
        ...

    async def list_for_run(self, run_id: str) -> list[WorkerExecution]:
        """Return all recorded executions for run_id."""
        ...


class InMemoryExecutionRepository:
    """In-memory ExecutionRepository implementation — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._executions: list[WorkerExecution] = []

    async def record(self, execution: WorkerExecution) -> WorkerExecution:
        """Append execution to the in-memory list and return it."""
        self._executions.append(execution)
        return execution

    async def list_for_run(self, run_id: str) -> list[WorkerExecution]:
        """Return all recorded executions for run_id, in recording order."""
        return [execution for execution in self._executions if execution.run_id == run_id]


class WorkerRegistry:
    """Resolves pinned worker configuration and stores prompt bodies by version (D055)."""

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._registrations: dict[str, WorkerRegistration] = {}
        self._prompts: dict[tuple[str, str], str] = {}

    def register(self, worker: str, registration: WorkerRegistration) -> None:
        """Register (or replace) the current pinned configuration for worker.

        Indexes `registration.prompt` under `(worker, registration.prompt_version)` —
        re-registering with a new prompt_version does not remove earlier versions,
        so prior prompt bodies remain retrievable via get_prompt() (D055 replay).
        """
        self._registrations[worker] = registration
        self._prompts[(worker, registration.prompt_version)] = registration.prompt

    def resolve(self, worker: str) -> WorkerRegistration:
        """Return the current WorkerRegistration for worker. Raises WorkerNotRegisteredError if absent."""
        try:
            return self._registrations[worker]
        except KeyError:
            raise WorkerNotRegisteredError(f"Worker not registered: {worker}") from None

    def get_prompt(self, worker: str, prompt_version: str) -> str:
        """Return the prompt body for worker@prompt_version. Raises PromptVersionNotFoundError if absent."""
        try:
            return self._prompts[(worker, prompt_version)]
        except KeyError:
            raise PromptVersionNotFoundError(f"No prompt for {worker}@{prompt_version}") from None


def wrap(
    worker: str,
    node_name: str,
    node: WorkerNode,
    *,
    registry: WorkerRegistry,
    storage: ArtifactStorage,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    control_channel: str | None = None,
) -> Callable[[StageState], Awaitable[dict[str, Any]]]:
    """Wrap a pure WorkerNode into a LangGraph node function with full observability.

    Resolves the worker's pinned configuration from registry, calls `node(state)`,
    writes `output.artifact` via the Artifact Manager (assigning the r2_key the
    worker body never sees), records the artifact's lineage row via `artifact_repo`
    (Postgres index, R2 stays blob truth — P2-S3), records exactly one
    WorkerExecution, and returns `{"artifacts": {node_name: r2_key}}` for the
    StageState.artifacts reducer (D056).

    When `control_channel` is provided, the node also returns
    `{control_channel: output.control}` so the calling graph can store the
    worker's routing signal in a typed state field without worker bodies ever
    reading or writing iteration bookkeeping (D057).

    Raises WorkerNotRegisteredError immediately if worker has no registration.
    """
    registration = registry.resolve(worker)

    async def _node_fn(state: Any) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        start_perf = time.perf_counter()
        output = await node(state)
        finished_at = datetime.now(UTC)
        latency_ms = int((time.perf_counter() - start_perf) * 1000)

        lineage = LineageEnvelope(
            run_id=state.run_id,
            worker=worker,
            worker_version=registration.worker_version,
            prompt_version=registration.prompt_version,
            model=registration.model,
            sampling_params=registration.sampling_params,
            created_at=finished_at,
        )
        artifact = await write_artifact(
            storage,
            output.artifact,
            name=node_name,
            stage=node_name,
            run_id=state.run_id,
            user_id=state.user_id,
            lineage=lineage,
        )
        await artifact_repo.record(artifact)
        execution = WorkerExecution(
            run_id=state.run_id,
            worker=worker,
            worker_version=registration.worker_version,
            prompt_version=registration.prompt_version,
            model=registration.model,
            sampling_params=registration.sampling_params,
            status="ok",
            artifact_r2_key=artifact.r2_key,
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=latency_ms,
        )
        await executions.record(execution)
        result: dict[str, Any] = {"artifacts": {node_name: artifact.r2_key}}
        if control_channel is not None:
            result[control_channel] = output.control
        return result

    return _node_fn


def build_observed_node_graph(
    node_name: str,
    worker: str,
    node: WorkerNode,
    *,
    registry: WorkerRegistry,
    storage: ArtifactStorage,
    executions: ExecutionRepository,
    artifact_repo: ArtifactRepository,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Compile a 1-node StateGraph (START -> node_name -> END) wrapping `node` via wrap().

    Like execution_engine.build_single_node_graph, but the node writes a real,
    versioned artifact via the Artifact Manager, records its lineage row via
    `artifact_repo`, and records a WorkerExecution instead of a JSON placeholder
    (Layer B).

    `checkpointer` defaults to `MemorySaver()` (in-memory, process-local). Pass a
    `cf_platform.core.db.get_checkpointer(...)` result for durable, restart-resumable
    checkpoints (P2-S4).
    """
    graph = StateGraph(StageState)
    graph.add_node(
        node_name,
        wrap(
            worker,
            node_name,
            node,
            registry=registry,
            storage=storage,
            executions=executions,
            artifact_repo=artifact_repo,
        ),
    )
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())
