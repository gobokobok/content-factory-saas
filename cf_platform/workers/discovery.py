"""Discovery worker (P3-S2, D050) — `signals -> {niche, generated_at, signals}`.

Pure aggregation/normalization only (D040/D056): calls each configured
`SourceAdapter.fetch(niche, params)`, merges the resulting `Signal`s into one
`SignalsArtifact` (plan §6), and records one `TraceEvent` per source (D050,
D057). No deduplication, topic generation, scoring, or ranking — that lives in
P4 (Topic Generator / Opportunity Scoring) over the `signals` artifact this
worker produces.

Partial-failure isolation (AC #3): if `adapter.fetch()` raises for one source,
that source's trace event is recorded with `status="error"` and the worker
continues with the remaining sources — one dead source never fails the worker
or drops the other sources' signals.

The artifact body is written by the observability wrapper (D056); this module
never sees its own r2_key.
"""

import time
from datetime import UTC, datetime

from pydantic import BaseModel

from cf_platform.core.schemas import Signal, SourceAdapter, StageState, TraceEvent, WorkerNode, WorkerOutput
from cf_platform.core.trace_repo import TraceEventRepository
from cf_platform.core.worker_registry import WorkerRegistration


class SignalsArtifact(BaseModel):
    """Artifact body produced by the discovery worker (plan §6)."""

    niche: str
    generated_at: datetime
    signals: list[Signal]


def build_discovery_worker(
    adapters: list[tuple[str, SourceAdapter]],
    trace_repo: TraceEventRepository,
) -> WorkerNode:
    """Return a discovery WorkerNode bound to adapters and trace_repo.

    `adapters` is a list of `(source_name, adapter)` pairs — the source name
    (e.g. "reddit", "google_trends", "youtube") identifies each adapter in its
    `TraceEvent`, independent of how many (or zero) `Signal`s it returns.
    """

    async def discovery_worker(state: StageState) -> WorkerOutput:
        """Fetch signals from every adapter and merge them into one SignalsArtifact."""
        niche = state.inputs["niche"]
        all_signals: list[Signal] = []

        for source, adapter in adapters:
            start = time.perf_counter()
            try:
                signals = await adapter.fetch(niche, {})
            except Exception as exc:  # noqa: BLE001 - partial-failure isolation (AC #3)
                await trace_repo.record(
                    TraceEvent(
                        run_id=state.run_id,
                        worker="discovery",
                        source=source,
                        op="fetch",
                        latency_ms=int((time.perf_counter() - start) * 1000),
                        status="error",
                        meta={"error": str(exc)},
                    )
                )
                continue

            await trace_repo.record(
                TraceEvent(
                    run_id=state.run_id,
                    worker="discovery",
                    source=source,
                    op="fetch",
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    status="ok",
                    meta={"signal_count": len(signals)},
                )
            )
            all_signals.extend(signals)

        artifact = SignalsArtifact(niche=niche, generated_at=datetime.now(UTC), signals=all_signals)
        return WorkerOutput(artifact=artifact)

    return discovery_worker


DISCOVERY_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt="discovery v1 — aggregates SourceAdapter signals, no LLM call",
    model="none",
    sampling_params={},
)
