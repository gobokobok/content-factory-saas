"""Auth routes — password login for the owner, Google sign-in, session and account routes (P-AUTH)."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from src.auth import AUTH_COOKIE_NAME, LoginRateLimiter, passwords_match
from src.config import Settings, get_settings

router = APIRouter(prefix="/auth", tags=["auth"])

_RATE_LIMITER = LoginRateLimiter()

# A pending Google sign-in is valid for this long; the callback must arrive within it.
_OAUTH_STATE_TTL = timedelta(minutes=10)


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    password: str


class ViewAsRequest(BaseModel):
    """Payload for POST /auth/view-as."""

    basic: bool


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


def _account_store(request: Request):
    """The AccountStore, honouring test overrides. Raises HTTPException(503) when none is configured."""
    from cf_platform.interfaces.dependencies import get_account_store

    return request.app.dependency_overrides.get(get_account_store, get_account_store)()


def _set_session_cookie(response, value: str, settings: Settings) -> None:
    """Attach the session cookie: HttpOnly, SameSite=Lax, Secure outside local, lifetime = session lifetime."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=value,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(settings),
        max_age=60 * 60 * 24 * max(1, settings.SESSION_TTL_DAYS),
    )


def _clear_session_cookie(response, settings: Settings) -> None:
    """Delete the session cookie."""
    response.delete_cookie(key=AUTH_COOKIE_NAME, httponly=True, samesite="lax", secure=_cookie_secure(settings))


async def _revoke_presented_session(request: Request) -> None:
    """Revoke the session the request carries, if any — logout and rotation at login."""
    from cf_platform.core.accounts import hash_token, token_from_cookie

    token = token_from_cookie(request.cookies.get(AUTH_COOKIE_NAME, ""))
    if token:
        await _account_store(request).revoke_session(hash_token(token))


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Validate the owner's password and start a server-side session for the owner's account.

    Returns 200 + {ok: true} on success, 401 on wrong password, and 429 once
    an IP has exceeded LOGIN_MAX_ATTEMPTS failures within the window. The cookie is a
    random token whose hash is stored with an expiry — revocable, rotated at every
    login (F6) — not the constant HMAC the first version issued.
    """
    from cf_platform.core.accounts import create_session, ensure_owner_user

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
    store = _account_store(request)
    await _revoke_presented_session(request)
    owner = await ensure_owner_user(store)
    value, _ = await create_session(store, owner.user_id, ttl_days=settings.SESSION_TTL_DAYS)
    response = JSONResponse(content={"ok": True})
    _set_session_cookie(response, value, settings)
    return response


@router.post("/logout")
async def logout(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Revoke the session server-side, clear the cookie and return {ok: true}."""
    try:
        await _revoke_presented_session(request)
    except Exception:  # a store outage must not stop a user leaving; the cookie is cleared regardless
        pass
    response = JSONResponse(content={"ok": True})
    _clear_session_cookie(response, settings)
    return response


@router.get("/providers")
def providers(settings: Settings = Depends(get_settings)) -> dict:
    """Which sign-in methods this deployment offers (exempt from login — the login page reads it)."""
    return {
        "google": bool(
            settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET and settings.GOOGLE_OAUTH_REDIRECT_URI
        ),
        "password": True,
    }


@router.get("/google/start")
async def google_start(
    request: Request, next: str = "/", settings: Settings = Depends(get_settings)
) -> RedirectResponse:
    """Begin Google sign-in: store a single-use state + PKCE verifier, then redirect to Google."""
    from cf_platform.core.accounts import OAuthState, hash_token
    from cf_platform.core.google_oauth import authorization_url, new_code_verifier, new_state, safe_next

    if not (
        settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET and settings.GOOGLE_OAUTH_REDIRECT_URI
    ):
        return RedirectResponse("/login?error=google_off", status_code=302)
    state, verifier = new_state(), new_code_verifier()
    await _account_store(request).save_oauth_state(
        OAuthState(
            state_hash=hash_token(state),
            code_verifier=verifier,
            next_path=safe_next(next),
            created_at=datetime.now(UTC),
        )
    )
    return RedirectResponse(
        authorization_url(
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
            state=state,
            verifier=verifier,
        ),
        status_code=302,
    )


