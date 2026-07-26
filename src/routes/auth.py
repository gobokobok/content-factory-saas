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


def _is_prod(settings: Settings) -> bool:
    """Return True when running in the prod environment."""
    return settings.ENVIRONMENT == "prod"


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
    client_ip = request.client.host if request.client else "unknown"
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
        secure=_is_prod(settings),
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
        secure=_is_prod(settings),
    )
    return response
