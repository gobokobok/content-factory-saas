"""FastAPI application entry point — registers routes and validates ENV at startup."""

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

import src.clip_reranker as clip_reranker
from src.auth import AUTH_COOKIE_NAME, origin_allowed, verify_cookie
from src.config import Settings, get_settings
from src.log_redaction import install_log_redaction
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

_AUTH_EXEMPT_PATHS = {
    "/health",
    "/login",
    "/auth/login",
    "/auth/logout",
    "/auth/providers",
    "/auth/google/start",
    "/auth/google/callback",
    "/platform/telegram/webhook",
}

# A signed-in user who has not accepted the terms may reach only these (S9, D115).
_TERMS_PATHS = {"/terms", "/auth/me", "/auth/terms/accept", "/auth/logout"}

_STATIC_DIR = Path(__file__).parent / "static"
# P-UX3-S3: the clickable redesign prototype — static demo pages, no backend calls.
_PROTOTYPE_DIR = Path(__file__).parent.parent / "docs" / "ux" / "prototype"
# Shared UI assets (shell, styles) used by every page.
_UI_DIR = _STATIC_DIR / "ui"


def _configure_logging(log_level: str) -> None:
    """Set root logger level from settings and redact API keys from every handler."""
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    install_log_redaction()


def _mount_platform_router(app: FastAPI) -> None:
    """Mount the cf_platform API router under /platform.

    Fault-isolated: cf_platform import or init errors are logged and swallowed so the
    legacy app keeps running with platform routes simply absent (D047).
    """
    try:
        from cf_platform.interfaces.api import router as platform_router

        app.include_router(platform_router, prefix="/platform")
    except Exception:
        logging.getLogger(__name__).exception(
            "cf_platform router failed to mount — platform routes disabled"
        )


async def _run_platform_migrations() -> None:
    """Apply cf_platform's Postgres migrations (P2-S2, D048).

    Fault-isolated: any failure (including a missing/unreachable DATABASE_URL) is
    logged and swallowed so legacy startup never fails because of the platform's
    metadata index, mirroring _mount_platform_router's isolation (D047, D048).
    """
    try:
        from cf_platform.core.config import get_platform_settings
        from cf_platform.core.migrations import run_migrations

        result = await run_migrations(get_platform_settings().DATABASE_URL)
        logging.getLogger(__name__).info("cf_platform migrations: %s", result)
    except Exception:
        logging.getLogger(__name__).exception(
            "cf_platform migration run failed — continuing"
        )


async def _setup_platform_checkpointer() -> None:
    """Create the LangGraph checkpoint tables for cf_platform's checkpointer (P2-S4, D048).

    Fault-isolated: any failure (including a missing/unreachable DATABASE_URL) is
    logged and swallowed so legacy startup never fails because of the platform's
    checkpointer setup, mirroring _run_platform_migrations's isolation (D047, D048).
    """
    try:
        from cf_platform.core.config import get_platform_settings
        from cf_platform.core.db import get_checkpointer, setup_checkpointer

        checkpointer = get_checkpointer(get_platform_settings().DATABASE_URL)
        result = await setup_checkpointer(checkpointer)
        logging.getLogger(__name__).info("cf_platform checkpointer setup: %s", result)
    except Exception:
        logging.getLogger(__name__).exception(
            "cf_platform checkpointer setup failed — continuing"
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
    except (ValidationError, ValueError) as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).error("Startup failed — missing or invalid ENV vars:\n%s", exc)
        raise SystemExit(1) from exc

    await _run_platform_migrations()
    await _setup_platform_checkpointer()

    yield


# F3 / F10: the legacy pipeline UI and its run routes are off unless this is "true".
# Read from the environment directly because routes are mounted at import time,
# before Settings is built.
_LEGACY_ROUTES_ENABLED = os.environ.get("LEGACY_ROUTES_ENABLED", "").strip().lower() in {"1", "true", "yes"}

app = FastAPI(title="Content Factory", lifespan=lifespan)
app.include_router(auth_router.router)

def _guard_dependencies(owner_only: bool) -> list:
    """Dependencies for the non-platform routers: run scope for Studio's, owner-only for the legacy UI's.

    The legacy routes act on the whole bucket by guessable id (F3), so even when
    LEGACY_ROUTES_ENABLED mounts them only the owner's tenant may call them.
    """
    try:
        from cf_platform.interfaces.guards import enforce_scope, require_owner

        return [Depends(require_owner)] if owner_only else [Depends(enforce_scope)]
    except Exception:
        logging.getLogger(__name__).exception("tenant guards unavailable — mounting without them")
        return []


