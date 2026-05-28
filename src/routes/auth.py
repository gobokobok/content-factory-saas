"""Auth routes — POST /auth/login and POST /auth/logout."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.auth import AUTH_COOKIE_NAME, sign_cookie, verify_cookie
from src.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year — effectively never expires for POC


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    password: str


def _is_prod(settings: Settings) -> bool:
    """Return True when running in the prod environment."""
    return settings.ENVIRONMENT == "prod"


@router.post("/login")
def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Validate operator password and set a signed session cookie.

    Returns 200 + {ok: true} on success, 401 on wrong password.
    """
    if body.password != settings.OPERATOR_PASSWORD:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Wrong password"})

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
