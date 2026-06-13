"""Tests for cf_platform/interfaces/api.py and its fault-isolated mount in src/main.py (P1-S1)."""

import sys
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import _mount_platform_router, app


@pytest.fixture(autouse=True)
def _clear_settings_override():
    """Remove the get_settings dependency override after each test."""
    yield
    app.dependency_overrides.pop(get_settings, None)

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
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}


def _client_with_settings() -> TestClient:
    """Return a TestClient for the main app with valid settings injected via Depends override."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    return TestClient(app)


class TestPlatformHealthRoute:
    def test_platform_health_returns_200(self):
        """GET /platform/health returns 200 with status ok and a database field."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["database"] in ("ok", "unavailable")

    def test_platform_health_ok_when_database_unset(self):
        """GET /platform/health reports status ok and database unavailable when DATABASE_URL is unset (D048)."""
        client = _client_with_settings()

        response = client.get("/platform/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "unavailable"}

    def test_legacy_route_unaffected(self):
        """Mounting the platform router does not break an existing legacy route."""
        client = _client_with_settings()

        response = client.get("/health")

        assert response.status_code == 200


class TestMountPlatformRouterFaultIsolation:
    def test_mount_succeeds_registers_route(self):
        """Normal mount registers /platform/health on a fresh app."""
        fresh_app = FastAPI()

        _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_mount_failure_is_swallowed(self):
        """An import failure in cf_platform.interfaces.api does not raise."""
        fresh_app = FastAPI()

        with patch.dict(sys.modules, {"cf_platform.interfaces.api": None}):
            _mount_platform_router(fresh_app)

        client = TestClient(fresh_app)
        response = client.get("/platform/health")
        assert response.status_code == 404
