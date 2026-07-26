"""Platform-facing REST API — composition root, mounted under /platform in src/main.py.

Route handlers live in cf_platform/interfaces/routes/ (D069), grouped by domain
(meta, echo, blocks, workers, studio, runs, pipeline, telegram_webhook). This
module assembles them into one router and re-exports the names older tests
and call sites still import directly from here.
"""

from fastapi import APIRouter

from cf_platform.core.config import get_platform_settings  # noqa: F401
from cf_platform.core.db import get_pool  # noqa: F401
from cf_platform.interfaces.dependencies import (  # noqa: F401
    get_artifact_repository,
    get_artifact_storage,
    get_discovery_adapters,
    get_execution_repository,
    get_graph_checkpointer,
    get_run_repository,
    get_trace_event_repository,
    get_worker_registry,
)
from cf_platform.interfaces.routes import (
    blocks,
    echo,
    meta,
    pipeline,
    runs,
    studio,
    telegram_webhook,
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
router.include_router(meta.router)
router.include_router(echo.router)
router.include_router(blocks.router)
router.include_router(workers.router)
router.include_router(studio.router)
router.include_router(runs.router)
router.include_router(pipeline.router)
router.include_router(telegram_webhook.router)
