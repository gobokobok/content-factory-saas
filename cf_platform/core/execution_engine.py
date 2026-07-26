"""LangGraph execution engine (P1-S4) — Layer A: compile and run a graph over StageState.

Adopts `langgraph` (D052) and implements the Worker = Node contract (D056): a `WorkerNode`
is a pure `StageState -> WorkerOutput` callable with no storage/DB knowledge. This module
wraps a `WorkerNode` into a LangGraph node function, compiles a single-node `StateGraph`
with a `MemorySaver` checkpointer, and runs it.

Pure execution only — no lineage, no artifact persistence (that's Layer B, P1-S5). The
`state.artifacts[node_name]` value written here is a JSON-encoded placeholder of the
worker's artifact body, not a real r2_key; the observability wrapper replaces it.
"""

from typing import Any, TypeVar

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from cf_platform.core.schemas import StageState, WorkerNode

StateT = TypeVar("StateT", bound=StageState)


def build_single_node_graph(
    node_name: str, worker: WorkerNode, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Compile a 1-node StateGraph (START -> node_name -> END) wrapping `worker`.

    The node calls the pure `worker` body with the current state and merges
    `WorkerOutput.artifact` into `state.artifacts[node_name]` as a JSON-encoded
    placeholder — the worker body never sees or assigns its own r2_key.

    `checkpointer` defaults to `MemorySaver()` (in-memory, process-local). Pass a
    `cf_platform.core.db.get_checkpointer(...)` result for durable, restart-resumable
    checkpoints (P2-S4).
    """

    async def _node_fn(state: StageState) -> dict[str, Any]:
        output = await worker(state)
        return {"artifacts": {node_name: output.artifact.model_dump_json()}}

    graph = StateGraph(StageState)
    graph.add_node(node_name, _node_fn)
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


async def run_graph(graph: CompiledStateGraph, state: StateT, thread_id: str) -> StateT:
    """Run `graph` from `state`, checkpointed under `thread_id`. Returns the resulting state."""
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(state, config=config)
    return type(state).model_validate(result)
