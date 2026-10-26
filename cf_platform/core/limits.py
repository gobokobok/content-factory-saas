"""Server-side caps and the interim per-tenant cost bound (Sprint P-AUTH S8, F4, F8).

Until the credit ledger (P-BILL-1) a stranger's use of the owner's provider keys is
bounded by numbers the *server* checks — never only the page:

* text length caps (script words, prompt, style, character description);
* runs per UTC day;
* a per-tenant daily spend row, checked and reserved **before** every paid call
  (LLM, TTS, image, prompt rewrite, render), so the check cannot be raced past by
  starting several calls at once;
* renders running at once per tenant;
* uploaded bytes per tenant.

The owner's tenant is exempt (it pays for itself and has per-run caps); every other
tenant — Basic or Super — is bound. The spend figure is an *estimate* reserved at
call time, not billing: a call that then fails still counted. That errs toward
stopping early, which is the safe side for a bound.

Routes call the module functions (``await spend_gate(...)``) — they resolve the
caller from the request principal, so no route signature changes.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Protocol

from fastapi import HTTPException

from cf_platform.core.accounts import OWNER_TENANT_ID, NotAuthenticatedError, current_principal
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import get_pool

# Storage quota rows are not per day; they live on this fixed date.
_STORAGE_DAY = date(2000, 1, 1)


class UsageStore(Protocol):
    """Per-tenant, per-day usage counters."""

    async def reserve_spend(self, tenant_id: str, day: date, usd: float, cap_usd: float) -> tuple[bool, float]:
        """Add usd to the day's spend unless that would pass cap_usd. Returns (ok, spend after / before)."""
        ...

    async def release_spend(self, tenant_id: str, day: date, usd: float) -> float:
        """Take usd back off the day's spend, never below zero. Returns the spend after."""
        ...

    async def spend_today(self, tenant_id: str, day: date) -> float:
        """The dollars reserved for tenant_id on day."""
        ...

    async def reserve_bytes(self, tenant_id: str, n: int, cap_bytes: int) -> tuple[bool, int]:
        """Add n uploaded bytes unless that would pass cap_bytes. Returns (ok, total)."""
        ...

    async def count_render(self, tenant_id: str, day: date) -> None:
        """Count one render for tenant_id on day (reporting)."""
        ...


class InMemoryUsageStore:
    """In-memory UsageStore — process-local; the local-development fallback (D048)."""

    def __init__(self) -> None:
        """Start empty."""
        self._spend: dict[tuple[str, date], float] = {}
        self._bytes: dict[str, int] = {}
        self._renders: dict[tuple[str, date], int] = {}

    async def reserve_spend(self, tenant_id: str, day: date, usd: float, cap_usd: float) -> tuple[bool, float]:
        """Add usd to the day's spend unless that would pass cap_usd."""
        current = self._spend.get((tenant_id, day), 0.0)
        if current + usd > cap_usd + 1e-9:
            return False, current
        self._spend[(tenant_id, day)] = current + usd
        return True, current + usd

    async def release_spend(self, tenant_id: str, day: date, usd: float) -> float:
        """Take usd back off the day's spend, never below zero."""
        after = max(self._spend.get((tenant_id, day), 0.0) - usd, 0.0)
        self._spend[(tenant_id, day)] = after
        return after

    async def spend_today(self, tenant_id: str, day: date) -> float:
        """The dollars reserved for tenant_id on day."""
        return self._spend.get((tenant_id, day), 0.0)

    async def reserve_bytes(self, tenant_id: str, n: int, cap_bytes: int) -> tuple[bool, int]:
        """Add n uploaded bytes unless that would pass cap_bytes."""
        total = self._bytes.get(tenant_id, 0)
        if total + n > cap_bytes:
            return False, total
        self._bytes[tenant_id] = total + n
        return True, total + n

    async def count_render(self, tenant_id: str, day: date) -> None:
        """Count one render for tenant_id on day."""
        self._renders[(tenant_id, day)] = self._renders.get((tenant_id, day), 0) + 1


