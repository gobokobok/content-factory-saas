"""Cookie-based authentication helpers — sign and verify the session cookie."""

import hashlib
import hmac
import time

AUTH_COOKIE_NAME = "cf_session"


def passwords_match(candidate: str, expected: str) -> bool:
    """Compare the submitted password against the operator password in constant time.

    A plain ``!=`` short-circuits on the first differing byte, which leaks
    prefix-length information through response timing.
    """
    return hmac.compare_digest(candidate.encode(), expected.encode())


class LoginRateLimiter:
    """Fixed-window, per-client-IP tracker of failed login attempts.

    In-memory by design: Railway runs a single process per service instance
    (same pattern as _ACQUISITION_STATE / _RENDER_STATE), and a container
    restart resetting the window is an acceptable trade-off for a
    single-operator tool.
    """

    def __init__(self) -> None:
        """Initialise with no recorded failures."""
        self._failures: dict[str, list[float]] = {}

    def _prune(self, ip: str, window_seconds: float, now: float) -> None:
        """Drop failures older than the window for this ip."""
        cutoff = now - window_seconds
        kept = [t for t in self._failures.get(ip, []) if t > cutoff]
        if kept:
            self._failures[ip] = kept
        else:
            self._failures.pop(ip, None)

    def is_blocked(self, ip: str, max_attempts: int, window_seconds: float) -> bool:
        """Return True if this ip has reached max_attempts failures within the window."""
        now = time.monotonic()
        self._prune(ip, window_seconds, now)
        return len(self._failures.get(ip, [])) >= max_attempts

    def record_failure(self, ip: str, window_seconds: float) -> None:
        """Record one failed login attempt for this ip."""
        now = time.monotonic()
        self._prune(ip, window_seconds, now)
        self._failures.setdefault(ip, []).append(now)

    def reset(self, ip: str) -> None:
        """Clear recorded failures for this ip (called on successful login)."""
        self._failures.pop(ip, None)

    def clear(self) -> None:
        """Clear all recorded failures (test isolation helper)."""
        self._failures.clear()


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
