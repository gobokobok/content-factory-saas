"""Tests for the discovery worker (P3-S2, D050).

Covers AC #2 (one signals artifact + one trace event per source) and AC #3
(one failing source does not fail the worker, others still aggregate).
"""

from typing import Optional

import pytest

from cf_platform.core.schemas import Signal, StageState
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.workers.discovery import SignalsArtifact, build_discovery_worker


class _StubAdapter:
    """SourceAdapter stub returning a fixed list of Signals or raising."""

    def __init__(self, signals: Optional[list[Signal]] = None, error: Optional[Exception] = None) -> None:
        self._signals = signals or []
        self._error = error

    async def fetch(self, niche, params):
        if self._error is not None:
            raise self._error
        return self._signals


def _state(niche: str = "starter homes") -> StageState:
    return StageState(run_id="run-1", user_id="user-1", inputs={"niche": niche})


class TestDiscoveryWorker:
    """build_discovery_worker aggregates signals and records trace events per source."""

    @pytest.mark.asyncio
    async def test_aggregates_signals_from_all_sources_into_one_artifact(self):
        reddit_signal = Signal(source="reddit", title="Reddit post", score=10.0)
        youtube_signal = Signal(source="youtube", title="YouTube video", score=20.0)
        trace_repo = InMemoryTraceEventRepository()

        worker = build_discovery_worker(
            adapters=[
                ("reddit", _StubAdapter(signals=[reddit_signal])),
                ("youtube", _StubAdapter(signals=[youtube_signal])),
            ],
            trace_repo=trace_repo,
        )

        output = await worker(_state())

        assert isinstance(output.artifact, SignalsArtifact)
        assert output.artifact.niche == "starter homes"
        assert output.artifact.signals == [reddit_signal, youtube_signal]
        assert output.control == "continue"

        events = await trace_repo.list_for_run("run-1")
        assert len(events) == 2
        assert {event.source for event in events} == {"reddit", "youtube"}
        assert all(event.worker == "discovery" and event.op == "fetch" and event.status == "ok" for event in events)

    @pytest.mark.asyncio
    async def test_one_failing_source_does_not_fail_worker(self):
        ok_signal = Signal(source="youtube", title="YouTube video", score=20.0)
        trace_repo = InMemoryTraceEventRepository()

        worker = build_discovery_worker(
            adapters=[
                ("google_trends", _StubAdapter(error=RuntimeError("boom"))),
                ("youtube", _StubAdapter(signals=[ok_signal])),
            ],
            trace_repo=trace_repo,
        )

        output = await worker(_state())

        assert output.artifact.signals == [ok_signal]

        events = await trace_repo.list_for_run("run-1")
        assert len(events) == 2
        events_by_source = {event.source: event for event in events}
        assert events_by_source["google_trends"].status == "error"
        assert "boom" in events_by_source["google_trends"].meta["error"]
        assert events_by_source["youtube"].status == "ok"

    @pytest.mark.asyncio
    async def test_no_adapters_returns_empty_signals(self):
        trace_repo = InMemoryTraceEventRepository()
        worker = build_discovery_worker(adapters=[], trace_repo=trace_repo)

        output = await worker(_state())

        assert output.artifact.signals == []
        assert await trace_repo.list_for_run("run-1") == []