class PostgresUsageStore:
    """UsageStore on the ``tenant_usage`` table (migration 0005) — conditional upserts, race-safe."""

    def __init__(self, pool) -> None:
        """Store the shared connection pool."""
        self._pool = pool

    async def _one(self, sql: str, params: tuple) -> tuple | None:
        """Run a statement, commit, and return its first row (or None)."""
        from cf_platform.core.postgres_repos import _ensure_open

        await _ensure_open(self._pool)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                row = await cur.fetchone() if cur.description else None
            await conn.commit()
        return row

    async def reserve_spend(self, tenant_id: str, day: date, usd: float, cap_usd: float) -> tuple[bool, float]:
        """Add usd to the day's spend unless that would pass cap_usd (one atomic statement)."""
        if usd > cap_usd + 1e-9:
            return False, await self.spend_today(tenant_id, day)
        row = await self._one(
            """
            INSERT INTO tenant_usage (tenant_id, day, spend_usd) VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, day) DO UPDATE
               SET spend_usd = tenant_usage.spend_usd + EXCLUDED.spend_usd, updated_at = now()
               WHERE tenant_usage.spend_usd + EXCLUDED.spend_usd <= %s
            RETURNING spend_usd
            """,
            (tenant_id, day, usd, cap_usd + 1e-9),
        )
        if row is None:
            return False, await self.spend_today(tenant_id, day)
        return True, float(row[0])

    async def release_spend(self, tenant_id: str, day: date, usd: float) -> float:
        """Take usd back off the day's spend, never below zero (one atomic statement)."""
        row = await self._one(
            "UPDATE tenant_usage SET spend_usd = GREATEST(spend_usd - %s, 0), updated_at = now() "
            "WHERE tenant_id = %s AND day = %s RETURNING spend_usd",
            (usd, tenant_id, day),
        )
        return float(row[0]) if row else 0.0

    async def spend_today(self, tenant_id: str, day: date) -> float:
        """The dollars reserved for tenant_id on day."""
        row = await self._one(
            "SELECT spend_usd FROM tenant_usage WHERE tenant_id = %s AND day = %s", (tenant_id, day)
        )
        return float(row[0]) if row else 0.0

    async def reserve_bytes(self, tenant_id: str, n: int, cap_bytes: int) -> tuple[bool, int]:
        """Add n uploaded bytes unless that would pass cap_bytes (one atomic statement)."""
        if n > cap_bytes:
            return False, 0
        row = await self._one(
            """
            INSERT INTO tenant_usage (tenant_id, day, uploaded_bytes) VALUES (%s, %s, %s)
            ON CONFLICT (tenant_id, day) DO UPDATE
               SET uploaded_bytes = tenant_usage.uploaded_bytes + EXCLUDED.uploaded_bytes, updated_at = now()
               WHERE tenant_usage.uploaded_bytes + EXCLUDED.uploaded_bytes <= %s
            RETURNING uploaded_bytes
            """,
            (tenant_id, _STORAGE_DAY, n, cap_bytes),
        )
        if row is None:
            current = await self._one(
                "SELECT uploaded_bytes FROM tenant_usage WHERE tenant_id = %s AND day = %s", (tenant_id, _STORAGE_DAY)
            )
            return False, int(current[0]) if current else 0
        return True, int(row[0])

    async def count_render(self, tenant_id: str, day: date) -> None:
        """Count one render for tenant_id on day."""
        await self._one(
            """
            INSERT INTO tenant_usage (tenant_id, day, renders) VALUES (%s, %s, 1)
            ON CONFLICT (tenant_id, day) DO UPDATE SET renders = tenant_usage.renders + 1, updated_at = now()
            """,
            (tenant_id, day),
        )


