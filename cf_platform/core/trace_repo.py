"""TraceEvent repository (P3-S2, D050/D048).

Source adapters and other IO boundaries emit `TraceEvent`s (never artifacts —
D050, D057). Persistence sits behind the `TraceEventRepository` Protocol;
`InMemoryTraceEventRepository` is the in-memory fallback (D048), swapped for
`PostgresTraceEventRepository` (cf_platform/core/postgres_repos.py) when
`DATABASE_URL` is set. Mirrors the `ArtifactRepository`/`ExecutionRepository`
pattern from artifact_manager.py/worker_registry.py.
"""

from typing import Protocol

from cf_platform.core.schemas import TraceEvent


class TraceEventRepository(Protocol):
    """Persistence interface for TraceEvent records — in-memory until backed by Postgres."""

    async def record(self, event: TraceEvent) -> TraceEvent:
        """Persist event and return it."""
        ...

    async def list_for_run(self, run_id: str) -> list[TraceEvent]:
        """Return all recorded trace events for run_id, in recording order."""
        ...


class InMemoryTraceEventRepository:
    """In-memory TraceEventRepository implementation — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._events: list[TraceEvent] = []

    async def record(self, event: TraceEvent) -> TraceEvent:
        """Append event to the in-memory list and return it."""
        self._events.append(event)
        return event

    async def list_for_run(self, run_id: str) -> list[TraceEvent]:
        """Return all recorded trace events for run_id, in recording order."""
        return [event for event in self._events if event.run_id == run_id]
