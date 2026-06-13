"""Tests for cf_platform/core/worker_registry.py (P1-S5)."""

import pytest
from pydantic import BaseModel

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, read_artifact
from cf_platform.core.execution_engine import run_graph
from cf_platform.core.schemas import StageState, WorkerOutput
from cf_platform.core.worker_registry import (
    InMemoryExecutionRepository,
    PromptVersionNotFoundError,
    WorkerNotRegisteredError,
    WorkerRegistration,
    WorkerRegistry,
    build_observed_node_graph,
    wrap,
)


class EchoArtifact(BaseModel):
    """Trivial artifact body for testing the observability wrapper."""

    message: str


async def echo_worker(state: StageState) -> WorkerOutput:
    """Pure worker — echoes state.inputs['message'] back as an EchoArtifact. No storage/DB knowledge."""
    return WorkerOutput(artifact=EchoArtifact(message=state.inputs["message"]))


def _registration(prompt_version: str = "v1", prompt: str = "echo prompt v1") -> WorkerRegistration:
    """Build a sample WorkerRegistration for tests."""
    return WorkerRegistration(
        worker_version="1.0.0",
        prompt_version=prompt_version,
        prompt=prompt,
        model="claude-haiku-4-5-20251001",
        sampling_params={"temperature": 0.0},
    )


class TestWorkerRegistry:
    def test_register_and_resolve(self):
        """resolve() returns the registration passed to register()."""
        registry = WorkerRegistry()
        registration = _registration()
        registry.register("echo", registration)

        assert registry.resolve("echo") == registration

    def test_resolve_unregistered_worker_raises(self):
        """resolve() raises WorkerNotRegisteredError for an unknown worker name."""
        registry = WorkerRegistry()

        with pytest.raises(WorkerNotRegisteredError):
            registry.resolve("echo")

    def test_get_prompt_returns_registered_prompt(self):
        """get_prompt() returns the prompt body for worker@prompt_version."""
        registry = WorkerRegistry()
        registry.register("echo", _registration(prompt_version="v1", prompt="prompt body v1"))

        assert registry.get_prompt("echo", "v1") == "prompt body v1"

    def test_get_prompt_unknown_version_raises(self):
        """get_prompt() raises PromptVersionNotFoundError for an unregistered prompt_version."""
        registry = WorkerRegistry()
        registry.register("echo", _registration(prompt_version="v1"))

        with pytest.raises(PromptVersionNotFoundError):
            registry.get_prompt("echo", "v2")

    def test_older_prompt_versions_remain_retrievable(self):
        """Re-registering with a new prompt_version keeps older prompt bodies retrievable (D055 replay)."""
        registry = WorkerRegistry()
        registry.register("echo", _registration(prompt_version="v1", prompt="prompt body v1"))
        registry.register("echo", _registration(prompt_version="v2", prompt="prompt body v2"))

        assert registry.get_prompt("echo", "v1") == "prompt body v1"
        assert registry.get_prompt("echo", "v2") == "prompt body v2"
        assert registry.resolve("echo").prompt_version == "v2"


