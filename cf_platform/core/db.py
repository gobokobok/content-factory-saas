"""Async Postgres connection pool for cf_platform (P2-S1, D048).

R2 remains the source of truth for artifact bodies; Postgres is the metadata
index (D048). The pool is fault-isolated: a missing DATABASE_URL or a DB
outage must never raise into callers — /platform/health and any other
platform route must keep working when the database is unavailable.
"""

import logging
from typing import Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None
_checkpoint_pool: Optional[AsyncConnectionPool] = None


def get_pool(database_url: str) -> Optional[AsyncConnectionPool]:
    """Return the process-local AsyncConnectionPool for database_url, or None if unset.

    The pool is created with open=False so an unreachable database does not raise
    at construction time; connections are attempted lazily on first use.
    """
    global _pool
    if not database_url:
        return None
    if _pool is None:
        _pool = AsyncConnectionPool(conninfo=database_url, open=False)
    return _pool


async def check_db_health(database_url: str) -> str:
    """Return "ok" if a SELECT 1 succeeds against database_url, else "unavailable".

    Never raises — a missing DATABASE_URL or any connection error is reported as
    "unavailable" so the platform health check stays fault-isolated (D048).
    """
    pool = get_pool(database_url)
    if pool is None:
        return "unavailable"
    try:
        if pool.closed:
            await pool.open(wait=False)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        return "ok"
    except Exception:
        logger.exception("Postgres health check failed")
        return "unavailable"


def get_checkpointer(database_url: str) -> BaseCheckpointSaver:
    """Return a LangGraph checkpointer for database_url (P2-S4, D052).

    A missing database_url degrades to an in-memory MemorySaver — graphs still
    run, but checkpoints do not survive a process restart (D048 fault isolation:
    DB down/unset != platform down). When database_url is set, returns an
    AsyncPostgresSaver backed by a dedicated connection pool (separate from
    get_pool's health-check pool), configured with autocommit + dict rows as
    required by AsyncPostgresSaver.

    Must be called from within a running event loop when database_url is set —
    AsyncPostgresSaver.__init__ calls asyncio.get_running_loop().
    """
    global _checkpoint_pool
    if not database_url:
        return MemorySaver()
    if _checkpoint_pool is None:
        _checkpoint_pool = AsyncConnectionPool(
            conninfo=database_url,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
    return AsyncPostgresSaver(_checkpoint_pool)


async def setup_checkpointer(checkpointer: BaseCheckpointSaver) -> str:
    """Create the checkpoint tables for checkpointer if needed. Returns "ok" or "unavailable".

    Never raises (D048 fault isolation, mirrors check_db_health). A MemorySaver
    needs no setup and always reports "ok". For an AsyncPostgresSaver, opens its
    pool if closed and runs setup() (idempotent — applies pending migrations only).
    """
    if not isinstance(checkpointer, AsyncPostgresSaver):
        return "ok"
    try:
        pool = checkpointer.conn
        if isinstance(pool, AsyncConnectionPool) and pool.closed:
            await pool.open(wait=False)
        await checkpointer.setup()
        return "ok"
    except Exception:
        logger.exception("Checkpointer setup failed")
        return "unavailable"
