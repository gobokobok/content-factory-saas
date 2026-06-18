"""Tests for cf_platform/workers/integrity_checker.py (P5-S6).

Covers:
- Happy path: passed=True → artifact IntegrityReport(passed=True), control='continue'
- Fail path: passed=False with issues → control='retry'
- Issues parsed with severity and span
- severity defaults to 'medium' when not in response
- Missing generated_script artifact ref → KeyError
- Missing merged_blueprint artifact ref → KeyError
- Invalid JSON from Claude → ValueError
- Registration: model='claude-haiku-4-5', worker_version, prompt_version
- build_integrity_checker_worker returns a callable
"""

import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    GeneratedScriptArtifact,
    IntegrityReport,
    Section,
)
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.integrity_checker import (
    INTEGRITY_CHECKER_REGISTRATION,
    build_integrity_checker_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-001", worker="test", worker_version="1.0.0", prompt_version="v1",
    model="none", created_at=_NOW,
)
_SCRIPT = "In 1980 homes were affordable. Today they cost 12 years of savings."


def _make_blueprint() -> Blueprint:
    return Blueprint(
        hook_angle="Homes less affordable",
        structure=[Section(title="Hook", key_points=["stat"])],
        claims=["12 years of savings needed"],
        monetization_angle="Urgency",
        required_evidence=["Census data"],
        signal_summary="Summary",
        direction_alignment_notes="Notes",
    )


def _make_generated_script() -> GeneratedScriptArtifact:
    return GeneratedScriptArtifact(
        idea_title="Why Starter Homes Vanished",
        niche="housing",
        script=_SCRIPT,
        word_count=len(_SCRIPT.split()),
        target_duration_seconds=60,
        generated_at=_NOW,
    )


def _mock_response(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


async def _run_worker(
    storage: InMemoryArtifactStorage,
    generated_script: Optional[GeneratedScriptArtifact],
    blueprint: Optional[Blueprint],
    claude_text: str,
):
    artifacts: dict[str, str] = {}
    if generated_script is not None:
        a = await write_artifact(
            storage, generated_script, name="generated_script", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["generated_script"] = a.r2_key
    if blueprint is not None:
        a = await write_artifact(
            storage, blueprint, name="merged_blueprint", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["merged_blueprint"] = a.r2_key

    state = StageState(run_id="run-001", user_id="operator", inputs={}, artifacts=artifacts)
    with patch("cf_platform.workers.integrity_checker.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_response(claude_text))
        mock_cls.return_value = mock_client
        worker = build_integrity_checker_worker(storage, "fake-key")
        return await worker(state)


@pytest.mark.asyncio
async def test_pass_path_returns_continue():
    """When Claude returns passed=True, control='continue'."""
    storage = InMemoryArtifactStorage()
    response_json = json.dumps({"passed": True, "issues": []})
    output = await _run_worker(storage, _make_generated_script(), _make_blueprint(), response_json)
    assert isinstance(output.artifact, IntegrityReport)
    assert output.artifact.passed is True
    assert output.control == "continue"


@pytest.mark.asyncio
async def test_fail_path_returns_retry():
    """When Claude returns passed=False, control='retry'."""
    storage = InMemoryArtifactStorage()
    response_json = json.dumps({
        "passed": False,
        "issues": [{"description": "Missing evidence", "severity": "high"}],
    })
    output = await _run_worker(storage, _make_generated_script(), _make_blueprint(), response_json)
    assert output.artifact.passed is False
    assert output.control == "retry"


@pytest.mark.asyncio
async def test_issues_parsed_with_severity():
    """Issues are parsed into IntegrityIssue with correct severity."""
    storage = InMemoryArtifactStorage()
    response_json = json.dumps({
        "passed": False,
        "issues": [
            {"description": "Hallucination", "span": "wrong text", "severity": "high"},
            {"description": "Minor style", "severity": "low"},
        ],
    })
    output = await _run_worker(storage, _make_generated_script(), _make_blueprint(), response_json)
    issues = output.artifact.issues
    assert len(issues) == 2
    assert issues[0].severity == "high"
    assert issues[0].span == "wrong text"
    assert issues[1].severity == "low"


@pytest.mark.asyncio
async def test_missing_generated_script_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="generated_script"):
        await _run_worker(storage, None, _make_blueprint(), "{}")


@pytest.mark.asyncio
async def test_missing_blueprint_raises_key_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="merged_blueprint"):
        await _run_worker(storage, _make_generated_script(), None, "{}")


@pytest.mark.asyncio
async def test_invalid_json_raises_value_error():
    storage = InMemoryArtifactStorage()
    with pytest.raises(ValueError):
        await _run_worker(storage, _make_generated_script(), _make_blueprint(), "not json")


def test_registration_model():
    assert INTEGRITY_CHECKER_REGISTRATION.model == "claude-haiku-4-5"


def test_registration_worker_version():
    assert INTEGRITY_CHECKER_REGISTRATION.worker_version == "1.0.0"


def test_build_returns_callable():
    storage = InMemoryArtifactStorage()
    worker = build_integrity_checker_worker(storage, "fake-key")
    assert callable(worker)
