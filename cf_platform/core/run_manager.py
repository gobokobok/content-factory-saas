"""Run lifecycle manager (P1-S2).

`create_run` mints a `RunRecord` and `transition_run` enforces the
`created -> running -> complete|failed` lifecycle. Persistence sits behind the
`RunRepository` Protocol; `InMemoryRunRepository` is the P1 implementation,
swapped for a Postgres-backed repository in P2-S3 without changing this
module's public interface (D056/D057 — run records are the durable lineage
index, not application state).
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional, Protocol

from cf_platform.core.schemas import RunRecord

RunStatus = Literal["created", "running", "complete", "failed"]

_VALID_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    "created": {"running"},
    "running": {"complete", "failed"},
    "complete": set(),
    "failed": set(),
}


class RunNotFoundError(Exception):
    """Raised when a run_id has no corresponding RunRecord in the repository."""


class InvalidTransitionError(Exception):
    """Raised when a requested status change is not allowed from the run's current status."""


class RunRepository(Protocol):
    """Persistence interface for RunRecord storage — swappable (in-memory now, Postgres in P2-S3)."""

    async def save(self, run: RunRecord) -> RunRecord:
        """Insert or overwrite the RunRecord for run.run_id. Returns the stored record."""
        ...

    async def get(self, run_id: str) -> RunRecord:
        """Return the RunRecord for run_id. Raises RunNotFoundError if absent."""
        ...


class InMemoryRunRepository:
    """In-memory RunRepository implementation — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._runs: dict[str, RunRecord] = {}

    async def save(self, run: RunRecord) -> RunRecord:
        """Insert or overwrite the RunRecord for run.run_id. Returns the stored record."""
        self._runs[run.run_id] = run
        return run

    async def get(self, run_id: str) -> RunRecord:
        """Return the RunRecord for run_id. Raises RunNotFoundError if absent."""
        try:
            return self._runs[run_id]
        except KeyError:
            raise RunNotFoundError(f"Run not found: {run_id}") from None


async def create_run(
    user_id: str,
    block: str,
    inputs: dict[str, Any],
    repository: RunRepository,
) -> RunRecord:
    """Mint a new RunRecord with status 'created', persist it via repository, and return it."""
    now = datetime.now(timezone.utc)
    run = RunRecord(
        run_id=str(uuid.uuid4()),
        user_id=user_id,
        block=block,
        status="created",
        inputs=inputs,
        error=None,
        created_at=now,
        updated_at=now,
    )
    return await repository.save(run)


async def transition_run(
    run_id: str,
    new_status: RunStatus,
    repository: RunRepository,
    error: Optional[str] = None,
) -> RunRecord:
    """Transition the run identified by run_id to new_status and persist the change.

    Raises InvalidTransitionError if new_status is not reachable from the run's
    current status. Raises RunNotFoundError if run_id is unknown to repository.
    """
    run = await repository.get(run_id)
    if new_status not in _VALID_TRANSITIONS[run.status]:
        raise InvalidTransitionError(
            f"Cannot transition run {run_id} from '{run.status}' to '{new_status}'"
        )
    updated = run.model_copy(
        update={
            "status": new_status,
            "error": error,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    return await repository.save(updated)
