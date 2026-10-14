"""Shared FastAPI dependencies and process-local singleton state for cf_platform routes.

Split out of cf_platform/interfaces/api.py (D069) so each route module can
import only what it needs without pulling in the whole platform surface.
"""

import logging

from fastapi import Depends, HTTPException
from langgraph.checkpoint.base import BaseCheckpointSaver

from cf_platform.blocks.idea_to_script import register_idea_to_script_workers
from cf_platform.blocks.niche_to_ideas import register_niche_to_ideas_workers
from cf_platform.core.accounts import (
    OWNER_TENANT_ID,
    AccountStore,
    InMemoryAccountStore,
    NotAuthenticatedError,
    Principal,
    current_principal,
    current_tenant_id,
)
from cf_platform.core.artifact_manager import (
    ArtifactRepository,
    ArtifactStorage,
    InMemoryArtifactRepository,
    R2ArtifactStorage,
)
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import get_checkpointer, get_pool
from cf_platform.core.integrations import TenantKeyError, effective_platform_settings
from cf_platform.core.postgres_accounts import PostgresAccountStore
from cf_platform.core.postgres_project_repos import (
    PostgresProjectRepository,
    PostgresShortlistRepository,
)
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
    PostgresTraceEventRepository,
)
from cf_platform.core.postgres_tenant_settings import PostgresTenantSettingsRepository
from cf_platform.core.projects import InMemoryProjectRepository, ProjectRepository
from cf_platform.core.run_manager import InMemoryRunRepository, RunRepository
from cf_platform.core.schemas import SourceAdapter
from cf_platform.core.shortlist import InMemoryShortlistRepository, ShortlistRepository
from cf_platform.core.tenant_settings import InMemoryTenantSettingsRepository, TenantSettingsRepository
from cf_platform.core.trace_repo import InMemoryTraceEventRepository, TraceEventRepository
from cf_platform.core.worker_registry import (
    ExecutionRepository,
    InMemoryExecutionRepository,
    WorkerRegistry,
)
from cf_platform.sources.google_trends import GoogleTrendsAdapter
from cf_platform.sources.reddit import RedditAdapter
from cf_platform.sources.youtube import YouTubeAdapter
from cf_platform.workers.acquisition_worker import ACQUISITION_WORKER_REGISTRATION
from cf_platform.workers.echo import ECHO_REGISTRATION
from cf_platform.workers.storyboard_worker import STORYBOARD_WORKER_REGISTRATION
from cf_platform.workers.voice_production import VOICE_PRODUCTION_REGISTRATION

# The owner's tenant — where every run made before P-AUTH lives (D092). Kept under its old
# name for tests and the Telegram path; routes no longer scope by it: they read the signed-in
# user's tenant from current_tenant_id() / current_user().
PLATFORM_USER_ID = OWNER_TENANT_ID

# In-memory fallback when DATABASE_URL is unset (D048) — process-local singletons.
_run_repository = InMemoryRunRepository()
_execution_repository = InMemoryExecutionRepository()
_artifact_repository = InMemoryArtifactRepository()
_trace_event_repository = InMemoryTraceEventRepository()
_project_repository = InMemoryProjectRepository(PLATFORM_USER_ID)
_shortlist_repository = InMemoryShortlistRepository()
_tenant_settings_repository = InMemoryTenantSettingsRepository()
_account_store = InMemoryAccountStore()
_worker_registry = WorkerRegistry()
_worker_registry.register("echo", ECHO_REGISTRATION)
register_niche_to_ideas_workers(_worker_registry)
register_idea_to_script_workers(_worker_registry)
_worker_registry.register("voice_production", VOICE_PRODUCTION_REGISTRATION)
_worker_registry.register("storyboard_worker", STORYBOARD_WORKER_REGISTRATION)
_worker_registry.register("acquisition_worker", ACQUISITION_WORKER_REGISTRATION)


def _memory_store_allowed() -> bool:
    """Whether process-memory repositories may stand in for Postgres (local development only, S6)."""
    return bool(get_platform_settings().ALLOW_IN_MEMORY_STORE)


def _memory_fallback(store):
    """Return the in-memory store, or refuse with 503 when this is not a local run (S6).

    Without DATABASE_URL a server would keep every user's data in one process's memory and
    lose it on restart — and share it across tenants through the module singleton. Failing
    closed is better than looking like it works.
    """
    if not _memory_store_allowed():
        raise HTTPException(
            status_code=503,
            detail="Storage is not configured on this server (DATABASE_URL is empty).",
        )
    return store


