"""Auth routes — POST /auth/login and POST /auth/logout."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.auth import AUTH_COOKIE_NAME, LoginRateLimiter, passwords_match, sign_cookie
from src.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year — effectively never expires for POC

_RATE_LIMITER = LoginRateLimiter()


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    password: str


def _cookie_secure(settings: Settings) -> bool:
    """Return True when the session cookie must be Secure.

    Every deployed environment (dev and prod) is served over https, so only a
    request that reached the app directly on localhost may use a plain cookie (F18).
    """
    return not settings.COOKIE_ALLOW_INSECURE


def _client_ip(request: Request, settings: Settings) -> str:
    """Return the caller's address for the login lockout.

    Behind Railway's proxy ``request.client.host`` is the proxy, so every visitor
    shares one lockout bucket (F14). The right-most X-Forwarded-For entry is the one
    the proxy itself appended — earlier entries are client-supplied and spoofable.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Validate operator password and set a signed session cookie.

    Returns 200 + {ok: true} on success, 401 on wrong password, and 429 once
    an IP has exceeded LOGIN_MAX_ATTEMPTS failures within the window.
    """
    client_ip = _client_ip(request, settings)
    if _RATE_LIMITER.is_blocked(
        client_ip, settings.LOGIN_MAX_ATTEMPTS, settings.LOGIN_ATTEMPT_WINDOW_SECONDS
    ):
        return JSONResponse(
            status_code=429,
            content={"ok": False, "error": "Too many attempts — try again later"},
        )

    if not passwords_match(body.password, settings.OPERATOR_PASSWORD):
        _RATE_LIMITER.record_failure(client_ip, settings.LOGIN_ATTEMPT_WINDOW_SECONDS)
        return JSONResponse(status_code=401, content={"ok": False, "error": "Wrong password"})

    _RATE_LIMITER.reset(client_ip)
    token = sign_cookie(settings.SESSION_SECRET_KEY)
    response = JSONResponse(content={"ok": True})
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(settings),
        max_age=_COOKIE_MAX_AGE,
    )
    return response


@router.post("/logout")
def logout(settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Clear the session cookie and return {ok: true}."""
    response = JSONResponse(content={"ok": True})
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(settings),
    )
    return response
