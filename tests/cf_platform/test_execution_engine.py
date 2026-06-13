"""Tests for cf_platform/core/execution_engine.py (P1-S4, P2-S4)."""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pydantic import BaseModel

from cf_platform.core.execution_engine import build_single_node_graph, run_graph
from cf_platform.core.schemas import StageState, WorkerOutput


class EchoArtifact(BaseModel):
    """Trivial artifact body for testing the execution engine."""

    message: str


async def echo_worker(state: StageState) -> WorkerOutput:
    """Pure worker — echoes state.inputs['message'] back as an EchoArtifact. No storage/DB knowledge."""
    return WorkerOutput(artifact=EchoArtifact(message=state.inputs["message"]))


class TestBuildSingleNodeGraph:
    @pytest.mark.asyncio
    async def test_runs_state_through_worker_output_back_to_state(self):
        """A 1-node graph runs state -> WorkerOutput -> state, merging the artifact ref."""
        graph = build_single_node_graph("echo", echo_worker)
        state = StageState(run_id="r1", user_id="u1", inputs={"message": "hello"})

        result = await run_graph(graph, state, thread_id="t1")

        assert isinstance(result, StageState)
        assert result.run_id == "r1"
        assert result.artifacts["echo"] == '{"message":"hello"}'

    @pytest.mark.asyncio
    async def test_checkpoints_in_memory(self):
        """The MemorySaver checkpointer persists state for a thread_id across invocations."""
        graph = build_single_node_graph("echo", echo_worker)
        state = StageState(run_id="r2", user_id="u1", inputs={"message": "first"})

        await run_graph(graph, state, thread_id="t2")
        snapshot = await graph.aget_state({"configurable": {"thread_id": "t2"}})

        assert snapshot.values["artifacts"]["echo"] == '{"message":"first"}'

    @pytest.mark.asyncio
    async def test_separate_threads_do_not_share_checkpoints(self):
        """Different thread_ids checkpoint independently."""
        graph = build_single_node_graph("echo", echo_worker)
        state_a = StageState(run_id="r3", user_id="u1", inputs={"message": "a"})
        state_b = StageState(run_id="r4", user_id="u1", inputs={"message": "b"})

        await run_graph(graph, state_a, thread_id="ta")
        await run_graph(graph, state_b, thread_id="tb")

        snap_a = await graph.aget_state({"configurable": {"thread_id": "ta"}})
        snap_b = await graph.aget_state({"configurable": {"thread_id": "tb"}})

        assert snap_a.values["artifacts"]["echo"] == '{"message":"a"}'
        assert snap_b.values["artifacts"]["echo"] == '{"message":"b"}'

    @pytest.mark.asyncio
    async def test_resumes_from_checkpoint_after_rebuild_with_same_checkpointer(self):
        """A run resumes from its last checkpoint when a new graph is built with the same checkpointer (P2-S4)."""
        checkpointer = MemorySaver()
        state = StageState(run_id="r6", user_id="u1", inputs={"message": "durable"})

        first_graph = build_single_node_graph("echo", echo_worker, checkpointer=checkpointer)
        await run_graph(first_graph, state, thread_id="t6")

        second_graph = build_single_node_graph("echo", echo_worker, checkpointer=checkpointer)
        snapshot = await second_graph.aget_state({"configurable": {"thread_id": "t6"}})

        assert snapshot.values["artifacts"]["echo"] == '{"message":"durable"}'

    @pytest.mark.asyncio
    async def test_defaults_to_memory_saver_when_checkpointer_not_provided(self):
        """build_single_node_graph defaults to an in-memory MemorySaver checkpointer."""
        graph = build_single_node_graph("echo", echo_worker)

        assert isinstance(graph.checkpointer, MemorySaver)


class TestWorkerPurity:
    @pytest.mark.asyncio
    async def test_worker_receives_only_stage_state(self):
        """The worker callable's only input is StageState — no storage/DB args."""
        received: list[StageState] = []

        async def recording_worker(state: StageState) -> WorkerOutput:
            received.append(state)
            return WorkerOutput(artifact=EchoArtifact(message="ok"))

        graph = build_single_node_graph("echo", recording_worker)
        state = StageState(run_id="r5", user_id="u1", inputs={"message": "x"})

        await run_graph(graph, state, thread_id="t5")

        assert len(received) == 1
        assert isinstance(received[0], StageState)
        assert received[0].run_id == "r5"
