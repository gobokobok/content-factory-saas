"""Tests for cf_platform/core/db.py — async Postgres connection pool (P2-S1, D048)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cf_platform.core.db as db


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the process-local pool singleton before and after each test."""
    db._pool = None
    yield
    db._pool = None


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
