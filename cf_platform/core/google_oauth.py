"""Google OAuth 2.0 authorization-code flow with PKCE (Sprint P-AUTH S1).

No new dependency: the code exchange is one HTTPS POST to Google's token endpoint,
made with ``requests`` (already a dependency). The ID token comes straight from
Google over TLS in that response, so — per Google's guidance for the server flow —
its claims are read without a signature check and then validated here (issuer,
audience, expiry, ``email_verified``).

Hard rules this module enforces by construction:
* ``redirect_uri`` is a configured value, never derived from the request;
* ``state`` is server-side, random and single use (cf_platform/core/accounts.py);
* PKCE S256 on every flow;
* ``next`` is an allow-list of same-site paths, so the callback is not an open redirect;
* the identity is the ``sub`` claim, not the e-mail.
"""

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
VALID_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
SCOPES = "openid email profile"

# Where a sign-in may land. A `next` that is not exactly one of these (or a path under
# one) falls back to "/" — never an absolute URL, never `//host`, never a backslash.
_NEXT_ALLOWED_PREFIXES = ("/create", "/studio", "/project", "/library", "/settings")


class GoogleAuthError(Exception):
    """A sign-in step failed in a way the user should see as a plain message."""


@dataclass(frozen=True)
class GoogleIdentity:
    """The verified identity Google returned."""

    sub: str
    email: str
    name: str


def safe_next(value: str | None, default: str = "/") -> str:
    """Return value when it is an allow-listed same-site path, else default."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value or "\n" in value:
        return default
    path = value.split("?", 1)[0].split("#", 1)[0]
    if path == "/" or any(path == p or path.startswith(p + "/") for p in _NEXT_ALLOWED_PREFIXES):
        return value
    return default


def new_state() -> str:
    """A random single-use state value."""
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    """A PKCE code verifier (RFC 7636: 43-128 URL-safe characters)."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """The S256 PKCE challenge for verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def authorization_url(*, client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    """The Google URL to send the browser to. redirect_uri is the configured value."""
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTH_ENDPOINT}?{query}"


def _decode_claims(id_token: str) -> dict:
    """Read the claims of a JWT without verifying its signature (it came from Google over TLS)."""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception as exc:  # malformed token
        raise GoogleAuthError("Google sent a response we could not read.") from exc
    if not isinstance(claims, dict):
        raise GoogleAuthError("Google sent a response we could not read.")
    return claims


def identity_from_claims(claims: dict, *, client_id: str, now: float) -> GoogleIdentity:
    """Validate ID-token claims and return the identity. GoogleAuthError when any check fails."""
    if claims.get("iss") not in VALID_ISSUERS:
        raise GoogleAuthError("The sign-in response was not issued by Google.")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if client_id not in audiences:
        raise GoogleAuthError("The sign-in response was meant for another application.")
    try:
        if float(claims.get("exp", 0)) <= now:
            raise GoogleAuthError("The sign-in response has expired. Try again.")
    except (TypeError, ValueError):
        raise GoogleAuthError("The sign-in response has no valid expiry.") from None
    sub = str(claims.get("sub") or "")
    email = str(claims.get("email") or "")
    if not sub:
        raise GoogleAuthError("Google did not return an account id.")
    if not email or claims.get("email_verified") is not True:
        raise GoogleAuthError("Your Google e-mail address is not verified.")
    return GoogleIdentity(sub=sub, email=email, name=str(claims.get("name") or ""))


def exchange_code(
    *,
    code: str,
    verifier: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    now: float,
    post=requests.post,
) -> GoogleIdentity:
    """Exchange an authorization code for the user's identity (blocking — call via a thread).

    `post` is injectable for tests. GoogleAuthError on any failure.
    """
    try:
        response = post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GoogleAuthError("Could not reach Google. Try again in a moment.") from exc
    if response.status_code != 200:
        raise GoogleAuthError("Google refused the sign-in. Try again.")
    id_token = (response.json() or {}).get("id_token")
    if not id_token:
        raise GoogleAuthError("Google did not return an identity.")
    return identity_from_claims(_decode_claims(id_token), client_id=client_id, now=now)
