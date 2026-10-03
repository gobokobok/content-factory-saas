"""Shared fixtures-as-functions for the Sprint P12 route tests (projects, shortlist, runs)."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi.testclient import TestClient

from cf_platform.core.projects import InMemoryProjectRepository
from cf_platform.core.run_manager import InMemoryRunRepository
from cf_platform.core.shortlist import InMemoryShortlistRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_project_repository,
    get_run_repository,
    get_shortlist_repository,
)
from src.config import Settings, get_settings
from src.main import app

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "fake-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels",
    "REPLICATE_API_TOKEN": "fake-replicate",
    "FREESOUND_API_KEY": "fake-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret",
}


@dataclass
class P12Env:
    """A TestClient wired to fresh in-memory project, run and shortlist repositories."""

    client: TestClient
    projects: InMemoryProjectRepository
    runs: InMemoryRunRepository
    shortlist: InMemoryShortlistRepository

    def create_project(self, name: str = "Housing", niche: str = "housing economics") -> str:
        """Create a project through the API and return its id."""
        r = self.client.post("/platform/projects", json={"name": name, "niche": niche})
        assert r.status_code == 201, r.text
        return r.json()["project_id"]

    def add_item(self, project_id: str, title: str = "Why starter homes vanished", **fields: str) -> str:
        """Add a shortlist item through the API and return its id."""
        r = self.client.post(f"/platform/projects/{project_id}/shortlist", json={"title": title, **fields})
        assert r.status_code == 201, r.text
        return r.json()["item_id"]


@contextmanager
def p12_env() -> Iterator[P12Env]:
    """Yield a P12Env; the dependency overrides are removed again on exit."""
    projects = InMemoryProjectRepository(PLATFORM_USER_ID)
    runs = InMemoryRunRepository()
    shortlist = InMemoryShortlistRepository()
    overrides = {
        get_settings: lambda: Settings.model_validate(VALID_ENV),
        get_project_repository: lambda: projects,
        get_run_repository: lambda: runs,
        get_shortlist_repository: lambda: shortlist,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield P12Env(TestClient(app, raise_server_exceptions=True), projects, runs, shortlist)
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)
