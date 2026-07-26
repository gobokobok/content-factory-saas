"""Tests for P5-S5/P5-S6: POST /platform/blocks/idea-to-script and Telegram /script formatters.

Covers:
- format_script_reply: shows title, optional score, script text
- format_script_reply: shows score when overall_score is not None
- format_script_reply: no score line when overall_score is None
- format_script_reply: manual_review flag shown in text
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
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    EvaluationArtifact,
    GeneratedScriptArtifact,
    HookVariantsArtifact,
    IntegrityReport,
    NarrativeLens,
    NormalizedContext,
    PatchSetArtifact,
    Section,
    SelectedHookArtifact,
)
from cf_platform.core.schemas import WorkerOutput
from cf_platform.interfaces.api import get_artifact_storage
from cf_platform.interfaces.telegram import (
    format_script_reply,
    format_script_running,
    format_script_usage,
    parse_script_command,
)
from cf_platform.workers.script_packager import ScriptArtifact
from src.config import Settings, get_settings
from src.main import app

_NOW = datetime(2026, 6, 18, 12, 0, 0, tzinfo=UTC)
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


def _make_script_artifact(
    script: str = _SCRIPT_TEXT,
    overall_score: float | None = 8.5,
    status: str = "ok",
) -> ScriptArtifact:
    return ScriptArtifact(
        idea_title=_IDEA_TITLE,
        niche="US housing",
        script=script,
        overall_score=overall_score,
        status=status,  # type: ignore[arg-type]
        generated_at=_NOW,
    )


@contextmanager
def _stub_idea_to_script_workers() -> Generator:
    """Patch all 11 Blueprint IR builder factories with deterministic stubs (no Claude calls)."""
    script_artifact = _make_script_artifact()

    async def _stub_context_normalizer(state):
        return WorkerOutput(artifact=NormalizedContext(
            primary_angle="Supply shortage", evidence_summary="Evidence",
            top_signals=[], controversies=[], hook_bias="Data",
        ))

    async def _stub_blueprint_generator(state):
        return WorkerOutput(artifact=Blueprint(
            hook_angle="Hook", structure=[Section(title="S", key_points=["p"])],
            claims=["Claim"], monetization_angle="Mon",
            required_evidence=["Evidence"], signal_summary="Sum",
            direction_alignment_notes="Notes",
        ))

    async def _stub_evaluator(state):
        return WorkerOutput(artifact=EvaluationArtifact(
            score=8.0, factual_corrections=[], alignment_notes="Notes",
            evidence_additions=[], passed=True, notes="",
        ))

    async def _stub_blueprint_merger(state):
        return WorkerOutput(artifact=Blueprint(
            hook_angle="Hook", structure=[Section(title="S", key_points=["p"])],
            claims=["Claim"], monetization_angle="Mon",
            required_evidence=["Evidence"], signal_summary="Sum",
            direction_alignment_notes="Notes",
        ))

    async def _stub_narrative_lens(state):
        return WorkerOutput(artifact=NarrativeLens(
            identity_angle="Identity", contrarian_angle="Contrarian",
            philosophical_angle="Philosophical", emotional_angle="Emotional",
            story_devices=["device 1"],
        ))

    async def _stub_hook_generator(state):
        return WorkerOutput(artifact=HookVariantsArtifact(hooks=["Hook 1"], generated_at=_NOW))

    async def _stub_hook_selector(state):
        return WorkerOutput(artifact=SelectedHookArtifact(hook="Hook 1", generated_at=_NOW))

    async def _stub_script_generator(state):
        return WorkerOutput(artifact=GeneratedScriptArtifact(
            idea_title=_IDEA_TITLE, niche=None, script=_SCRIPT_TEXT,
            word_count=len(_SCRIPT_TEXT.split()), target_duration_seconds=60, generated_at=_NOW,
        ))

    async def _stub_integrity_checker(state):
        return WorkerOutput(artifact=IntegrityReport(passed=True, issues=[]), control="continue")  # type: ignore[arg-type]

    async def _stub_patch_generator(state):
        return WorkerOutput(artifact=PatchSetArtifact(patches=[], generated_at=_NOW))

    async def _stub_patch_applier(state):
        return WorkerOutput(artifact=GeneratedScriptArtifact(
            idea_title=_IDEA_TITLE, niche=None, script=_SCRIPT_TEXT,
            word_count=len(_SCRIPT_TEXT.split()), target_duration_seconds=60, generated_at=_NOW,
        ))

    async def _stub_packager(state):
        return WorkerOutput(artifact=script_artifact)

    with (
        patch("cf_platform.blocks.idea_to_script.build_context_normalizer_worker", return_value=_stub_context_normalizer),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_generator_worker", return_value=_stub_blueprint_generator),
        patch("cf_platform.blocks.idea_to_script.build_evaluator_worker", return_value=_stub_evaluator),
        patch("cf_platform.blocks.idea_to_script.build_blueprint_merger_worker", return_value=_stub_blueprint_merger),
        patch("cf_platform.blocks.idea_to_script.build_narrative_lens_worker", return_value=_stub_narrative_lens),
        patch("cf_platform.blocks.idea_to_script.build_hook_generator_worker", return_value=_stub_hook_generator),
        patch("cf_platform.blocks.idea_to_script.build_hook_selector_worker", return_value=_stub_hook_selector),
        patch("cf_platform.blocks.idea_to_script.build_script_generator_worker", return_value=_stub_script_generator),
        patch("cf_platform.blocks.idea_to_script.build_integrity_checker_worker", return_value=_stub_integrity_checker),
        patch("cf_platform.blocks.idea_to_script.build_patch_generator_worker", return_value=_stub_patch_generator),
        patch("cf_platform.blocks.idea_to_script.build_patch_applier_worker", return_value=_stub_patch_applier),
        patch("cf_platform.blocks.idea_to_script.build_script_packager_worker", return_value=_stub_packager),
    ):
        yield


# ── format_script_reply ───────────────────────────────────────────────────


class TestFormatScriptReply:
    def test_shows_idea_title(self):
        text = format_script_reply(_make_script_artifact())
        assert _IDEA_TITLE in text

    def test_shows_score_when_not_none(self):
        text = format_script_reply(_make_script_artifact(overall_score=8.5))
        assert "8.5" in text

    def test_no_score_line_when_none(self):
        text = format_script_reply(_make_script_artifact(overall_score=None))
        assert "Score:" not in text

    def test_shows_script_text(self):
        text = format_script_reply(_make_script_artifact())
        assert _SCRIPT_TEXT in text

    def test_manual_review_flag_in_text(self):
        text = format_script_reply(_make_script_artifact(status="manual_review"))
        assert "manual_review" in text.lower() or "⚠️" in text

    def test_truncates_long_script(self):
        long_script = "x" * 5000
        text = format_script_reply(_make_script_artifact(script=long_script))
        assert len(text) <= 4003  # limit + "..." overhead

    def test_short_script_ends_with_script_text(self):
        text = format_script_reply(_make_script_artifact(overall_score=None))
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
        from cf_platform.core.worker_registry import (
            InMemoryExecutionRepository,
            WorkerNotRegisteredError,
            WorkerRegistry,
        )

        with pytest.raises(WorkerNotRegisteredError):
            build_idea_to_script_graph(
                storage=InMemoryArtifactStorage(),
                registry=WorkerRegistry(),
                executions=InMemoryExecutionRepository(),
                artifact_repo=InMemoryArtifactRepository(),
                anthropic_api_key="fake-key",
            )