def _login_error(code: str) -> RedirectResponse:
    """Send the browser back to the login page with a short error code."""
    return RedirectResponse(f"/login?error={quote(code)}", status_code=302)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    """Finish Google sign-in: check state, exchange the code, find or create the user, start a session.

    Sign-in is allow-listed (ALLOWED_EMAILS / OWNER_EMAILS / SUPER_EMAILS) until
    SIGNUP_OPEN is set. The session token is new at every sign-in (rotation).
    """
    from cf_platform.core.accounts import create_session, hash_token, parse_email_list, provision_google_user
    from cf_platform.core.config import get_platform_settings
    from cf_platform.core.google_oauth import GoogleAuthError, exchange_code, safe_next
    from cf_platform.interfaces.dependencies import get_project_repository

    if error or not code or not state:
        return _login_error("cancelled")
    store = _account_store(request)
    pending = await store.pop_oauth_state(hash_token(state))
    if pending is None or datetime.now(UTC) - pending.created_at > _OAUTH_STATE_TTL:
        return _login_error("expired")
    try:
        identity = await asyncio.to_thread(
            exchange_code,
            code=code,
            verifier=pending.code_verifier,
            client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
            client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
            now=time.time(),
        )
    except GoogleAuthError:
        return _login_error("google_failed")

    owners = parse_email_list(settings.OWNER_EMAILS)
    supers = parse_email_list(settings.SUPER_EMAILS)
    allowed = parse_email_list(settings.ALLOWED_EMAILS) | owners | supers
    if not settings.SIGNUP_OPEN and identity.email.lower() not in allowed:
        return _login_error("not_invited")

    projects = request.app.dependency_overrides.get(get_project_repository, get_project_repository)()
    user = await provision_google_user(
        store,
        projects,
        google_sub=identity.sub,
        email=identity.email,
        name=identity.name,
        owner_emails=owners,
        super_emails=supers,
        project_name=get_platform_settings().CREATOR_PROJECT_NAME,
    )
    if user.disabled_at is not None:
        return _login_error("disabled")
    await _revoke_presented_session(request)
    value, _ = await create_session(store, user.user_id, ttl_days=settings.SESSION_TTL_DAYS)
    default_home = "/" if user.account_type == "super" else "/create"
    response = RedirectResponse(safe_next(pending.next_path, default_home) if pending.next_path != "/" else default_home, status_code=302)
    _set_session_cookie(response, value, settings)
    return response


@router.get("/me")
async def me(request: Request, settings: Settings = Depends(get_settings)) -> dict:
    """The signed-in principal: who, which account type, and what the server enforces for this session."""
    from cf_platform.core.accounts import get_principal

    principal = get_principal()
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})  # type: ignore[return-value]
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "account_type": principal.account_type,
        "effective_type": principal.effective_type,
        "view_as_basic": principal.view_as_basic,
        "terms_accepted": principal.terms_accepted,
        "terms_version": settings.TERMS_VERSION,
        "abuse_contact": settings.ABUSE_CONTACT_EMAIL,
        "is_owner": principal.is_owner,
    }


@router.post("/view-as")
async def view_as(body: ViewAsRequest, request: Request) -> JSONResponse:
    """Switch this session between its own account type and Basic (View as Basic, D118).

    Only a Super account may do it, and it narrows that one session; it changes no
    data and never charges. Checked against the account's own type, not the effective
    one — otherwise a Super viewing as Basic could not switch back.
    """
    from cf_platform.core.accounts import ACCOUNT_SUPER, get_principal, hash_token, token_from_cookie

    principal = get_principal()
    if principal is None or principal.account_type != ACCOUNT_SUPER:
        return JSONResponse(status_code=403, content={"detail": "This needs a Super account."})
    token = token_from_cookie(request.cookies.get(AUTH_COOKIE_NAME, ""))
    if not token:
        return JSONResponse(
            status_code=409, content={"detail": "Sign in again to use View as Basic (this session cannot hold it)."}
        )
    store = _account_store(request)
    session = await store.get_session(hash_token(token))
    if session is None:
        return JSONResponse(status_code=409, content={"detail": "Session not found."})
    await store.save_session(session.model_copy(update={"view_as_basic": body.basic}))
    return JSONResponse(content={"ok": True, "view_as_basic": body.basic})


@router.post("/terms/accept")
async def accept_terms(request: Request, settings: Settings = Depends(get_settings)) -> JSONResponse:
    """Record that the signed-in user accepted the terms version in force (S9, D115)."""
    from cf_platform.core.accounts import get_principal

    principal = get_principal()
    if principal is None:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    store = _account_store(request)
    user = await store.get_user(principal.user_id)
    if user is None:
        return JSONResponse(status_code=404, content={"detail": "Account not found."})
    await store.save_user(
        user.model_copy(update={"terms_version": settings.TERMS_VERSION, "terms_accepted_at": datetime.now(UTC)})
    )
    return JSONResponse(content={"ok": True, "terms_version": settings.TERMS_VERSION})
