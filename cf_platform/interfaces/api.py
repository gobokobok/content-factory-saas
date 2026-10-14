"""Platform-facing REST API — composition root, mounted under /platform in src/main.py.

Route handlers live in cf_platform/interfaces/routes/ (D069), grouped by domain
(meta, echo, blocks, workers, studio, runs, projects, pipeline, telegram_webhook). This
module assembles them into one router and re-exports the names older tests
and call sites still import directly from here.
"""

import os

from fastapi import APIRouter, Depends

from cf_platform.core.config import get_platform_settings  # noqa: F401
from cf_platform.core.db import get_pool  # noqa: F401
from cf_platform.interfaces.dependencies import (  # noqa: F401
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_project_repository,
    get_run_repository,
    get_shortlist_repository,
    get_trace_event_repository,
    get_worker_registry,
    require_super,
)
from cf_platform.interfaces.guards import enforce_scope
from cf_platform.interfaces.routes import (
    blocks,
    creator,
    echo,
    library,
    meta,
    pipeline,
    projects,
    runs,
    studio,
    studio_ai,
    studio_animation,
    studio_providers,
    studio_visuals,
    studio_voice,
    telegram_webhook,
    tenant_settings,
    workers,
)
from cf_platform.interfaces.routes.blocks import IdeaToScriptRequest, IdeaToScriptResponse  # noqa: F401
from cf_platform.interfaces.routes.telegram_webhook import (  # noqa: F401
    TelegramClient,
    _run_pick_and_reply,
    _run_pipeline_and_reply,
    _run_script_and_reply,
    _run_testvoice_and_reply,
    build_full_pipeline_graph,
    build_voice_production_worker,
    create_run,
    read_artifact,
    run_graph,
    transition_run,
)
from cf_platform.interfaces.routes.workers import (  # noqa: F401
    RenderWorkerRequest,
    RenderWorkerResponse,
    StoryboardWorkerRequest,
    StoryboardWorkerResponse,
    VerifiedStoryboardArtifact,  # noqa: F401
    build_render_worker,
    build_storyboard_worker,
    render_worker_endpoint,
    storyboard_worker_endpoint,
)

router = APIRouter()

# P-AUTH S3: every route module answers only for the signed-in user's own runs and
# projects. The scope guard reads run_id / project_id from the path, so a route added
# later cannot forget it. The Telegram webhook authenticates by its own secret, not a
# session, so it stays outside (and is unmounted unless TELEGRAM_ROUTES_ENABLED, S6).
_SCOPED = [Depends(enforce_scope)]
# Routes Basic never reaches: closed at the router too, not only by the middleware's allow-list.
_SUPER_ONLY = [Depends(require_super), Depends(enforce_scope)]

router.include_router(meta.router, dependencies=_SCOPED)
router.include_router(echo.router, dependencies=_SUPER_ONLY)
router.include_router(blocks.router, dependencies=_SUPER_ONLY)
router.include_router(workers.router, dependencies=_SCOPED)
router.include_router(studio.router, dependencies=_SCOPED)
router.include_router(studio_ai.router, dependencies=_SCOPED)
router.include_router(studio_animation.router, dependencies=_SCOPED)
router.include_router(studio_providers.router, dependencies=_SUPER_ONLY)
router.include_router(studio_visuals.router, dependencies=_SUPER_ONLY)
router.include_router(creator.router, dependencies=_SCOPED)
router.include_router(studio_voice.router, dependencies=_SCOPED)
router.include_router(runs.router, dependencies=_SUPER_ONLY)
router.include_router(projects.router, dependencies=_SCOPED)
router.include_router(tenant_settings.router, dependencies=_SUPER_ONLY)
router.include_router(library.router, dependencies=_SUPER_ONLY)
router.include_router(pipeline.router, dependencies=_SUPER_ONLY)
if os.environ.get("TELEGRAM_ROUTES_ENABLED", "").strip().lower() in {"1", "true", "yes"}:
    router.include_router(telegram_webhook.router)