_memory_usage = InMemoryUsageStore()
# Renders in flight in this process, per tenant. Railway runs one process per service,
# the same assumption as the other in-process job registries.
_active_renders: dict[str, int] = {}


def get_usage_store() -> UsageStore:
    """Postgres usage store when DATABASE_URL is set, else the in-memory one."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresUsageStore(pool)
    return _memory_usage


def _bound_tenant() -> str | None:
    """The tenant to bind, or None when there is none or it is the owner's (exempt)."""
    try:
        principal = current_principal()
    except NotAuthenticatedError:
        return None
    return None if principal.tenant_id == OWNER_TENANT_ID else principal.tenant_id


def _today() -> date:
    """The current UTC date — the day boundary for daily caps."""
    return datetime.now(UTC).date()


def day_start() -> datetime:
    """Midnight UTC of today."""
    return datetime.combine(_today(), datetime.min.time(), tzinfo=UTC)


def _too_long(label: str, limit: int, unit: str) -> HTTPException:
    """422 for a text over its cap."""
    return HTTPException(status_code=422, detail=f"{label} is too long — the limit is {limit} {unit}.")


def word_count(text: str) -> int:
    """How many whitespace-separated words text has."""
    return len(text.split())


def check_script(text: str, settings: PlatformSettings | None = None) -> None:
    """422 when a bound tenant's script has more than CAP_SCRIPT_WORDS words (F4)."""
    if _bound_tenant() is None:
        return
    cap = (settings or get_platform_settings()).CAP_SCRIPT_WORDS
    if word_count(text) > cap:
        raise _too_long("The script", cap, "words")


def check_prompt(text: str, label: str = "The prompt", settings: PlatformSettings | None = None) -> None:
    """422 when a bound tenant's image prompt / instruction is over CAP_PROMPT_CHARS."""
    if _bound_tenant() is None:
        return
    cap = (settings or get_platform_settings()).CAP_PROMPT_CHARS
    if len(text) > cap:
        raise _too_long(label, cap, "characters")


def check_style(text: str, settings: PlatformSettings | None = None) -> None:
    """422 when a bound tenant's master style is over CAP_STYLE_CHARS."""
    if _bound_tenant() is None:
        return
    cap = (settings or get_platform_settings()).CAP_STYLE_CHARS
    if len(text) > cap:
        raise _too_long("The style", cap, "characters")


def check_character(text: str, label: str = "A character description", settings: PlatformSettings | None = None) -> None:
    """422 when a bound tenant's character / entity description is over CAP_CHARACTER_CHARS."""
    if _bound_tenant() is None:
        return
    cap = (settings or get_platform_settings()).CAP_CHARACTER_CHARS
    if len(text) > cap:
        raise _too_long(label, cap, "characters")


async def enforce_runs_per_day(runs, settings: PlatformSettings | None = None) -> None:
    """429 when a bound tenant already started CAP_RUNS_PER_DAY runs today (UTC)."""
    tenant = _bound_tenant()
    if tenant is None:
        return
    cap = (settings or get_platform_settings()).CAP_RUNS_PER_DAY
    if await runs.count_created_since(tenant, day_start()) >= cap:
        raise HTTPException(
            status_code=429,
            detail=f"You have reached today's limit of {cap} new videos. It resets at midnight UTC.",
        )


async def spend_gate(usd: float, what: str = "this", settings: PlatformSettings | None = None) -> None:
    """Reserve usd of today's budget for a paid call, or raise 429. Call BEFORE the provider is.

    The tenant's row is incremented atomically, so concurrent calls cannot all pass a
    check that only one of them fits under.
    """
    tenant = _bound_tenant()
    if tenant is None or usd <= 0:
        return
    cap = (settings or get_platform_settings()).CAP_DAILY_SPEND_USD
    ok, _ = await get_usage_store().reserve_spend(tenant, _today(), usd, cap)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"You have reached today's usage limit, so {what} can't run now. It resets at midnight UTC.",
        )


