"""Tests for cf_platform/core/postgres_repos.py — Postgres-backed lineage repos (P2-S3, D048)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
    PostgresTraceEventRepository,
)
from cf_platform.core.run_manager import RunNotFoundError
from cf_platform.core.schemas import Artifact, LineageEnvelope, RunRecord, TraceEvent, WorkerExecution


def _mock_pool(fetchone=None, fetchall=None):
    """Build a MagicMock AsyncConnectionPool whose cursor returns fetchone/fetchall."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = fetchone
    mock_cursor.fetchall.return_value = fetchall or []

    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__aexit__.return_value = None
    mock_conn.commit = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.closed = False
    mock_pool.connection.return_value.__aenter__.return_value = mock_conn
    mock_pool.connection.return_value.__aexit__.return_value = None
    return mock_pool, mock_cursor, mock_conn


def _run_record() -> RunRecord:
    """Build a sample RunRecord for tests."""
    now = datetime.now(UTC)
    return RunRecord(
        run_id="r1",
        user_id="operator",
        block="echo",
        status="running",
        inputs={"text": "hello"},
        error=None,
        created_at=now,
        updated_at=now,
    )


def _artifact() -> Artifact:
    """Build a sample Artifact for tests."""
    now = datetime.now(UTC)
    return Artifact(
        name="echo",
        stage="echo",
        version=1,
        run_id="r1",
        content_type="application/json",
        r2_key="users/operator/runs/r1/echo/echo@v1.json",
        lineage=LineageEnvelope(
            run_id="r1",
            worker="echo",
            worker_version="1.0.0",
            prompt_version="v1",
            model="claude-haiku-4-5-20251001",
            sampling_params={"temperature": 0.0},
            created_at=now,
        ),
    )


def _execution() -> WorkerExecution:
    """Build a sample WorkerExecution for tests."""
    now = datetime.now(UTC)
    return WorkerExecution(
        run_id="r1",
        worker="echo",
        worker_version="1.0.0",
        prompt_version="v1",
        model="claude-haiku-4-5-20251001",
        sampling_params={"temperature": 0.0},
        status="ok",
        artifact_r2_key="users/operator/runs/r1/echo/echo@v1.json",
        started_at=now,
        finished_at=now,
    )


class TestPostgresRunRepository:
    @pytest.mark.asyncio
    async def test_save_upserts_run_row(self):
        """save() issues an INSERT .. ON CONFLICT (run_id) DO UPDATE and returns the record."""
        pool, cursor, conn = _mock_pool()
        repo = PostgresRunRepository(pool)
        run = _run_record()

        result = await repo.save(run)

        assert result == run
        cursor.execute.assert_awaited_once()
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO runs" in sql
        assert "ON CONFLICT (run_id) DO UPDATE" in sql
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_returns_run_record(self):
        """get() maps a found row back into a RunRecord."""
        run = _run_record()
        row = (run.run_id, run.user_id, run.block, run.status, run.inputs, run.error, run.created_at, run.updated_at)
        pool, cursor, _ = _mock_pool(fetchone=row)
        repo = PostgresRunRepository(pool)

        result = await repo.get("r1")

        assert result == run

    @pytest.mark.asyncio
    async def test_get_missing_run_raises(self):
        """get() raises RunNotFoundError when no row matches run_id."""
        pool, _, _ = _mock_pool(fetchone=None)
        repo = PostgresRunRepository(pool)

        with pytest.raises(RunNotFoundError):
            await repo.get("missing")

    @pytest.mark.asyncio
    async def test_list_runs_maps_rows_to_records(self):
        """list_runs() maps runs rows back into RunRecord models, ordered by created_at desc."""
        run = _run_record()
        row = (run.run_id, run.user_id, run.block, run.status, run.inputs, run.error, run.created_at, run.updated_at)
        pool, cursor, _ = _mock_pool(fetchall=[row])
        repo = PostgresRunRepository(pool)

        result = await repo.list_runs()

        assert result == [run]
        sql = cursor.execute.call_args[0][0]
        assert "FROM runs" in sql
        assert "ORDER BY created_at DESC" in sql

    @pytest.mark.asyncio
    async def test_list_runs_empty_when_no_rows(self):
        """list_runs() returns an empty list when no rows exist."""
        pool, _, _ = _mock_pool(fetchall=[])
        repo = PostgresRunRepository(pool)

        result = await repo.list_runs()

        assert result == []


