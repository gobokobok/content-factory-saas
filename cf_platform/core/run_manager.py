"""Run lifecycle manager (P1-S2).

`create_run` mints a `RunRecord` and `transition_run` enforces the
`created -> running -> complete|failed` lifecycle. Persistence sits behind the
`RunRepository` Protocol; `InMemoryRunRepository` is the P1 implementation,
swapped for a Postgres-backed repository in P2-S3 without changing this
module's public interface (D056/D057 — run records are the durable lineage
index, not application state).
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from cf_platform.core.accounts import default_project_id
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

    async def get(self, run_id: str, tenant_id: str | None = None) -> RunRecord:
        """Return the RunRecord for run_id. Raises RunNotFoundError if absent.

        With tenant_id, a run of another tenant is "absent" too (P-AUTH, F2).
        """
        ...

    async def list_runs(self, tenant_id: str | None = None) -> list[RunRecord]:
        """Return RunRecords (only tenant_id's when given), most recently created first."""
        ...

    async def list_for_project(self, project_id: str, tenant_id: str | None = None) -> list[RunRecord]:
        """Return project_id's non-archived RunRecords (only tenant_id's when given), newest first."""
        ...

    async def count_by_project(self, tenant_id: str | None = None) -> dict[str, int]:
        """Return {project_id: non-archived run count} (only tenant_id's runs when given)."""
        ...

    async def count_created_since(self, tenant_id: str, since: datetime) -> int:
        """Return how many runs tenant_id created at or after since (the daily run cap, S8)."""
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

    async def get(self, run_id: str, tenant_id: str | None = None) -> RunRecord:
        """Return the RunRecord for run_id. Raises RunNotFoundError if absent or another tenant's."""
        run = self._runs.get(run_id)
        if run is None or (tenant_id is not None and (run.tenant_id or run.user_id) != tenant_id):
            raise RunNotFoundError(f"Run not found: {run_id}")
        return run

    async def list_runs(self, tenant_id: str | None = None) -> list[RunRecord]:
        """Return RunRecords (only tenant_id's when given), most recently created first."""
        runs = [
            run for run in self._runs.values()
            if tenant_id is None or (run.tenant_id or run.user_id) == tenant_id
        ]
        return sorted(runs, key=lambda run: run.created_at, reverse=True)

    async def list_for_project(self, project_id: str, tenant_id: str | None = None) -> list[RunRecord]:
        """Return project_id's non-archived RunRecords (only tenant_id's when given), newest first."""
        return [
            run
            for run in await self.list_runs(tenant_id)
            if run.project_id == project_id and run.archived_at is None
        ]

    async def count_by_project(self, tenant_id: str | None = None) -> dict[str, int]:
        """Return {project_id: non-archived run count} (only tenant_id's runs when given)."""
        counts: dict[str, int] = {}
        for run in await self.list_runs(tenant_id):
            if run.archived_at is None:
                counts[run.project_id] = counts.get(run.project_id, 0) + 1
        return counts

    async def count_created_since(self, tenant_id: str, since: datetime) -> int:
        """Return how many runs tenant_id created at or after since."""
        return sum(1 for run in await self.list_runs(tenant_id) if run.created_at >= since)


async def create_run(
    user_id: str,
    block: str,
    inputs: dict[str, Any],
    repository: RunRepository,
    *,
    project_id: str | None = None,
    name: str = "",
    run_id: str | None = None,
) -> RunRecord:
    """Mint a new RunRecord with status 'created', persist it via repository, and return it.

    Every run belongs to a project (D092): `project_id` defaults to the tenant's
    default project (the owner's legacy one, or the hidden personal one) and an
    empty value raises ValueError. `run_id` is minted when not
    given; passing one registers a run whose id already exists elsewhere (a
    Studio run known only to a browser's local history).
    """
    if project_id is None:
        project_id = default_project_id(user_id)
    if not project_id:
        raise ValueError("A run cannot be created without a project_id")
    now = datetime.now(UTC)
    run = RunRecord(
        run_id=run_id or str(uuid.uuid4()),
        user_id=user_id,
        block=block,
        status="created",
        inputs=inputs,
        error=None,
        created_at=now,
        updated_at=now,
        tenant_id=user_id,
        project_id=project_id,
        name=name,
    )
    return await repository.save(run)


async def register_existing_run(
    run_id: str,
    user_id: str,
    project_id: str,
    repository: RunRepository,
    *,
    name: str = "",
    created_at: datetime | None = None,
) -> tuple[RunRecord, bool]:
    """Give a run that already exists in R2 a row in project_id. Returns (record, created).

    Studio used to mint run ids in the browser and never wrote a `runs` row for a
    pasted-script run, so those runs were visible only in that browser's local
    history. This registers one. A run_id that already has a row is returned
    untouched with created=False — an import never moves a run between projects.
    """
    try:
        return await repository.get(run_id), False
    except RunNotFoundError:
        pass
    now = datetime.now(UTC)
    run = RunRecord(
        run_id=run_id,
        user_id=user_id,
        block="studio",
        status="created",
        inputs={},
        error=None,
        created_at=created_at or now,
        updated_at=now,
        tenant_id=user_id,
        project_id=project_id,
        name=name,
    )
    return await repository.save(run), True


async def archive_run(run_id: str, repository: RunRepository) -> RunRecord:
    """Mark the run archived so it drops out of its project's run list. Idempotent.

    Raises RunNotFoundError if run_id is unknown to repository.
    """
    run = await repository.get(run_id)
    if run.archived_at is not None:
        return run
    now = datetime.now(UTC)
    return await repository.save(run.model_copy(update={"archived_at": now, "updated_at": now}))


async def transition_run(
    run_id: str,
    new_status: RunStatus,
    repository: RunRepository,
    error: str | None = None,
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
            "updated_at": datetime.now(UTC),
        }
    )
    return await repository.save(updated)
