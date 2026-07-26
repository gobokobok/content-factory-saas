"""Shared FastAPI dependencies and process-local singleton state for cf_platform routes.

Split out of cf_platform/interfaces/api.py (D069) so each route module can
import only what it needs without pulling in the whole platform surface.
"""

from fastapi import Depends
from langgraph.checkpoint.base import BaseCheckpointSaver

from cf_platform.blocks.idea_to_script import register_idea_to_script_workers
from cf_platform.blocks.niche_to_ideas import register_niche_to_ideas_workers
from cf_platform.core.artifact_manager import (
    ArtifactRepository,
    ArtifactStorage,
    InMemoryArtifactRepository,
    R2ArtifactStorage,
)
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.db import get_checkpointer, get_pool
from cf_platform.core.postgres_repos import (
    PostgresArtifactRepository,
    PostgresExecutionRepository,
    PostgresRunRepository,
    PostgresTraceEventRepository,
)
from cf_platform.core.run_manager import InMemoryRunRepository, RunRepository
from cf_platform.core.schemas import SourceAdapter
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

# Single-operator platform (multi-tenant isolation lands in S19) — fixed user_id for now.
PLATFORM_USER_ID = "operator"

# In-memory fallback when DATABASE_URL is unset (D048) — process-local singletons.
_run_repository = InMemoryRunRepository()
_execution_repository = InMemoryExecutionRepository()
_artifact_repository = InMemoryArtifactRepository()
_trace_event_repository = InMemoryTraceEventRepository()
_worker_registry = WorkerRegistry()
_worker_registry.register("echo", ECHO_REGISTRATION)
register_niche_to_ideas_workers(_worker_registry)
register_idea_to_script_workers(_worker_registry)
_worker_registry.register("voice_production", VOICE_PRODUCTION_REGISTRATION)
_worker_registry.register("storyboard_worker", STORYBOARD_WORKER_REGISTRATION)
_worker_registry.register("acquisition_worker", ACQUISITION_WORKER_REGISTRATION)


def get_run_repository() -> RunRepository:
    """Return a Postgres-backed RunRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresRunRepository(pool)
    return _run_repository


def get_execution_repository() -> ExecutionRepository:
    """Return a Postgres-backed ExecutionRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresExecutionRepository(pool)
    return _execution_repository


def get_artifact_repository() -> ArtifactRepository:
    """Return a Postgres-backed ArtifactRepository when DATABASE_URL is set, else the in-memory fallback (D048)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresArtifactRepository(pool)
    return _artifact_repository


def get_trace_event_repository() -> TraceEventRepository:
    """Return a Postgres-backed TraceEventRepository when DATABASE_URL is set, else the in-memory fallback (D048, D050)."""
    pool = get_pool(get_platform_settings().DATABASE_URL)
    if pool is not None:
        return PostgresTraceEventRepository(pool)
    return _trace_event_repository


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