class TestPostgresArtifactRepository:
    @pytest.mark.asyncio
    async def test_record_inserts_lineage_row(self):
        """record() issues an INSERT .. ON CONFLICT DO NOTHING keyed on (run_id, stage, name, version)."""
        pool, cursor, conn = _mock_pool()
        repo = PostgresArtifactRepository(pool)
        artifact = _artifact()

        await repo.record(artifact)

        cursor.execute.assert_awaited_once()
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO artifacts" in sql
        assert "ON CONFLICT (run_id, stage, name, version) DO NOTHING" in sql
        assert artifact.r2_key in params
        assert artifact.lineage.worker in params
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_for_run_maps_rows_to_artifacts(self):
        """list_for_run() maps artifacts rows back into Artifact models with lineage."""
        artifact = _artifact()
        lineage = artifact.lineage
        row = (
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
            lineage.sampling_params,
            lineage.created_at,
        )
        pool, cursor, _ = _mock_pool(fetchall=[row])
        repo = PostgresArtifactRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == [artifact]
        sql = cursor.execute.call_args[0][0]
        assert "FROM artifacts" in sql
        assert "ORDER BY stage, name, version" in sql

    @pytest.mark.asyncio
    async def test_list_for_run_empty_when_no_rows(self):
        """list_for_run() returns an empty list when no rows match run_id."""
        pool, _, _ = _mock_pool(fetchall=[])
        repo = PostgresArtifactRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == []


class TestPostgresExecutionRepository:
    @pytest.mark.asyncio
    async def test_record_inserts_execution_row(self):
        """record() issues an INSERT into worker_executions and returns the execution unchanged."""
        pool, cursor, conn = _mock_pool()
        repo = PostgresExecutionRepository(pool)
        execution = _execution()

        result = await repo.record(execution)

        assert result == execution
        cursor.execute.assert_awaited_once()
        sql = cursor.execute.call_args[0][0]
        assert "INSERT INTO worker_executions" in sql
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_for_run_maps_rows_to_executions(self):
        """list_for_run() maps worker_executions rows back into WorkerExecution models."""
        execution = _execution()
        row = (
            execution.run_id,
            execution.worker,
            execution.worker_version,
            execution.prompt_version,
            execution.model,
            execution.sampling_params,
            execution.input_tokens,
            execution.output_tokens,
            execution.cost_usd,
            execution.latency_ms,
            execution.status,
            execution.artifact_r2_key,
            execution.started_at,
            execution.finished_at,
        )
        pool, cursor, _ = _mock_pool(fetchall=[row])
        repo = PostgresExecutionRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == [execution]

    @pytest.mark.asyncio
    async def test_list_for_run_empty_when_no_rows(self):
        """list_for_run() returns an empty list when no rows match run_id."""
        pool, _, _ = _mock_pool(fetchall=[])
        repo = PostgresExecutionRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == []


def _trace_event() -> TraceEvent:
    """Build a sample TraceEvent for tests."""
    return TraceEvent(
        run_id="r1",
        worker="discovery",
        source="reddit",
        op="fetch",
        latency_ms=123,
        cost_usd=None,
        status="ok",
        meta={"signal_count": 5},
    )


class TestPostgresTraceEventRepository:
    @pytest.mark.asyncio
    async def test_record_inserts_trace_event_row(self):
        """record() issues an INSERT into trace_events and returns the event unchanged."""
        pool, cursor, conn = _mock_pool()
        repo = PostgresTraceEventRepository(pool)
        event = _trace_event()

        result = await repo.record(event)

        assert result == event
        cursor.execute.assert_awaited_once()
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO trace_events" in sql
        assert event.run_id in params
        assert event.source in params
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_for_run_maps_rows_to_trace_events(self):
        """list_for_run() maps trace_events rows back into TraceEvent models, ordered by id."""
        event = _trace_event()
        row = (
            event.run_id,
            event.worker,
            event.source,
            event.op,
            event.latency_ms,
            event.cost_usd,
            event.status,
            event.meta,
        )
        pool, cursor, _ = _mock_pool(fetchall=[row])
        repo = PostgresTraceEventRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == [event]
        sql = cursor.execute.call_args[0][0]
        assert "FROM trace_events" in sql
        assert "ORDER BY id" in sql

    @pytest.mark.asyncio
    async def test_list_for_run_empty_when_no_rows(self):
        """list_for_run() returns an empty list when no rows match run_id."""
        pool, _, _ = _mock_pool(fetchall=[])
        repo = PostgresTraceEventRepository(pool)

        result = await repo.list_for_run("r1")

        assert result == []


class TestPoolLazyOpen:
    @pytest.mark.asyncio
    async def test_save_opens_closed_pool(self):
        """A closed pool is opened before use, mirroring core/db.py's lazy-open pattern."""
        pool, _, _ = _mock_pool()
        pool.closed = True
        pool.open = AsyncMock()
        repo = PostgresRunRepository(pool)

        await repo.save(_run_record())

        pool.open.assert_awaited_once_with(wait=False)
