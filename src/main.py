"""FastAPI application entry point — registers routes and validates ENV at startup."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from pydantic import ValidationError

from src.config import Settings, get_settings
from src.routes import assets as assets_router
from src.routes import ffmpeg_script as ffmpeg_script_router
from src.routes import manifest as manifest_router
from src.routes import render as render_router
from src.routes import runs as runs_router
from src.routes import storyboard as storyboard_router

_STATIC_DIR = Path(__file__).parent / "static"


def _configure_logging(log_level: str) -> None:
    """Set root logger level from settings."""
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Validate all ENV vars at startup. Crash fast if anything is missing or invalid."""
    try:
        settings = get_settings()
        _configure_logging(settings.LOG_LEVEL)
        logging.getLogger(__name__).info(
            "Startup OK — environment=%s", settings.ENVIRONMENT
        )
    except ValidationError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Startup failed — missing or invalid ENV vars:\n%s", exc)
        raise SystemExit(1) from exc

    yield


app = FastAPI(title="Content Factory", lifespan=lifespan)
app.include_router(runs_router.router)
app.include_router(storyboard_router.router)
app.include_router(manifest_router.router)
app.include_router(assets_router.router)
app.include_router(ffmpeg_script_router.router)
app.include_router(render_router.router)


@app.get("/", include_in_schema=False)
def pipeline_ui() -> FileResponse:
    """Serve the end-to-end pipeline UI."""
    return FileResponse(_STATIC_DIR / "pipeline.html")


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Return service health and current environment."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}
