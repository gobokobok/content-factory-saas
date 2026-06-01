"""FastAPI application entry point — registers routes and validates ENV at startup."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError

import src.clip_reranker as clip_reranker
from src.auth import AUTH_COOKIE_NAME, verify_cookie
from src.config import Settings, get_settings
from src.routes import alignment as alignment_router
from src.routes import assets as assets_router
from src.routes import auth as auth_router
from src.routes import ffmpeg_script as ffmpeg_script_router
from src.routes import manifest as manifest_router
from src.routes import metadata as metadata_router
from src.routes import render as render_router
from src.routes import runs as runs_router
from src.routes import storyboard as storyboard_router
from src.routes import tts as tts_router

_AUTH_EXEMPT_PATHS = {"/health", "/login", "/auth/login", "/auth/logout"}

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
        if settings.CLIP_RERANK_ENABLED:
            clip_reranker.load_model()
    except ValidationError as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Startup failed — missing or invalid ENV vars:\n%s", exc)
        raise SystemExit(1) from exc

    yield


app = FastAPI(title="Content Factory", lifespan=lifespan)
app.include_router(auth_router.router)
app.include_router(runs_router.router)
app.include_router(storyboard_router.router)
app.include_router(manifest_router.router)
app.include_router(assets_router.router)
app.include_router(alignment_router.router)
app.include_router(tts_router.router)
app.include_router(ffmpeg_script_router.router)
app.include_router(render_router.router)
app.include_router(metadata_router.router)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Gate all routes except exempt paths.

    Browser navigations (Accept: text/html) get 302 → /login.
    API/fetch calls get 401 so JS can detect and redirect.
    """
    if request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    # Respect dependency overrides (e.g. in tests) by checking app.dependency_overrides
    settings_fn = request.app.dependency_overrides.get(get_settings, get_settings)
    settings = settings_fn()
    cookie = request.cookies.get(AUTH_COOKIE_NAME, "")
    if not verify_cookie(cookie, settings.SESSION_SECRET_KEY):
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


@app.get("/", include_in_schema=False)
def pipeline_ui() -> FileResponse:
    """Serve the end-to-end pipeline UI."""
    return FileResponse(_STATIC_DIR / "pipeline.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    """Serve the login page."""
    return FileResponse(_STATIC_DIR / "login.html")


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Return service health and current environment."""
    return {"status": "ok", "environment": settings.ENVIRONMENT}
