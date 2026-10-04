"""Postgres-backed TenantSettingsRepository (Sprint P14, D104).

Persists the `tenant_settings` row defined in
cf_platform/db/migrations/0003_tenant_settings.sql. Drop-in replacement for
InMemoryTenantSettingsRepository, selected in cf_platform/interfaces/dependencies.py
when DATABASE_URL is configured (D048).
"""

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from cf_platform.core.postgres_repos import _ensure_open
from cf_platform.core.tenant_settings import TenantSettings

_COLUMNS = "tenant_id, image_provider, image_model, api_keys, updated_at"


class PostgresTenantSettingsRepository:
    """Upserts into the `tenant_settings` table by `tenant_id`."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Hold the shared connection pool."""
        self._pool = pool

    async def get(self, tenant_id: str) -> TenantSettings | None:
        """Return the tenant's row, or None when nothing was saved yet."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT {_COLUMNS} FROM tenant_settings WHERE tenant_id = %s", (tenant_id,)
                )
                row = await cur.fetchone()
        if row is None:
            return None
        tenant, provider, model, api_keys, updated_at = row
        return TenantSettings(
            tenant_id=tenant, image_provider=provider, image_model=model,
            api_keys=api_keys or {}, updated_at=updated_at,
        )

    async def save(self, settings: TenantSettings) -> TenantSettings:
        """Insert or overwrite the row for settings.tenant_id; returns it."""
        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"""
                    INSERT INTO tenant_settings ({_COLUMNS})
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id) DO UPDATE SET
                        image_provider = EXCLUDED.image_provider,
                        image_model = EXCLUDED.image_model,
                        api_keys = EXCLUDED.api_keys,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        settings.tenant_id, settings.image_provider, settings.image_model,
                        Jsonb(settings.api_keys), settings.updated_at,
                    ),
                )
            await conn.commit()
        return settings
