"""Postgres-backed repositories for Run/Artifact/Execution lineage (P2-S3, D048).

R2 remains the source of truth for artifact bodies; these repositories persist the
queryable index rows defined in `cf_platform/db/migrations/0001_init.sql` (P2-S2):
`runs`, `artifacts`, `worker_executions`. Each implements the Protocol declared
alongside its in-memory counterpart (`RunRepository` in run_manager.py,
`ArtifactRepository` in artifact_manager.py, `ExecutionRepository` in
worker_registry.py) so they are drop-in swappable — selected in
cf_platform/interfaces/api.py when `DATABASE_URL` is configured.

Writes are upserts keyed on each table's natural identity (`run_id` for runs;
`(run_id, stage, name, version)` for artifacts) so re-running a step does not
fail or duplicate rows (D055 — artifacts are immutable per version, so a repeat
write of the same version is a no-op).
"""

from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.run_manager import RunNotFoundError
from cf_platform.core.schemas import Artifact, RunRecord, WorkerExecution


async def _ensure_open(pool: AsyncConnectionPool) -> None:
    """Open pool if it is currently closed (lazy connection, mirrors core/db.py)."""
    if pool.closed:
        await pool.open(wait=False)


class PostgresRunRepository:
    """Postgres-backed RunRepository — upserts into the `runs` table by `run_id`."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def save(self, run: RunRecord) -> RunRecord:
        """Upsert the RunRecord row keyed on run_id. Returns the stored record."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO runs (run_id, user_id, block, status, inputs, error, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        block = EXCLUDED.block,
                        status = EXCLUDED.status,
                        inputs = EXCLUDED.inputs,
                        error = EXCLUDED.error,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        run.run_id,
                        run.user_id,
                        run.block,
                        run.status,
                        Jsonb(run.inputs),
                        run.error,
                        run.created_at,
                        run.updated_at,
                    ),
                )
            await conn.commit()
        return run

    async def get(self, run_id: str) -> RunRecord:
        """Return the RunRecord for run_id. Raises RunNotFoundError if absent."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT run_id, user_id, block, status, inputs, error, created_at, updated_at
                    FROM runs WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = await cur.fetchone()
        if row is None:
            raise RunNotFoundError(f"Run not found: {run_id}")
        run_id_, user_id, block, status, inputs, error, created_at, updated_at = row
        return RunRecord(
            run_id=run_id_,
            user_id=user_id,
            block=block,
            status=status,
            inputs=inputs,
            error=error,
            created_at=created_at,
            updated_at=updated_at,
        )


class PostgresArtifactRepository:
    """Postgres-backed ArtifactRepository — indexes Artifact lineage rows.

    Bodies stay in R2; only `r2_key` + lineage columns are written here, matching
    `cf_platform/db/schema.sql`'s `artifacts` table (D048).
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def record(self, artifact: Artifact) -> None:
        """Insert the lineage index row for artifact. No-op if (run_id, stage, name, version) exists."""
        await _ensure_open(self._pool)
        lineage = artifact.lineage
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO artifacts (
                        run_id, name, stage, version, r2_key, content_type, schema_version,
                        worker, worker_version, prompt_version, model, sampling_params, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, stage, name, version) DO NOTHING
                    """,
                    (
                        artifact.run_id,
                        artifact.name,
                        artifact.stage,
                        artifact.version,
                        artifact.r2_key,
                        artifact.content_type,
                        artifact.schema_version,
                        lineage.worker,
                        lineage.worker_version,
                        lineage.prompt_version,
                        lineage.model,
                        Jsonb(lineage.sampling_params),
                        lineage.created_at,
                    ),
                )
            await conn.commit()


class PostgresExecutionRepository:
    """Postgres-backed ExecutionRepository — appends WorkerExecution rows."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def record(self, execution: WorkerExecution) -> WorkerExecution:
        """Insert a new worker_executions row and return execution unchanged."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO worker_executions (
                        run_id, worker, worker_version, prompt_version, model, sampling_params,
                        input_tokens, output_tokens, cost_usd, latency_ms, status, artifact_r2_key,
                        started_at, finished_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        execution.run_id,
                        execution.worker,
                        execution.worker_version,
                        execution.prompt_version,
                        execution.model,
                        Jsonb(execution.sampling_params),
                        execution.input_tokens,
                        execution.output_tokens,
                        execution.cost_usd,
                        execution.latency_ms,
                        execution.status,
                        execution.artifact_r2_key,
                        execution.started_at,
                        execution.finished_at,
                    ),
                )
            await conn.commit()
        return execution

    async def list_for_run(self, run_id: str) -> list[WorkerExecution]:
        """Return all recorded executions for run_id, ordered by insertion (id)."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT run_id, worker, worker_version, prompt_version, model, sampling_params,
                           input_tokens, output_tokens, cost_usd, latency_ms, status, artifact_r2_key,
                           started_at, finished_at
                    FROM worker_executions WHERE run_id = %s ORDER BY id
                    """,
                    (run_id,),
                )
                rows = await cur.fetchall()
        return [_row_to_execution(row) for row in rows]


def _row_to_execution(row: tuple[Any, ...]) -> WorkerExecution:
    """Map a worker_executions row tuple to a WorkerExecution."""
    (
        run_id,
        worker,
        worker_version,
        prompt_version,
        model,
        sampling_params,
        input_tokens,
        output_tokens,
        cost_usd,
        latency_ms,
        status,
        artifact_r2_key,
        started_at,
        finished_at,
    ) = row
    return WorkerExecution(
        run_id=run_id,
        worker=worker,
        worker_version=worker_version,
        prompt_version=prompt_version,
        model=model,
        sampling_params=sampling_params,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=float(cost_usd),
        latency_ms=latency_ms,
        status=status,
        artifact_r2_key=artifact_r2_key,
        started_at=started_at,
        finished_at=finished_at,
    )
