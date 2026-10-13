"""Raw-SQL migration runner for cf_platform's Postgres metadata index (P2-S2, D048).

Migrations are numbered SQL files in cf_platform/db/migrations/, applied in filename
order and recorded in a schema_migrations tracking table. Each migration file is
idempotent (CREATE TABLE/INDEX IF NOT EXISTS), and already-applied migrations are
skipped, so run_migrations is safe to call on every startup.

Fault-isolated like cf_platform/core/db.py: a missing DATABASE_URL or any database
error is logged and reported via the return value — never raised — so platform
startup never fails because of the metadata index (D048's "DB outage != legacy down").
"""

import logging
from pathlib import Path

from cf_platform.core.db import get_pool

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"

# Arbitrary constant: two instances starting together (a deploy overlap) queue on this
# Postgres advisory lock instead of applying the same migration twice (F11).
MIGRATION_LOCK_KEY = 7_041_302_001

# What the last run_migrations call in this process returned: "not_run" before start-up
# finishes, then "ok" | "unavailable" | "error". /health reports it (F11).
_last_status = "not_run"


def get_migration_status() -> str:
    """Return the result of this process's start-up migration run, or "not_run"."""
    return _last_status


def list_migrations() -> list[Path]:
    """Return all migration SQL files in cf_platform/db/migrations, sorted by filename."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def run_migrations(database_url: str) -> str:
    """Apply all pending migrations in cf_platform/db/migrations, in filename order.

    Returns "ok" if all pending migrations applied successfully (or none were
    pending), "unavailable" if database_url is empty, "error" if a connection or
    migration failure occurred. Never raises (D048 fault isolation).
    """
    global _last_status
    _last_status = await _apply_migrations(database_url)
    return _last_status


async def _apply_migrations(database_url: str) -> str:
    """Apply pending migrations under an advisory lock and return the status string."""
    pool = get_pool(database_url)
    if pool is None:
        return "unavailable"

    try:
        if pool.closed:
            await pool.open(wait=False)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Transaction-level: released by the commit below (or a rollback).
                await cur.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_KEY,))
                await cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version TEXT PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                await cur.execute("SELECT version FROM schema_migrations")
                applied = {row[0] for row in await cur.fetchall()}

                for migration_file in list_migrations():
                    if migration_file.name in applied:
                        continue
                    await cur.execute(migration_file.read_text())
                    await cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (migration_file.name,),
                    )
            await conn.commit()
        return "ok"
    except Exception:
        logger.exception("cf_platform migration run failed")
        return "error"
