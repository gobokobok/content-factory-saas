"""Tests for auth helpers, auth routes, and the auth middleware."""

from fastapi.testclient import TestClient

from src.auth import AUTH_COOKIE_NAME, sign_cookie, verify_cookie
from src.config import Settings, get_settings
from src.main import app

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels-key",
    "REPLICATE_API_TOKEN": "fake-replicate-token",
    "FREESOUND_API_KEY": "fake-freesound-key",
    "OPERATOR_PASSWORD": "correct-horse-battery",
    "SESSION_SECRET_KEY": "test-hmac-secret",
}

_SETTINGS = Settings.model_validate(VALID_ENV)


def _client() -> TestClient:
    """Return a TestClient with the test settings injected."""
    app.dependency_overrides[get_settings] = lambda: _SETTINGS
    return TestClient(app, raise_server_exceptions=False)


# ─── Unit tests: cookie helpers ───────────────────────────────────────────────

class TestCookieHelpers:
    def test_sign_cookie_returns_hex_string(self):
        """sign_cookie returns a non-empty hex string."""
        token = sign_cookie("secret")
        assert isinstance(token, str)
        assert len(token) == 64  # sha256 hex digest

    def test_verify_cookie_accepts_correct_token(self):
        """verify_cookie returns True for the token it produced."""
        token = sign_cookie("my-secret")
        assert verify_cookie(token, "my-secret") is True

    def test_verify_cookie_rejects_wrong_token(self):
        """verify_cookie returns False for an arbitrary string."""
        assert verify_cookie("bad-token", "my-secret") is False

    def test_verify_cookie_rejects_different_secret(self):
        """Token signed with one secret is invalid under another secret."""
        token = sign_cookie("secret-a")
        assert verify_cookie(token, "secret-b") is False

    def test_sign_cookie_is_deterministic(self):
        """Same secret always produces the same token."""
        assert sign_cookie("key") == sign_cookie("key")


# ─── POST /auth/login ─────────────────────────────────────────────────────────

class TestLogin:
    def test_correct_password_returns_200(self):
        """POST /auth/login with correct password returns 200 and ok: true."""
        client = _client()
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        assert res.status_code == 200
        assert res.json() == {"ok": True}

    def test_correct_password_sets_cookie(self):
        """Successful login sets the session cookie."""
        client = _client()
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        assert AUTH_COOKIE_NAME in res.cookies

    def test_cookie_value_matches_expected_hmac(self):
        """Cookie value equals sign_cookie(SESSION_SECRET_KEY)."""
        client = _client()
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        expected = sign_cookie("test-hmac-secret")
        assert res.cookies[AUTH_COOKIE_NAME] == expected

    def test_wrong_password_returns_401(self):
        """POST /auth/login with wrong password returns 401."""
        client = _client()
        res = client.post("/auth/login", json={"password": "wrong-password"})
        assert res.status_code == 401
        assert res.json()["ok"] is False

    def test_wrong_password_does_not_set_cookie(self):
        """Failed login must not set the session cookie."""
        client = _client()
        res = client.post("/auth/login", json={"password": "nope"})
        assert AUTH_COOKIE_NAME not in res.cookies


# ─── Login rate limiting ──────────────────────────────────────────────────────

