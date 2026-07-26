"""HITL auto-approve timeout coroutine (P6-S3).

When a pipeline run is interrupted at the script-approval gate with
`PipelineState.hitl=True` and `HITL_TIMEOUT_SECONDS > 0`, this coroutine
fires after the configured delay and resumes the pipeline automatically with
an "approve" decision — implementing the "default fully autonomous" contract.

Usage (P6-S4 will wire this into /produce):
    asyncio.create_task(
        auto_approve_after_timeout(run_id, settings.HITL_TIMEOUT_SECONDS, graph)
    )
"""

import asyncio
import logging

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

_logger = logging.getLogger(__name__)


async def auto_approve_after_timeout(
    run_id: str,
    timeout_seconds: int,
    graph: CompiledStateGraph,
    thread_id: str | None = None,
) -> None:
    """Sleep for `timeout_seconds` then auto-approve the interrupted pipeline run.

    No-op when `timeout_seconds <= 0`. Logs and swallows exceptions so that a
    failed auto-approve does not crash the caller's background task.

    `thread_id` defaults to `run_id` (the convention used by the full pipeline
    orchestrator). Pass an explicit value only when the pipeline uses a different
    thread_id scheme.
    """
    if timeout_seconds <= 0:
        return
    tid = thread_id or run_id
    await asyncio.sleep(timeout_seconds)
    config = {"configurable": {"thread_id": tid}}
    try:
        await graph.ainvoke(Command(resume="approve"), config=config)
        _logger.info("Auto-approved run %s after %ds HITL timeout", run_id, timeout_seconds)
    except Exception as exc:
        _logger.error("Auto-approve failed for run %s: %s", run_id, exc)
