"""Cookie-based authentication helpers — sign and verify the session cookie."""

import hashlib
import hmac

AUTH_COOKIE_NAME = "cf_session"


def sign_cookie(secret_key: str) -> str:
    """Return an HMAC-SHA256 hex digest of the constant 'authenticated' token.

    The value is stable for a given secret key — logout is enforced by deleting the cookie,
    not by tracking session state server-side.
    """
    return hmac.new(secret_key.encode(), b"authenticated", hashlib.sha256).hexdigest()


def verify_cookie(cookie_value: str, secret_key: str) -> bool:
    """Return True if cookie_value matches the expected HMAC token for secret_key."""
    expected = sign_cookie(secret_key)
    return hmac.compare_digest(cookie_value, expected)
