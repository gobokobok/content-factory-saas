"""P-HARD2-S2 / S3 — start-up validators, run_id pattern, cookie Secure, proxy-aware lockout,
legacy routes off by default, capped uploads, migration status in /health, container and CI."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.config import Settings, check_deployment_settings, get_settings
from src.main import app

ROOT = Path(__file__).resolve().parent.parent

_BASE = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "a",
    "R2_ACCESS_KEY_ID": "b",
    "R2_SECRET_ACCESS_KEY": "c",
    "R2_BUCKET_NAME": "d",
    "ANTHROPIC_API_KEY": "e",
    "PEXELS_API_KEY": "f",
    "REPLICATE_API_TOKEN": "g",
    "FREESOUND_API_KEY": "h",
    "OPERATOR_PASSWORD": "a-long-enough-password",
    "SESSION_SECRET_KEY": "a-long-enough-session-secret",
    # Explicit: the suite's environment sets these to the permissive test values.
    "AUTH_SECRET_MIN_LENGTH": 12,
    "COOKIE_ALLOW_INSECURE": False,
}


def _settings(**overrides) -> Settings:
    """Build Settings from a dict (bypasses the environment)."""
    return Settings.model_validate({**_BASE, **overrides})


# ─── S2 / F7 — deployment settings ────────────────────────────────────────────

class TestDeploymentSettings:
    def test_strong_values_pass(self):
        """Long secrets on dev are accepted."""
        assert check_deployment_settings(_settings()).ENVIRONMENT == "dev"

    @pytest.mark.parametrize("name", ["OPERATOR_PASSWORD", "SESSION_SECRET_KEY"])
    def test_short_secret_refused(self, name):
        """A secret under the minimum length stops start-up."""
        with pytest.raises(ValueError, match=name):
            check_deployment_settings(_settings(**{name: "short"}))

    @pytest.mark.parametrize("name", ["OPERATOR_PASSWORD", "SESSION_SECRET_KEY"])
    def test_empty_secret_refused_even_with_minimum_one(self, name):
        """An empty secret is refused whatever the configured minimum is."""
        with pytest.raises(ValueError, match=name):
            check_deployment_settings(_settings(**{name: "", "AUTH_SECRET_MIN_LENGTH": 0}))

    def test_error_does_not_contain_the_value(self):
        """The message names the variable, never its value."""
        with pytest.raises(ValueError) as exc:
            check_deployment_settings(_settings(OPERATOR_PASSWORD="hunter2"))
        assert "hunter2" not in str(exc.value)

    def test_prod_without_encryption_key_refused(self):
        """ENVIRONMENT=prod needs SETTINGS_ENCRYPTION_KEY."""
        with pytest.raises(ValueError, match="SETTINGS_ENCRYPTION_KEY"):
            check_deployment_settings(_settings(ENVIRONMENT="prod"))

    def test_prod_with_encryption_key_passes(self):
        """ENVIRONMENT=prod with the key is accepted."""
        check_deployment_settings(_settings(ENVIRONMENT="prod", SETTINGS_ENCRYPTION_KEY="k"))

    def test_dev_without_encryption_key_passes(self):
        """dev may start without the key (the Settings page warns instead)."""
        check_deployment_settings(_settings(SETTINGS_ENCRYPTION_KEY=""))

    def test_get_settings_applies_the_check(self, monkeypatch):
        """get_settings() — the start-up path — raises for a short password."""
        monkeypatch.setenv("AUTH_SECRET_MIN_LENGTH", "12")
        monkeypatch.setenv("OPERATOR_PASSWORD", "short")
        with pytest.raises(ValueError, match="OPERATOR_PASSWORD"):
            get_settings()


# ─── S2 / F9 — run_id pattern ─────────────────────────────────────────────────

class TestRunIdPattern:
    @pytest.mark.parametrize("path", [
        "/platform/workers/render",
        "/platform/workers/voice",
        "/platform/workers/storyboard",
        "/platform/workers/acquisition",
        "/platform/workers/metadata",
    ])
    @pytest.mark.parametrize("bad", ["../../etc", "a/b", "run id", "x" * 200, ""])
    def test_bad_run_id_is_422(self, path, bad):
        """A run id with a path separator, dots, spaces or an absurd length is rejected."""
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(path, json={"run_id": bad})
        assert r.status_code == 422

    def test_pattern_accepts_uuid_and_legacy_ids(self):
        """A uuid and a {date}_{slug} legacy id both match."""
        import re

        from cf_platform.interfaces.routes._run_id import RUN_ID_PATTERN

        assert re.match(RUN_ID_PATTERN, "6fe35dab-1111-2222-3333-444444444444")
        assert re.match(RUN_ID_PATTERN, "2026-10-13_housing-costs")


# ─── S2 / F18, F14 — cookie and lockout ───────────────────────────────────────

def _login_client(**settings_overrides) -> TestClient:
    """Return a TestClient with settings injected."""
    s = _settings(**settings_overrides)
    app.dependency_overrides[get_settings] = lambda: s
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clear_overrides():
    """Drop the settings override after each test."""
    yield
    app.dependency_overrides.pop(get_settings, None)


class TestCookieAndLockout:
    def test_cookie_secure_on_dev(self):
        """DEV is https: the session cookie is Secure unless insecure is allowed."""
        client = _login_client()
        r = client.post("/auth/login", json={"password": _BASE["OPERATOR_PASSWORD"]})
        assert r.status_code == 200
        assert "secure" in r.headers["set-cookie"].lower()

    def test_cookie_not_secure_when_insecure_allowed(self):
        """Local http development can opt out."""
        client = _login_client(COOKIE_ALLOW_INSECURE=True)
        r = client.post("/auth/login", json={"password": _BASE["OPERATOR_PASSWORD"]})
        assert "secure" not in r.headers["set-cookie"].lower()

    def test_lockout_is_per_forwarded_client(self):
        """Five bad tries from one forwarded address do not lock out another one."""
        client = _login_client(LOGIN_MAX_ATTEMPTS=3)
        attacker = {"x-forwarded-for": "203.0.113.9"}
        for _ in range(3):
            assert client.post("/auth/login", json={"password": "x"}, headers=attacker).status_code == 401
        assert client.post("/auth/login", json={"password": "x"}, headers=attacker).status_code == 429
        operator = {"x-forwarded-for": "198.51.100.7"}
        r = client.post("/auth/login", json={"password": _BASE["OPERATOR_PASSWORD"]}, headers=operator)
        assert r.status_code == 200

    def test_client_supplied_prefix_does_not_dodge_the_lockout(self):
        """The right-most entry is the proxy's; extra left-hand entries change nothing."""
        client = _login_client(LOGIN_MAX_ATTEMPTS=2)
        for i in range(2):
            h = {"x-forwarded-for": f"10.0.0.{i}, 203.0.113.9"}
            assert client.post("/auth/login", json={"password": "x"}, headers=h).status_code == 401
        h = {"x-forwarded-for": "10.9.9.9, 203.0.113.9"}
        assert client.post("/auth/login", json={"password": "x"}, headers=h).status_code == 429

    def test_proxy_headers_ignored_when_not_trusted(self):
        """With TRUST_PROXY_HEADERS off the lockout keys on the socket address."""
        client = _login_client(LOGIN_MAX_ATTEMPTS=2, TRUST_PROXY_HEADERS=False)
        for i in range(2):
            h = {"x-forwarded-for": f"203.0.113.{i}"}
            client.post("/auth/login", json={"password": "x"}, headers=h)
        h = {"x-forwarded-for": "203.0.113.200"}
        assert client.post("/auth/login", json={"password": "x"}, headers=h).status_code == 429