# Studio and the Creator call the run's settings and delete here (F2): behind the run scope
# guard, and registered first so they win over the same paths in the legacy module below.
app.include_router(runs_router.studio_router, dependencies=_guard_dependencies(owner_only=False))
if _LEGACY_ROUTES_ENABLED:
    _legacy_guard = _guard_dependencies(owner_only=True)
    # The module's Studio routes are already mounted above, behind the run scope guard.
    _legacy_runs = APIRouter()
    _legacy_runs.routes.extend(
        r for r in runs_router.router.routes if getattr(r, "name", "") not in runs_router._STUDIO_ROUTE_NAMES
    )
    app.include_router(_legacy_runs, dependencies=_legacy_guard)
    app.include_router(storyboard_router.router, dependencies=_legacy_guard)
    app.include_router(manifest_router.router, dependencies=_legacy_guard)
    app.include_router(assets_router.router, dependencies=_legacy_guard)
    app.include_router(alignment_router.router, dependencies=_legacy_guard)
    app.include_router(tts_router.router, dependencies=_legacy_guard)
    app.include_router(ffmpeg_script_router.router, dependencies=_legacy_guard)
    app.include_router(render_router.router, dependencies=_legacy_guard)
    app.include_router(metadata_router.router, dependencies=_legacy_guard)
_mount_platform_router(app)


def _own_origin(request: Request, trust_proxy: bool) -> str:
    """The origin this request was addressed to (scheme://host), proxy-aware."""
    scheme = request.url.scheme
    host = request.headers.get("host", request.url.netloc)
    if trust_proxy:
        scheme = request.headers.get("x-forwarded-proto", scheme).split(",")[0].strip() or scheme
        host = request.headers.get("x-forwarded-host", host).split(",")[0].strip() or host
    return f"{scheme}://{host}"


def _unauthorized(request: Request) -> JSONResponse | RedirectResponse:
    """302 to /login for a page navigation, 401 for an API call."""
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(url="/login", status_code=302)
    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


async def _resolve_principal(request: Request, settings: Settings):
    """Resolve the request's session cookie to a Principal, or None.

    A server-side session (random token, hashed in the store) wins. Failing that, the
    pre-P-AUTH constant cookie still means "the owner" while ACCEPT_LEGACY_COOKIE is on
    (F6 bridge). Imports are local so a cf_platform failure leaves only the legacy path.
    """
    cookie = request.cookies.get(AUTH_COOKIE_NAME, "")
    try:
        from cf_platform.core.accounts import owner_principal, principal_from_cookie, token_from_cookie

        if token_from_cookie(cookie) is not None:
            from cf_platform.interfaces.dependencies import get_account_store

            store = request.app.dependency_overrides.get(get_account_store, get_account_store)()
            resolved = await principal_from_cookie(store, cookie, terms_version=settings.TERMS_VERSION)
            if resolved is not None:
                return resolved[0]
    except Exception:
        logging.getLogger(__name__).warning("Session lookup failed", exc_info=True)
        # A store outage must not fall through to the weaker cookie for session cookies.
        if cookie.startswith("s1."):
            return None
    if settings.ACCEPT_LEGACY_COOKIE and verify_cookie(cookie, settings.SESSION_SECRET_KEY):
        from cf_platform.core.accounts import owner_principal

        return owner_principal()
    return None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authenticate, bind the principal, check Origin and Basic's allow-list (P-AUTH S1, S6).

    Exempt paths pass straight through. Browser navigations (Accept: text/html) get
    302 → /login; API/fetch calls get 401 so JS can detect and redirect. The principal
    travels in a ContextVar, so every route reads the same tenant the middleware resolved.
    """
    path = request.url.path
    if path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    # Respect dependency overrides (e.g. in tests) by checking app.dependency_overrides
    settings_fn = request.app.dependency_overrides.get(get_settings, get_settings)
    settings = settings_fn()
    principal = await _resolve_principal(request, settings)
    if principal is None:
        return _unauthorized(request)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin is not None:
            extra = {o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()}
            if not origin_allowed(origin, _own_origin(request, settings.TRUST_PROXY_HEADERS), extra):
                return JSONResponse(status_code=403, content={"detail": "Cross-site request refused."})

    if not principal.terms_accepted and path not in _TERMS_PATHS and not path.startswith("/ui/"):
        if "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(url="/terms", status_code=302)
        return JSONResponse(status_code=403, content={"detail": "terms_required"})

    if not principal.is_super:
        from cf_platform.core.gating import BASIC_HOME, basic_may

        if not basic_may(request.method, path):
            if "text/html" in request.headers.get("accept", "") and request.method == "GET":
                return RedirectResponse(url=BASIC_HOME, status_code=302)
            return JSONResponse(status_code=403, content={"detail": "This needs a Super account."})

    from cf_platform.core.accounts import reset_principal, set_principal

    token = set_principal(principal)
    try:
        response = await call_next(request)
    finally:
        reset_principal(token)
    if path.startswith("/ui/"):
        # The page scripts change with every deploy; revalidate them (cheap, ETag) instead of
        # letting a browser's heuristic cache keep an old core.js against a new server.
        response.headers["Cache-Control"] = "no-cache"
    return response


_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/", include_in_schema=False)
def projects_ui() -> FileResponse:
    """Serve the project list — the operator's landing page (P12, D092)."""
    return FileResponse(_STATIC_DIR / "projects.html", headers=_NO_CACHE)


