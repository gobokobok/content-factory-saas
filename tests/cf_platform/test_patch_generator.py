"""Tests for cf_platform/workers/patch_generator.py (P5-S6).

Covers:
- Happy path: reads script + report with medium/high issues, calls Claude, returns PatchSetArtifact
- Patches parsed from Claude JSON response
- Only medium/high severity issues sent to Claude (low ignored)
- No actionable issues → returns empty PatchSetArtifact without LLM call
- Invalid JSON from Claude → graceful fallback to empty PatchSetArtifact (no raise)
- Missing generated_script artifact ref → KeyError
- Missing integrity_report artifact ref → KeyError
- Registration: model='claude-haiku-4-5'
- build_patch_generator_worker returns a callable
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import (
    GeneratedScriptArtifact,
    IntegrityIssue,
    IntegrityReport,
    Patch,
    PatchSetArtifact,
)
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.patch_generator import (
    PATCH_GENERATOR_REGISTRATION,
    build_patch_generator_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-001", worker="test", worker_version="1.0.0", prompt_version="v1",
    model="none", created_at=_NOW,
)
_SCRIPT = "In 1980 homes were affordable and starter homes were common."


def _make_script() -> GeneratedScriptArtifact:
    return GeneratedScriptArtifact(
        idea_title="Why Starter Homes Vanished", niche="housing",
        script=_SCRIPT, word_count=len(_SCRIPT.split()),
        target_duration_seconds=60, generated_at=_NOW,
    )


def _make_report(issues: list[IntegrityIssue]) -> IntegrityReport:
    return IntegrityReport(passed=False, issues=issues)


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


async def _run_worker(
    storage: InMemoryArtifactStorage,
    script: Optional[GeneratedScriptArtifact],
    report: Optional[IntegrityReport],
    claude_text: str,
):
    artifacts: dict[str, str] = {}
    if script is not None:
        a = await write_artifact(
            storage, script, name="generated_script", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["generated_script"] = a.r2_key
    if report is not None:
        a = await write_artifact(
            storage, report, name="integrity_report", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["integrity_report"] = a.r2_key

    state = StageState(run_id="run-001", user_id="operator", inputs={}, artifacts=artifacts)
    with patch("cf_platform.workers.patch_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response(claude_text))
        mock_cls.return_value = mock_client
        worker = build_patch_generator_worker(storage, "fake-key")
        return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_patch_set():
    """Worker parses Claude's patch JSON and returns PatchSetArtifact."""
    storage = InMemoryArtifactStorage()
    issues = [IntegrityIssue(description="Wrong stat", span="1980", severity="high")]
    patches_json = json.dumps([{
        "operation": "replace", "target": "1980", "replacement": "1970"
    }])
    output = await _run_worker(storage, _make_script(), _make_report(issues), patches_json)
    assert isinstance(output.artifact, PatchSetArtifact)
    assert len(output.artifact.patches) == 1
    assert output.artifact.patches[0].operation == "replace"
    assert output.artifact.patches[0].target == "1980"


@pytest.mark.asyncio
async def test_low_severity_issues_skipped_no_llm_call():
    """Only low severity issues → returns empty PatchSetArtifact without calling LLM."""
    storage = InMemoryArtifactStorage()
    issues = [IntegrityIssue(description="Minor style", severity="low")]
    called = False

    async def _fake_create(*args, **kwargs):
        nonlocal called
        called = True
        return _mock_response("[]")

    with patch("cf_platform.workers.patch_generator.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = _fake_create
        mock_cls.return_value = mock_client
        worker = build_patch_generator_worker(storage, "fake-key")
        script_a = await write_artifact(
            storage, _make_script(), name="generated_script", stage="s",
            run_id="r", user_id="u", lineage=_LINEAGE,
        )
        report_a = await write_artifact(
            storage, _make_report(issues), name="integrity_report", stage="s",
            run_id="r", user_id="u", lineage=_LINEAGE,
        )
        state = StageState(
            run_id="r", user_id="u", inputs={},
            artifacts={"generated_script": script_a.r2_key, "integrity_report": report_a.r2_key},
        )
        output = await worker(state)

    assert not called  # LLM not called for low-severity-only
    assert output.artifact.patches == []


@pytest.mark.asyncio
async def test_invalid_json_fallback_to_empty():
    """Invalid JSON from Claude → safe fallback to empty patch set (no raise)."""
    storage = InMemoryArtifactStorage()
    issues = [IntegrityIssue(description="Issue", severity="high")]
    output = await _run_worker(storage, _make_script(), _make_report(issues), "invalid json!!!")
    assert isinstance(output.artifact, PatchSetArtifact)
    assert output.artifact.patches == []


@pytest.mark.asyncio
async def test_missing_generated_script_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="generated_script"):
        await _run_worker(storage, None, _make_report([]), "[]")


@pytest.mark.asyncio
async def test_missing_integrity_report_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="integrity_report"):
        await _run_worker(storage, _make_script(), None, "[]")


def test_registration_model():
    assert PATCH_GENERATOR_REGISTRATION.model == "claude-haiku-4-5"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_patch_generator_worker(storage, "fake-key")
    assert callable(worker)