# ─── S2 / F3, F10 — legacy routes off by default ──────────────────────────────

def _route_paths(legacy_flag: str | None) -> set[str]:
    """Import src.main in a clean interpreter with the flag and list its route paths."""
    env = {**os.environ}
    env.pop("LEGACY_ROUTES_ENABLED", None)
    if legacy_flag is not None:
        env["LEGACY_ROUTES_ENABLED"] = legacy_flag
    code = (
        f"import sys, json; sys.path.insert(0, {str(ROOT)!r}); from src.main import app; "
        "paths = {getattr(r,'path','') or '' for r in app.routes}; "
        "paths |= set(app.openapi()['paths']); "
        "print(json.dumps(sorted(paths)))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, check=True,
    )
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


class TestLegacyRoutes:
    def test_off_by_default_keeps_only_studio_routes(self):
        """No /legacy, no run list, no upload URLs; delete and settings stay for Studio."""
        paths = _route_paths(None)
        assert "/legacy" not in paths
        assert "/runs" not in paths
        assert "/runs/{run_id}/download" not in paths
        assert "/runs/{run_id}/voiceover-upload-url" not in paths
        assert "/runs/{run_id}/render" not in paths
        assert "/runs/{run_id}" in paths
        assert "/runs/{run_id}/settings" in paths

    def test_flag_mounts_them(self):
        """LEGACY_ROUTES_ENABLED=true brings the legacy surface back."""
        paths = _route_paths("true")
        assert "/legacy" in paths
        assert "/runs" in paths
        assert "/runs/{run_id}/download" in paths


# ─── S2 / F12 — capped uploads ────────────────────────────────────────────────

class _FakeUpload:
    """A minimal UploadFile stand-in that counts how much was read."""

    def __init__(self, size: int) -> None:
        self.remaining = size
        self.read_total = 0

    async def read(self, n: int = -1) -> bytes:
        """Return up to n bytes of zeros."""
        take = min(n if n > 0 else self.remaining, self.remaining)
        self.remaining -= take
        self.read_total += take
        return b"\0" * take