class TestLoginRateLimit:
    def test_blocked_after_max_failed_attempts(self):
        """The attempt after LOGIN_MAX_ATTEMPTS failures returns 429."""
        client = _client()
        for _ in range(_SETTINGS.LOGIN_MAX_ATTEMPTS):
            res = client.post("/auth/login", json={"password": "wrong"})
            assert res.status_code == 401
        res = client.post("/auth/login", json={"password": "wrong"})
        assert res.status_code == 429
        assert res.json()["ok"] is False

    def test_blocked_even_with_correct_password(self):
        """Once blocked, even the correct password is rejected until the window passes."""
        client = _client()
        for _ in range(_SETTINGS.LOGIN_MAX_ATTEMPTS):
            client.post("/auth/login", json={"password": "wrong"})
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        assert res.status_code == 429
        assert AUTH_COOKIE_NAME not in res.cookies

    def test_successful_login_resets_counter(self):
        """A successful login clears prior failures for that IP."""
        client = _client()
        for _ in range(_SETTINGS.LOGIN_MAX_ATTEMPTS - 1):
            client.post("/auth/login", json={"password": "wrong"})
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        assert res.status_code == 200
        # Full budget of failures is available again.
        for _ in range(_SETTINGS.LOGIN_MAX_ATTEMPTS - 1):
            res = client.post("/auth/login", json={"password": "wrong"})
            assert res.status_code == 401

    def test_window_expiry_unblocks(self):
        """Failures older than the window no longer count toward the block."""
        from src.auth import LoginRateLimiter

        limiter = LoginRateLimiter()
        limiter.record_failure("1.2.3.4", window_seconds=900)
        # Age the recorded failure past the window by rewriting its timestamp.
        limiter._failures["1.2.3.4"] = [t - 901 for t in limiter._failures["1.2.3.4"]]
        assert limiter.is_blocked("1.2.3.4", max_attempts=1, window_seconds=900) is False


# ─── Constant-time password comparison ────────────────────────────────────────

class TestPasswordsMatch:
    def test_accepts_equal_passwords(self):
        """passwords_match returns True for identical strings."""
        from src.auth import passwords_match

        assert passwords_match("swordfish", "swordfish") is True

    def test_rejects_different_passwords(self):
        """passwords_match returns False for different strings, including prefixes."""
        from src.auth import passwords_match

        assert passwords_match("swordfish", "swordfish2") is False
        assert passwords_match("", "swordfish") is False
        assert passwords_match("sword", "swordfish") is False

    def test_handles_non_ascii(self):
        """passwords_match compares non-ASCII passwords correctly."""
        from src.auth import passwords_match

        assert passwords_match("pärole-🔑", "pärole-🔑") is True
        assert passwords_match("pärole", "parole") is False


# ─── POST /auth/logout ────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_returns_200(self):
        """POST /auth/logout returns 200 and ok: true."""
        client = _client()
        res = client.post("/auth/logout")
        assert res.status_code == 200
        assert res.json() == {"ok": True}

    def test_logout_clears_cookie(self):
        """After logout the session cookie is deleted (max-age=0 or absent)."""
        client = _client()
        # Log in first
        client.post("/auth/login", json={"password": "correct-horse-battery"})
        # Log out
        res = client.post("/auth/logout")
        # Cookie should be cleared (empty string or absent after deletion)
        assert res.cookies.get(AUTH_COOKIE_NAME, "") == ""


# ─── Auth middleware ──────────────────────────────────────────────────────────

class TestAuthMiddleware:
    def test_unauthenticated_api_request_returns_401(self):
        """Unauthenticated fetch-style request (no Accept: text/html) gets 401."""
        client = _client()
        res = client.get("/runs", headers={"Accept": "application/json"}, follow_redirects=False)
        assert res.status_code == 401

    def test_unauthenticated_browser_request_returns_302(self):
        """Unauthenticated browser request (Accept: text/html) gets 302 to /login."""
        client = _client()
        res = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["location"] == "/login"

    def test_health_is_exempt_from_auth(self):
        """GET /health requires no authentication."""
        client = _client()
        res = client.get("/health")
        assert res.status_code == 200

    def test_login_page_is_exempt_from_auth(self):
        """GET /login requires no authentication (serves login page)."""
        client = _client()
        res = client.get("/login")
        assert res.status_code == 200

    def test_auth_login_endpoint_is_exempt_from_auth(self):
        """POST /auth/login requires no authentication (so login can succeed)."""
        client = _client()
        res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        assert res.status_code == 200

    def test_authenticated_request_passes_through(self):
        """Valid session cookie allows access to gated routes."""
        client = _client()
        # Log in to get cookie
        login_res = client.post("/auth/login", json={"password": "correct-horse-battery"})
        token = login_res.cookies[AUTH_COOKIE_NAME]
        # Make authenticated request
        res = client.get(
            "/runs",
            headers={"Accept": "application/json"},
            cookies={AUTH_COOKIE_NAME: token},
        )
        # Route exists and cookie passes — should not be 401 or 302
        assert res.status_code != 401
        assert res.status_code != 302
