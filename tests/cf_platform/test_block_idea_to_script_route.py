"""Tests for P5-S5: POST /platform/blocks/idea-to-script and Telegram /script formatters.

Covers:
- format_script_reply: shows title, score, script text
- format_script_reply: truncates long scripts to _SCRIPT_REPLY_CHAR_LIMIT
- format_script_running: includes idea_title
- format_script_usage: usage hint present
- parse_script_command: parses /script <idea_title>
- parse_script_command: bare /script returns empty string
- parse_script_command: non-/script text returns None
- POST /platform/blocks/idea-to-script: 200 response shape (run_id, script_artifact_key, script, iterations)
- Response run_id is a UUID
- Response script_artifact_key embeds run_id
- Response script text is non-empty
- Response iterations is int >= 0
- Optional niche stored in run inputs
- build_idea_to_script_graph compiles with registered workers
- build_idea_to_script_graph raises WorkerNotRegisteredError without registered workers
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.schemas import WorkerOutput
from cf_platform.interfaces.api import get_artifact_storage
from cf_platform.interfaces.telegram import (
    format_script_reply,
    format_script_running,
    format_script_usage,
    parse_script_command,
)
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.script_quality_scorer import ScriptDraftScore, ScriptScoresArtifact
from cf_platform.workers.script_writer import ScriptDraft, ScriptDraftsArtifact
from src.config import Settings, get_settings
from src.main import app

_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)
_IDEA_TITLE = "Why Starter Homes Vanished"
_SCRIPT_TEXT = (
    "In 1980, the average American could afford a home after 3 years of saving. "
    "Today it takes 12. Here is why the starter home has all but disappeared."
)

_VALID_ENV = {
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

_PLATFORM_SETTINGS_BASE = {
    "R2_ACCOUNT_ID": "fake-account-id",
    "R2_ACCESS_KEY_ID": "fake-access-key",
    "R2_SECRET_ACCESS_KEY": "fake-secret-key",
    "R2_BUCKET_NAME": "content-factory-dev",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
}


def _make_script_artifact(script: str = _SCRIPT_TEXT, overall_score: float = 8.5) -> ScriptArtifact:
    return ScriptArtifact(
        idea_title=_IDEA_TITLE,
        niche="US housing",
        script=script,
        draft_number=1,
        overall_score=overall_score,
        generated_at=_NOW,
    )


@contextmanager
def _stub_idea_to_script_workers() -> Generator:
    """Patch all five builder factories with deterministic stubs (no Claude calls)."""
    drafts_artifact = ScriptDraftsArtifact(
        idea_title=_IDEA_TITLE, niche=None, idea_angle=None,
        drafts=[ScriptDraft(draft_number=1, script=_SCRIPT_TEXT)],
        generated_at=_NOW,
    )
    scores_artifact = ScriptScoresArtifact(
        idea_title=_IDEA_TITLE,
        scored_drafts=[ScriptDraftScore(
            draft_number=1, hook_strength=9.0, data_quality=9.0,
            narrative_flow=9.0, virality_potential=9.0, overall_score=9.0,
        )],
        best_draft_number=1,
        best_score=9.0,
        generated_at=_NOW,
    )
    script_artifact = ScriptArtifact(
        idea_title=_IDEA_TITLE, niche=None, script=_SCRIPT_TEXT,
        draft_number=1, overall_score=9.0, generated_at=_NOW,
    )

    async def _stub_writer(state):
        return WorkerOutput(artifact=drafts_artifact)

    async def _stub_scorer(state):
        return WorkerOutput(artifact=scores_artifact, control="continue")  # type: ignore[arg-type]

    async def _stub_fact_checker(state):
        from cf_platform.workers.fact_checker import FactcheckReportArtifact
        return WorkerOutput(
            artifact=FactcheckReportArtifact(
                idea_title=_IDEA_TITLE, draft_number=1, claims=[],
                verified_count=0, refuted_count=0, unverifiable_count=0, checked_at=_NOW,
            ),
            control="continue",  # type: ignore[arg-type]
        )

    async def _stub_refiner(state):
        return WorkerOutput(artifact=drafts_artifact)

    async def _stub_packager(state):
        return WorkerOutput(artifact=script_artifact)

    with (
        patch("cf_platform.blocks.idea_to_script.build_script_writer_worker", return_value=_stub_writer),
        patch("cf_platform.blocks.idea_to_script.build_script_quality_scorer_worker", return_value=_stub_scorer),
        patch("cf_platform.blocks.idea_to_script.build_fact_checker_worker", return_value=_stub_fact_checker),
        patch("cf_platform.blocks.idea_to_script.build_script_refiner_worker", return_value=_stub_refiner),
        patch("cf_platform.blocks.idea_to_script.build_script_packager_worker", return_value=_stub_packager),
    ):
        yield


# ── format_script_reply ───────────────────────────────────────────────────


class TestFormatScriptReply:
    def test_shows_idea_title(self):
        text = format_script_reply(_make_script_artifact())
        assert _IDEA_TITLE in text

    def test_shows_score(self):
        text = format_script_reply(_make_script_artifact(overall_score=8.5))
        assert "8.5" in text

    def test_shows_script_text(self):
        text = format_script_reply(_make_script_artifact())
        assert _SCRIPT_TEXT in text

    def test_truncates_long_script(self):
        long_script = "x" * 5000
        text = format_script_reply(_make_script_artifact(script=long_script))
        assert len(text) <= 4003  # limit + "..." overhead

    def test_short_script_not_truncated(self):
        text = format_script_reply(_make_script_artifact())
        assert text.endswith(_SCRIPT_TEXT)


# ── parse_script_command ──────────────────────────────────────────────────


class TestParseScriptCommand:
    def test_parses_idea_title(self):
        assert parse_script_command("/script Why starter homes vanished") == "Why starter homes vanished"

    def test_strips_whitespace(self):
        assert parse_script_command("  /script   idea title  ") == "idea title"

    def test_bare_command_returns_empty_string(self):
        assert parse_script_command("/script") == ""

    def test_non_script_command_returns_none(self):
        assert parse_script_command("/ideas niche") is None

    def test_unrelated_text_returns_none(self):
        assert parse_script_command("hello world") is None


class TestFormatScriptRunning:
    def test_contains_idea_title(self):
        text = format_script_running(_IDEA_TITLE)
        assert _IDEA_TITLE in text


class TestFormatScriptUsage:
    def test_contains_script_command(self):
        text = format_script_usage()
        assert "/script" in text


# ── POST /platform/blocks/idea-to-script ─────────────────────────────────


class TestIdeaToScriptRoute:
    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=True)
        self.storage = InMemoryArtifactStorage()
        app.dependency_overrides[get_artifact_storage] = lambda: self.storage
        app.dependency_overrides[get_settings] = lambda: Settings(**_VALID_ENV)
        app.dependency_overrides[get_platform_settings] = lambda: PlatformSettings(
            **_PLATFORM_SETTINGS_BASE
        )

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _post(self, payload: dict) -> dict:
        with _stub_idea_to_script_workers():
            resp = self.client.post(
                "/platform/blocks/idea-to-script",
                json=payload,
                cookies={"session": "ignored"},
            )
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_returns_200_with_required_fields(self):
        body = self._post({"idea_title": _IDEA_TITLE})
        assert "run_id" in body
        assert "script_artifact_key" in body
        assert "script" in body
        assert "iterations" in body

    def test_run_id_is_uuid(self):
        body = self._post({"idea_title": _IDEA_TITLE})
        uuid.UUID(body["run_id"])  # raises ValueError if invalid

    def test_script_artifact_key_contains_run_id(self):
        body = self._post({"idea_title": _IDEA_TITLE})
        assert body["run_id"] in body["script_artifact_key"]

    def test_script_text_is_non_empty(self):
        body = self._post({"idea_title": _IDEA_TITLE})
        assert len(body["script"]) > 0

    def test_iterations_is_int(self):
        body = self._post({"idea_title": _IDEA_TITLE})
        assert isinstance(body["iterations"], int)
        assert body["iterations"] >= 0

    def test_optional_niche_accepted(self):
        body = self._post({"idea_title": _IDEA_TITLE, "niche": "US housing"})
        assert body["run_id"]  # just verify success — niche stored in run inputs


# ── build_idea_to_script_graph ────────────────────────────────────────────


class TestBuildIdeaToScriptGraph:
    def test_compiles_with_registered_workers(self):
        from cf_platform.blocks.idea_to_script import build_idea_to_script_graph, register_idea_to_script_workers
        from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
        from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerRegistry

        storage = InMemoryArtifactStorage()
        registry = WorkerRegistry()
        register_idea_to_script_workers(registry)

        with _stub_idea_to_script_workers():
            graph = build_idea_to_script_graph(
                storage=storage,
                registry=registry,
                executions=InMemoryExecutionRepository(),
                artifact_repo=InMemoryArtifactRepository(),
                anthropic_api_key="fake-key",
            )
        assert graph is not None

    def test_raises_for_empty_registry(self):
        from cf_platform.blocks.idea_to_script import build_idea_to_script_graph
        from cf_platform.core.artifact_manager import InMemoryArtifactRepository, InMemoryArtifactStorage
        from cf_platform.core.worker_registry import InMemoryExecutionRepository, WorkerNotRegisteredError, WorkerRegistry

        with pytest.raises(WorkerNotRegisteredError):
            build_idea_to_script_graph(
                storage=InMemoryArtifactStorage(),
                registry=WorkerRegistry(),
                executions=InMemoryExecutionRepository(),
                artifact_repo=InMemoryArtifactRepository(),
                anthropic_api_key="fake-key",
            )