@app.get("/project", include_in_schema=False)
def project_ui() -> FileResponse:
    """Serve one project's page (shortlist + runs); the project id is the `id` query param."""
    return FileResponse(_STATIC_DIR / "project.html", headers=_NO_CACHE)


@app.get("/library", include_in_schema=False)
def library_ui() -> FileResponse:
    """Serve a tenant-wide asset library (videos, audio, footage, AI generations, music); `?kind=` picks it."""
    return FileResponse(_STATIC_DIR / "library.html", headers=_NO_CACHE)


@app.get("/settings", include_in_schema=False)
def settings_ui() -> FileResponse:
    """Serve the tenant settings pages — Integrations and Defaults; `?tab=` picks one (P14, D104, P-UX build)."""
    return FileResponse(_STATIC_DIR / "settings.html", headers=_NO_CACHE)


@app.get("/create", include_in_schema=False)
def creator_ui() -> FileResponse:
    """Serve the Creator pages — the simplified flow beside the Studio (P-LITE, D114, D117)."""
    return FileResponse(_STATIC_DIR / "creator.html", headers=_NO_CACHE)


@app.get("/terms", include_in_schema=False)
def terms_ui() -> FileResponse:
    """Serve the terms page — a first sign-in must accept it before anything else (S9, D115)."""
    return FileResponse(_STATIC_DIR / "terms.html", headers=_NO_CACHE)


@app.get("/studio", include_in_schema=False)
def studio_ui() -> FileResponse:
    """Serve the Studio pipeline UI for one run (`/studio#run/<run_id>/<stage>`)."""
    return FileResponse(_STATIC_DIR / "studio-v2.html", headers=_NO_CACHE)


if _LEGACY_ROUTES_ENABLED:

    @app.get("/legacy", include_in_schema=False)
    def legacy_pipeline_ui() -> FileResponse:
        """Serve the legacy end-to-end pipeline UI (D047 — off unless LEGACY_ROUTES_ENABLED)."""
        return FileResponse(
            _STATIC_DIR / "pipeline.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    """Serve the login page."""
    return FileResponse(_STATIC_DIR / "login-v2.html")


# Served behind the same login as every other page (the auth middleware covers mounts).
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=_UI_DIR), name="ui")
if _PROTOTYPE_DIR.is_dir():
    app.mount("/prototype", StaticFiles(directory=_PROTOTYPE_DIR, html=True), name="prototype")


@app.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Return service health, the environment and the start-up migration status.

    Exempt from login so the deploy check can call it. "migrations" is one of
    "ok", "unavailable" (no database configured), "error" or "not_run"; an
    "error" turns "status" to "degraded" (F11). The HTTP status stays 200 so a
    database problem never takes the legacy app down (D048).
    """
    try:
        from cf_platform.core.migrations import get_migration_status

        migrations = get_migration_status()
    except Exception:
        migrations = "unavailable"
    return {
        "status": "degraded" if migrations == "error" else "ok",
        "environment": settings.ENVIRONMENT,
        "migrations": migrations,
    }
