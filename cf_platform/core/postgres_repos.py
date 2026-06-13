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
from cf_platform.core.schemas import Artifact, LineageEnvelope, RunRecord, TraceEvent, WorkerExecution


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

    async def list_runs(self) -> list[RunRecord]:
        """Return all RunRecords, most recently created first."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT run_id, user_id, block, status, inputs, error, created_at, updated_at
                    FROM runs ORDER BY created_at DESC
                    """
                )
                rows = await cur.fetchall()
        return [
            RunRecord(
                run_id=run_id_,
                user_id=user_id,
                block=block,
                status=status,
                inputs=inputs,
                error=error,
                created_at=created_at,
                updated_at=updated_at,
            )
            for run_id_, user_id, block, status, inputs, error, created_at, updated_at in rows
        ]


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

    async def list_for_run(self, run_id: str) -> list[Artifact]:
        """Return all recorded artifacts for run_id, ordered by stage, name, version."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT run_id, name, stage, version, r2_key, content_type, schema_version,
                           worker, worker_version, prompt_version, model, sampling_params, created_at
                    FROM artifacts WHERE run_id = %s ORDER BY stage, name, version
                    """,
                    (run_id,),
                )
                rows = await cur.fetchall()
        return [_row_to_artifact(row) for row in rows]


def _row_to_artifact(row: tuple[Any, ...]) -> Artifact:
    """Map an artifacts row tuple to an Artifact."""
    (
        run_id,
        name,
        stage,
        version,
        r2_key,
        content_type,
        schema_version,
        worker,
        worker_version,
        prompt_version,
        model,
        sampling_params,
        created_at,
    ) = row
    return Artifact(
        name=name,
        stage=stage,
        version=version,
        run_id=run_id,
        content_type=content_type,
        r2_key=r2_key,
        schema_version=schema_version,
        lineage=LineageEnvelope(
            run_id=run_id,
            worker=worker,
            worker_version=worker_version,
            prompt_version=prompt_version,
            model=model,
            sampling_params=sampling_params,
            created_at=created_at,
        ),
    )


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


class PostgresTraceEventRepository:
    """Postgres-backed TraceEventRepository — appends TraceEvent rows (D050)."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def record(self, event: TraceEvent) -> TraceEvent:
        """Insert a new trace_events row and return event unchanged."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO trace_events (run_id, worker, source, op, latency_ms, cost_usd, status, meta)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event.run_id,
                        event.worker,
                        event.source,
                        event.op,
                        event.latency_ms,
                        event.cost_usd,
                        event.status,
                        Jsonb(event.meta),
                    ),
                )
            await conn.commit()
        return event

    async def list_for_run(self, run_id: str) -> list[TraceEvent]:
        """Return all recorded trace events for run_id, ordered by insertion (id)."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT run_id, worker, source, op, latency_ms, cost_usd, status, meta
                    FROM trace_events WHERE run_id = %s ORDER BY id
                    """,
                    (run_id,),
                )
                rows = await cur.fetchall()
        return [
            TraceEvent(
                run_id=run_id_,
                worker=worker,
                source=source,
                op=op,
                latency_ms=latency_ms,
                cost_usd=float(cost_usd) if cost_usd is not None else None,
                status=status,
                meta=meta,
            )
            for run_id_, worker, source, op, latency_ms, cost_usd, status, meta in rows
        ]


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