async def release_spend(tenant_id: str, usd: float, day: date | None = None) -> None:
    """Give usd of a day's spend reservation back (a refunded or settled-down action), never below zero.

    The owner's tenant is not bound by ``spend_gate``, so there is nothing of its to release.
    ``day`` is the UTC day the reservation was taken on (today when omitted).
    """
    if tenant_id == OWNER_TENANT_ID or usd <= 0:
        return
    await get_usage_store().release_spend(tenant_id, day or _today(), usd)


async def reserve_upload(n_bytes: int, settings: PlatformSettings | None = None) -> None:
    """422 when a bound tenant's uploads would pass CAP_STORAGE_MB."""
    tenant = _bound_tenant()
    if tenant is None:
        return
    cap = (settings or get_platform_settings()).CAP_STORAGE_MB * 1024 * 1024
    ok, _ = await get_usage_store().reserve_bytes(tenant, n_bytes, cap)
    if not ok:
        raise HTTPException(status_code=413, detail="Your storage limit is reached — remove something first.")


@contextlib.asynccontextmanager
async def render_slot(settings: PlatformSettings | None = None) -> AsyncIterator[None]:
    """Hold one of the tenant's CAP_CONCURRENT_RENDERS slots for the duration, or raise 429."""
    tenant = _bound_tenant()
    if tenant is None:
        yield
        return
    cap = max(1, (settings or get_platform_settings()).CAP_CONCURRENT_RENDERS)
    if _active_renders.get(tenant, 0) >= cap:
        raise HTTPException(status_code=429, detail="A video of yours is still rendering — wait for it to finish.")
    _active_renders[tenant] = _active_renders.get(tenant, 0) + 1
    try:
        yield
    finally:
        _active_renders[tenant] = max(0, _active_renders.get(tenant, 1) - 1)


def claim_render_slot(settings: PlatformSettings | None = None) -> str | None:
    """Take a render slot for a background job; returns the tenant to release, or None when exempt. 429 when full."""
    tenant = _bound_tenant()
    if tenant is None:
        return None
    cap = max(1, (settings or get_platform_settings()).CAP_CONCURRENT_RENDERS)
    if _active_renders.get(tenant, 0) >= cap:
        raise HTTPException(status_code=429, detail="A video of yours is still rendering — wait for it to finish.")
    _active_renders[tenant] = _active_renders.get(tenant, 0) + 1
    return tenant


_render_gate: tuple[asyncio.AbstractEventLoop, int, asyncio.Semaphore] | None = None


def _gate(settings: PlatformSettings | None = None) -> asyncio.Semaphore:
    """The process-wide render gate: RENDER_MAX_CONCURRENT renders run, the rest wait their turn."""
    global _render_gate
    size = max(1, (settings or get_platform_settings()).RENDER_MAX_CONCURRENT)
    loop = asyncio.get_running_loop()
    if _render_gate is None or _render_gate[0] is not loop or _render_gate[1] != size:
        _render_gate = (loop, size, asyncio.Semaphore(size))
    return _render_gate[2]


def render_gate_full(settings: PlatformSettings | None = None) -> bool:
    """True when a render started now would have to wait for a free place."""
    return _gate(settings).locked()


@contextlib.asynccontextmanager
async def render_gate(settings: PlatformSettings | None = None) -> AsyncIterator[None]:
    """Wait for one of the server's RENDER_MAX_CONCURRENT places, hold it while FFmpeg runs.

    Every tenant shares the gate, so a few renders at once cannot starve the container's CPU
    and memory (a render runs up to four FFmpeg encodes itself).
    """
    gate = _gate(settings)
    async with gate:
        yield


def release_render_slot(tenant: str | None) -> None:
    """Give back a slot claimed with claim_render_slot (idempotent for None)."""
    if tenant is not None:
        _active_renders[tenant] = max(0, _active_renders.get(tenant, 1) - 1)