def get_account_store() -> AccountStore:
    """Return the Postgres-backed account store when DATABASE_URL is set, else the in-memory one (local only)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresAccountStore(pool)
    return _memory_fallback(_account_store)


def current_user() -> Principal:
    """Dependency: the signed-in principal. 401 when the request has none (the middleware sets it)."""
    try:
        return current_principal()
    except NotAuthenticatedError:
        raise HTTPException(status_code=401, detail="Unauthorized") from None


def current_tenant() -> str:
    """The tenant id of the signed-in user — every repository read and write is scoped to it."""
    return current_user().tenant_id


def require_super(principal: Principal = Depends(current_user)) -> Principal:
    """Dependency: allow only a Super account that is not viewing as Basic (D118). 403 otherwise."""
    if not principal.is_super:
        raise HTTPException(status_code=403, detail="This needs a Super account.")
    return principal


def get_run_repository() -> RunRepository:
    """Return a Postgres-backed RunRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresRunRepository(pool)
    return _memory_fallback(_run_repository)


def get_project_repository() -> ProjectRepository:
    """Return a Postgres-backed ProjectRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresProjectRepository(pool)
    return _memory_fallback(_project_repository)


def get_shortlist_repository() -> ShortlistRepository:
    """Return a Postgres-backed ShortlistRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresShortlistRepository(pool)
    return _memory_fallback(_shortlist_repository)


def get_tenant_settings_repository() -> TenantSettingsRepository:
    """Return a Postgres-backed TenantSettingsRepository when DATABASE_URL is set, else the in-memory fallback (D048, D104)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresTenantSettingsRepository(pool)
    return _memory_fallback(_tenant_settings_repository)


def get_execution_repository() -> ExecutionRepository:
    """Return a Postgres-backed ExecutionRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresExecutionRepository(pool)
    return _memory_fallback(_execution_repository)


def get_artifact_repository() -> ArtifactRepository:
    """Return a Postgres-backed ArtifactRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresArtifactRepository(pool)
    return _memory_fallback(_artifact_repository)


def get_trace_event_repository() -> TraceEventRepository:
    """Return a Postgres-backed TraceEventRepository when DATABASE_URL is set, else the in-memory fallback (D048, D050)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresTraceEventRepository(pool)
    return _memory_fallback(_trace_event_repository)


def get_worker_registry() -> WorkerRegistry:
    """Return the process-local WorkerRegistry, pre-populated with the echo and discovery workers."""
    return _worker_registry


def build_discovery_adapters(settings: PlatformSettings) -> list[tuple[str, SourceAdapter]]:
    """Return the (source_name, SourceAdapter) pairs for the discovery worker (D050).

    Adapters are constructed unconditionally even with empty credentials — a
    missing credential surfaces as an "error" trace event for that one source
    (partial-failure isolation, AC #3) rather than at construction time.
    """
    return [
        ("reddit", RedditAdapter(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET, settings.REDDIT_USER_AGENT)),
        ("google_trends", GoogleTrendsAdapter()),
        ("youtube", YouTubeAdapter(settings.YOUTUBE_API_KEY)),
    ]


def get_discovery_adapters(
    settings: PlatformSettings = Depends(get_platform_settings),
) -> list[tuple[str, SourceAdapter]]:
    """FastAPI dependency wrapping build_discovery_adapters — overridable with stub adapters in tests."""
    return build_discovery_adapters(settings)


async def get_graph_checkpointer() -> BaseCheckpointSaver:
    """Return a Postgres-backed checkpointer when DATABASE_URL is set, else MemorySaver (D048, P2-S4).

    Async because AsyncPostgresSaver's constructor requires a running event loop
    (asyncio.get_running_loop()) — FastAPI runs async dependencies on the loop
    directly, whereas sync dependencies run in a worker thread without one.
    """
    return get_checkpointer(get_platform_settings().DATABASE_URL)


def get_artifact_storage() -> ArtifactStorage:
    """Return an R2ArtifactStorage built from cf_platform's own settings (D047)."""
    settings = get_platform_settings()
    return R2ArtifactStorage(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )


_logger = logging.getLogger(__name__)


async def get_effective_platform_settings(
    settings: PlatformSettings = Depends(get_platform_settings),
    repo: TenantSettingsRepository = Depends(get_tenant_settings_repository),
) -> PlatformSettings:
    """Platform settings with the tenant's saved service keys overlaid (Integrations page).

    A key saved in Settings wins over the Railway variable. A settings-database outage
    must not break the pipeline, so any error falls back to the plain Railway settings.
    """
    try:
        return await effective_platform_settings(repo, current_tenant_id(), settings)
    except TenantKeyError as exc:
        # F5: a non-owner tenant's saved key is unreadable. Say so; never spend the owner's key.
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except Exception:
        _logger.warning("Tenant keys unavailable — using the Railway variables", exc_info=True)
        return settings
