"""Tests for cf_platform/core/db.py — async Postgres connection pool (P2-S1, D048)
and LangGraph checkpointer (P2-S4, D052)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

import cf_platform.core.db as db


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the process-local pool singletons before and after each test."""
    db._pool = None
    db._checkpoint_pool = None
    yield
    db._pool = None
    db._checkpoint_pool = None


class TestGetPool:
    def test_returns_none_when_database_url_unset(self):
        """get_pool returns None when database_url is empty (DATABASE_URL unset)."""
        assert db.get_pool("") is None

    def test_returns_pool_when_database_url_set(self):
        """get_pool returns an AsyncConnectionPool when database_url is provided."""
        pool = db.get_pool("postgresql://user:pass@localhost/db")

        assert pool is not None
        assert pool.closed

    def test_returns_same_pool_instance_on_repeat_calls(self):
        """get_pool returns the same process-local pool instance across calls."""
        first = db.get_pool("postgresql://user:pass@localhost/db")
        second = db.get_pool("postgresql://user:pass@localhost/db")

        assert first is second


class TestCheckDbHealth:
    @pytest.mark.asyncio
    async def test_unavailable_when_database_url_unset(self):
        """check_db_health returns 'unavailable' when DATABASE_URL is empty."""
        result = await db.check_db_health("")

        assert result == "unavailable"

    @pytest.mark.asyncio
    async def test_ok_when_select_1_succeeds(self):
        """check_db_health returns 'ok' when SELECT 1 succeeds against the pool."""
        mock_cursor = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn
        mock_pool.connection.return_value.__aexit__.return_value = None

        with patch.object(db, "get_pool", return_value=mock_pool):
            result = await db.check_db_health("postgresql://user:pass@localhost/db")

        assert result == "ok"
        mock_cursor.execute.assert_awaited_once_with("SELECT 1")

    @pytest.mark.asyncio
    async def test_unavailable_when_connection_fails(self):
        """check_db_health returns 'unavailable' (never raises) when the pool connection errors."""
        mock_pool = MagicMock()
        mock_pool.closed = False
        mock_pool.connection.side_effect = RuntimeError("connection refused")

        with patch.object(db, "get_pool", return_value=mock_pool):
            result = await db.check_db_health("postgresql://user:pass@localhost/db")

        assert result == "unavailable"

    @pytest.mark.asyncio
    async def test_opens_pool_when_closed(self):
        """check_db_health opens a closed pool before attempting a connection."""
        mock_cursor = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cursor
        mock_conn.cursor.return_value.__aexit__.return_value = None

        mock_pool = MagicMock()
        mock_pool.closed = True
        mock_pool.open = AsyncMock()
        mock_pool.connection.return_value.__aenter__.return_value = mock_conn
        mock_pool.connection.return_value.__aexit__.return_value = None

        with patch.object(db, "get_pool", return_value=mock_pool):
            result = await db.check_db_health("postgresql://user:pass@localhost/db")

        assert result == "ok"
        mock_pool.open.assert_awaited_once_with(wait=False)


class TestGetCheckpointer:
    def test_returns_memory_saver_when_database_url_unset(self):
        """get_checkpointer returns a MemorySaver when database_url is empty."""
        checkpointer = db.get_checkpointer("")

        assert isinstance(checkpointer, MemorySaver)

    @pytest.mark.asyncio
    async def test_returns_postgres_saver_when_database_url_set(self):
        """get_checkpointer returns an AsyncPostgresSaver when database_url is provided."""
        checkpointer = db.get_checkpointer("postgresql://user:pass@localhost/db")

        assert isinstance(checkpointer, AsyncPostgresSaver)

    @pytest.mark.asyncio
    async def test_checkpoint_pool_configured_with_autocommit_and_dict_row(self):
        """get_checkpointer's dedicated pool is opened with autocommit + dict_row."""
        from psycopg.rows import dict_row

        db.get_checkpointer("postgresql://user:pass@localhost/db")

        assert db._checkpoint_pool is not None
        assert db._checkpoint_pool.closed
        assert db._checkpoint_pool.kwargs["autocommit"] is True
        assert db._checkpoint_pool.kwargs["row_factory"] is dict_row

    @pytest.mark.asyncio
    async def test_returns_saver_backed_by_same_pool_instance_on_repeat_calls(self):
        """get_checkpointer reuses the same checkpoint pool across calls (separate from get_pool)."""
        first = db.get_checkpointer("postgresql://user:pass@localhost/db")
        second = db.get_checkpointer("postgresql://user:pass@localhost/db")

        assert first.conn is second.conn
        assert db._pool is None


class TestSetupCheckpointer:
    @pytest.mark.asyncio
    async def test_ok_for_memory_saver_without_setup(self):
        """setup_checkpointer returns 'ok' for a MemorySaver without calling setup()."""
        result = await db.setup_checkpointer(MemorySaver())

        assert result == "ok"

    @pytest.mark.asyncio
    async def test_ok_when_postgres_saver_setup_succeeds(self):
        """setup_checkpointer returns 'ok' when AsyncPostgresSaver.setup() succeeds."""
        mock_pool = MagicMock(spec=AsyncConnectionPool)
        mock_pool.closed = False
        checkpointer = AsyncPostgresSaver(mock_pool)
        checkpointer.setup = AsyncMock()

        result = await db.setup_checkpointer(checkpointer)

        assert result == "ok"
        checkpointer.setup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_opens_pool_when_closed(self):
        """setup_checkpointer opens a closed checkpoint pool before calling setup()."""
        mock_pool = MagicMock(spec=AsyncConnectionPool)
        mock_pool.closed = True
        mock_pool.open = AsyncMock()
        checkpointer = AsyncPostgresSaver(mock_pool)
        checkpointer.setup = AsyncMock()

        result = await db.setup_checkpointer(checkpointer)

        assert result == "ok"
        mock_pool.open.assert_awaited_once_with(wait=False)
        checkpointer.setup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unavailable_when_setup_raises(self):
        """setup_checkpointer returns 'unavailable' (never raises) when setup() errors."""
        mock_pool = MagicMock(spec=AsyncConnectionPool)
        mock_pool.closed = False
        checkpointer = AsyncPostgresSaver(mock_pool)
        checkpointer.setup = AsyncMock(side_effect=RuntimeError("connection refused"))

        result = await db.setup_checkpointer(checkpointer)

        assert result == "unavailable"
