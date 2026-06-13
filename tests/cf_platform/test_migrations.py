"""Tests for cf_platform/core/migrations.py — SQL migration runner (P2-S2, D048)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cf_platform.core.db as db
import cf_platform.core.migrations as migrations


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the process-local pool singleton before and after each test."""
    db._pool = None
    yield
    db._pool = None


class TestListMigrations:
    def test_returns_sorted_sql_files(self):
        """list_migrations returns the migration files in filename order."""
        files = migrations.list_migrations()

        assert [f.name for f in files] == sorted(f.name for f in files)
        assert "0001_init.sql" in [f.name for f in files]


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_unavailable_when_database_url_unset(self):
        """run_migrations returns 'unavailable' when DATABASE_URL is empty."""
        result = await migrations.run_migrations("")

        assert result == "unavailable"

    @pytest.mark.asyncio
    async def test_applies_pending_migration_and_records_it(self):
        """run_migrations applies an unapplied migration and inserts a schema_migrations row."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = []  # no migrations applied yet

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__aexit__.return_value = None
        mock_conn.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn
        mock_pool.connection.return_value.__aexit__.return_value = None

        with patch.object(migrations, "get_pool", return_value=mock_pool):
            result = await migrations.run_migrations("postgresql://user:pass@localhost/db")

        assert result == "ok"
        mock_conn.commit.assert_awaited_once()

        # First execute creates schema_migrations, second selects applied versions,
        # then one execute per pending migration's SQL + one INSERT per migration.
        executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert "CREATE TABLE IF NOT EXISTS schema_migrations" in executed_sql[0]
        assert executed_sql[1] == "SELECT version FROM schema_migrations"

        num_migrations = len(migrations.list_migrations())
        assert len(executed_sql) == 2 + num_migrations * 2

        inserted_versions = [
            call.args[1][0]
            for call in mock_cursor.execute.call_args_list
            if call.args[0] == "INSERT INTO schema_migrations (version) VALUES (%s)"
        ]
        assert inserted_versions == [f.name for f in migrations.list_migrations()]

    @pytest.mark.asyncio
    async def test_skips_already_applied_migration(self):
        """run_migrations does not re-run a migration whose version is already recorded."""
        applied_versions = [(f.name,) for f in migrations.list_migrations()]

        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = applied_versions

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__aexit__.return_value = None
        mock_conn.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn
        mock_pool.connection.return_value.__aexit__.return_value = None

        with patch.object(migrations, "get_pool", return_value=mock_pool):
            result = await migrations.run_migrations("postgresql://user:pass@localhost/db")

        assert result == "ok"

        # Only the schema_migrations CREATE + SELECT — no migration SQL/INSERTs run.
        executed_sql = [call.args[0] for call in mock_cursor.execute.call_args_list]
        assert len(executed_sql) == 2

    @pytest.mark.asyncio
    async def test_unavailable_path_never_raises_and_error_path_never_raises(self):
        """run_migrations returns 'error' (never raises) when the connection fails."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.connection.side_effect = RuntimeError("connection refused")

        with patch.object(migrations, "get_pool", return_value=mock_pool):
            result = await migrations.run_migrations("postgresql://user:pass@localhost/db")

        assert result == "error"

    @pytest.mark.asyncio
    async def test_opens_pool_when_closed(self):
        """run_migrations opens a closed pool before attempting a connection."""
        mock_cursor = AsyncMock()
        mock_cursor.fetchall.return_value = [(f.name,) for f in migrations.list_migrations()]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__aexit__.return_value = None
        mock_conn.commit = AsyncMock()

        mock_pool = MagicMock()
        mock_pool.closed = True
        mock_pool.open = AsyncMock()
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn
        mock_pool.connection.return_value.__aexit__.return_value = None

        with patch.object(migrations, "get_pool", return_value=mock_pool):
            result = await migrations.run_migrations("postgresql://user:pass@localhost/db")

        assert result == "ok"
        mock_pool.open.assert_awaited_once_with(wait=False)