class TestCappedUpload:
    def test_stops_early_past_the_limit(self):
        """A 100 MB body against a 2 MB limit is abandoned after ~3 MB, not read whole."""
        from cf_platform.interfaces.routes.studio import _read_upload_capped

        up = _FakeUpload(100 * 1024 * 1024)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_read_upload_capped(up, 2 * 1024 * 1024, "2 MB"))
        assert exc.value.status_code == 422
        assert up.read_total <= 3 * 1024 * 1024

    def test_returns_the_bytes_under_the_limit(self):
        """A file under the limit comes back whole."""
        from cf_platform.interfaces.routes.studio import _read_upload_capped

        data = asyncio.run(_read_upload_capped(_FakeUpload(1500), 2 * 1024 * 1024, "2 MB"))
        assert len(data) == 1500


# ─── S3 / F11 — migration status ──────────────────────────────────────────────

def _fake_pool(execute: AsyncMock | None = None, fail: bool = False):
    """Return (pool, cursor) mocks shaped like psycopg's async pool."""
    cur = MagicMock()
    cur.execute = execute or AsyncMock()
    cur.fetchall = AsyncMock(return_value=[])
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cur)
    conn.commit = AsyncMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.closed = False
    if fail:
        pool.connection = MagicMock(side_effect=RuntimeError("boom"))
    else:
        pool.connection = MagicMock(return_value=conn)
    return pool, cur


class TestMigrationStatus:
    def test_ok_run_is_reported_and_takes_the_advisory_lock_first(self):
        """The lock statement is the first thing executed; status becomes "ok"."""
        from cf_platform.core import migrations

        pool, cur = _fake_pool()
        with patch.object(migrations, "get_pool", return_value=pool), \
             patch.object(migrations, "list_migrations", return_value=[]):
            assert asyncio.run(migrations.run_migrations("postgres://x")) == "ok"
        first_sql = cur.execute.await_args_list[0].args[0]
        assert "pg_advisory_xact_lock" in first_sql
        assert migrations.get_migration_status() == "ok"

    def test_failed_run_is_reported_as_error(self):
        """A database error during migration leaves the status at "error"."""
        from cf_platform.core import migrations

        pool, _ = _fake_pool(fail=True)
        with patch.object(migrations, "get_pool", return_value=pool):
            assert asyncio.run(migrations.run_migrations("postgres://x")) == "error"
        assert migrations.get_migration_status() == "error"

    def test_no_database_is_unavailable(self):
        """No DATABASE_URL: "unavailable", not an error."""
        from cf_platform.core import migrations

        assert asyncio.run(migrations.run_migrations("")) == "unavailable"
        assert migrations.get_migration_status() == "unavailable"


class TestHealthReportsMigrations:
    @pytest.mark.parametrize("status,expected", [
        ("ok", "ok"), ("unavailable", "ok"), ("not_run", "ok"), ("error", "degraded"),
    ])
    def test_health(self, status, expected):
        """/health carries the migration status; only "error" degrades it, HTTP stays 200."""
        client = _login_client()
        with patch("cf_platform.core.migrations.get_migration_status", return_value=status):
            r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["migrations"] == status
        assert body["status"] == expected

    def test_platform_health_degrades_on_error(self):
        """/platform/health says "degraded" for a failed migration."""
        client = _login_client()
        with patch("cf_platform.interfaces.routes.meta.get_migration_status", return_value="error"), \
             patch("cf_platform.interfaces.routes.meta.check_db_health", new=AsyncMock(return_value="ok")):
            r = client.get("/platform/health")
        assert r.json()["status"] == "degraded"
        assert r.json()["migrations"] == "error"


# ─── S3 / F20 — container and CI ──────────────────────────────────────────────

class TestContainerAndCi:
    def test_dockerfile_pins_base_and_drops_root(self):
        """The base image carries a digest and the last USER is not root."""
        text = (ROOT / "Dockerfile").read_text()
        from_line = next(line for line in text.splitlines() if line.startswith("FROM "))
        assert "@sha256:" in from_line
        users = [line.split()[1] for line in text.splitlines() if line.startswith("USER ")]
        assert users and users[-1] != "root"

    def test_ci_runs_pip_audit_warn_only(self):
        """pip-audit is in the CI workflow and cannot fail the build yet."""
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        assert "pip-audit" in text
        assert "continue-on-error: true" in text

    def test_cd_checks_health_after_deploy(self):
        """The CD workflow calls /health and fails on a degraded migration status."""
        text = (ROOT / ".github" / "workflows" / "cd.yml").read_text()
        assert "/health" in text and "migrations" in text