class TestWrap:
    @pytest.mark.asyncio
    async def test_unregistered_worker_raises_immediately(self):
        """wrap() raises WorkerNotRegisteredError for an unregistered worker without calling node."""
        registry = WorkerRegistry()
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        with pytest.raises(WorkerNotRegisteredError):
            wrap("echo", "echo", echo_worker, registry=registry, storage=storage, executions=executions)

    @pytest.mark.asyncio
    async def test_emits_exactly_one_artifact_and_execution(self):
        """A wrapped node writes exactly one artifact and records exactly one WorkerExecution."""
        registry = WorkerRegistry()
        registry.register("echo", _registration())
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        node_fn = wrap("echo", "echo", echo_worker, registry=registry, storage=storage, executions=executions)
        state = StageState(run_id="r1", user_id="u1", inputs={"message": "hello"})

        result = await node_fn(state)

        assert len(await storage.list_keys("users/u1/runs/r1/echo/")) == 1
        recorded = await executions.list_for_run("r1")
        assert len(recorded) == 1
        assert result == {"artifacts": {"echo": recorded[0].artifact_r2_key}}

    @pytest.mark.asyncio
    async def test_artifact_body_and_lineage_match_registration(self):
        """The persisted artifact body matches WorkerOutput.artifact and its lineage matches the registration."""
        registry = WorkerRegistry()
        registry.register("echo", _registration())
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        node_fn = wrap("echo", "echo", echo_worker, registry=registry, storage=storage, executions=executions)
        state = StageState(run_id="r1", user_id="u1", inputs={"message": "hello"})

        result = await node_fn(state)
        r2_key = result["artifacts"]["echo"]
        artifact, body = await read_artifact(storage, r2_key)

        assert body == {"message": "hello"}
        assert artifact.lineage.worker == "echo"
        assert artifact.lineage.worker_version == "1.0.0"
        assert artifact.lineage.prompt_version == "v1"
        assert artifact.lineage.model == "claude-haiku-4-5-20251001"
        assert artifact.lineage.sampling_params == {"temperature": 0.0}
        assert artifact.lineage.run_id == "r1"

    @pytest.mark.asyncio
    async def test_execution_record_matches_registration_and_artifact(self):
        """The recorded WorkerExecution carries the registration's lineage and the artifact's r2_key."""
        registry = WorkerRegistry()
        registry.register("echo", _registration())
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        node_fn = wrap("echo", "echo", echo_worker, registry=registry, storage=storage, executions=executions)
        state = StageState(run_id="r1", user_id="u1", inputs={"message": "hello"})

        result = await node_fn(state)
        execution = (await executions.list_for_run("r1"))[0]

        assert execution.worker == "echo"
        assert execution.worker_version == "1.0.0"
        assert execution.prompt_version == "v1"
        assert execution.model == "claude-haiku-4-5-20251001"
        assert execution.sampling_params == {"temperature": 0.0}
        assert execution.status == "ok"
        assert execution.artifact_r2_key == result["artifacts"]["echo"]
        assert execution.latency_ms >= 0
        assert execution.started_at <= execution.finished_at

    @pytest.mark.asyncio
    async def test_worker_receives_only_stage_state(self):
        """The wrapped worker callable's only input is StageState — it never sees its own r2_key."""
        received: list[StageState] = []

        async def recording_worker(state: StageState) -> WorkerOutput:
            received.append(state)
            return WorkerOutput(artifact=EchoArtifact(message="ok"))

        registry = WorkerRegistry()
        registry.register("echo", _registration())
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        node_fn = wrap("echo", "echo", recording_worker, registry=registry, storage=storage, executions=executions)
        state = StageState(run_id="r1", user_id="u1", inputs={})

        await node_fn(state)

        assert len(received) == 1
        assert isinstance(received[0], StageState)
        assert "echo" not in received[0].artifacts


class TestBuildObservedNodeGraph:
    @pytest.mark.asyncio
    async def test_runs_state_through_to_real_artifact_ref(self):
        """The compiled graph injects a real r2_key (not a JSON placeholder) into state.artifacts."""
        registry = WorkerRegistry()
        registry.register("echo", _registration())
        storage = InMemoryArtifactStorage()
        executions = InMemoryExecutionRepository()

        graph = build_observed_node_graph(
            "echo", "echo", echo_worker, registry=registry, storage=storage, executions=executions
        )
        state = StageState(run_id="r1", user_id="u1", inputs={"message": "hello"})

        result = await run_graph(graph, state, thread_id="t1")

        r2_key = result.artifacts["echo"]
        assert r2_key.startswith("users/u1/runs/r1/echo/echo@v1.json")
        artifact, body = await read_artifact(storage, r2_key)
        assert body == {"message": "hello"}
        assert (await executions.list_for_run("r1"))[0].artifact_r2_key == r2_key
