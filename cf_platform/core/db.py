"""Async Postgres connection pool for cf_platform (P2-S1, D048).

R2 remains the source of truth for artifact bodies; Postgres is the metadata
index (D048). The pool is fault-isolated: a missing DATABASE_URL or a DB
outage must never raise into callers — /platform/health and any other
platform route must keep working when the database is unavailable.
"""

import logging
from typing import Optional

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)

_pool: Optional[AsyncConnectionPool] = None


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
