"""Tests for cf_platform/core/trace_repo.py — InMemoryTraceEventRepository (P3-S2, D050)."""

import pytest

from cf_platform.core.schemas import TraceEvent
from cf_platform.core.trace_repo import InMemoryTraceEventRepository


def _trace_event(run_id: str, source: str) -> TraceEvent:
    """Build a sample TraceEvent for run_id from source."""
    return TraceEvent(
        run_id=run_id,
        worker="discovery",
        source=source,
        op="fetch",
        latency_ms=10,
        status="ok",
        meta={},
    )


class TestInMemoryTraceEventRepository:
    @pytest.mark.asyncio
    async def test_record_returns_event_unchanged(self):
        """record() returns the same event it was given."""
        repo = InMemoryTraceEventRepository()
        event = _trace_event("r1", "reddit")

        result = await repo.record(event)

        assert result == event

    @pytest.mark.asyncio
    async def test_list_for_run_returns_events_in_recording_order(self):
        """list_for_run() returns only events for run_id, in the order they were recorded."""
        repo = InMemoryTraceEventRepository()
        first = _trace_event("r1", "reddit")
        second = _trace_event("r1", "youtube")
        other_run = _trace_event("r2", "google_trends")

        await repo.record(first)
        await repo.record(other_run)
        await repo.record(second)

        result = await repo.list_for_run("r1")

        assert result == [first, second]

    @pytest.mark.asyncio
    async def test_list_for_run_empty_when_no_events(self):
        """list_for_run() returns an empty list when no events were recorded for run_id."""
        repo = InMemoryTraceEventRepository()

        result = await repo.list_for_run("missing")

        assert result == []
