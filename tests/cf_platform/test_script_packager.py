"""Tests for cf_platform/workers/script_packager.py (P5-S6 version).

Covers:
- Happy path: reads generated_script, emits ScriptArtifact with status='ok'
- idea_title propagated from GeneratedScriptArtifact
- niche propagated (Optional — None when absent)
- word_count propagated
- overall_score is None (not computed in Blueprint IR pipeline)
- draft_number is None (not applicable)
- status='manual_review' when integrity_verdict='retry' and integrity_loops >= _MAX_INTEGRITY_LOOPS
- status='ok' when integrity_verdict='retry' but integrity_loops < _MAX_INTEGRITY_LOOPS
- status='ok' when integrity_verdict='continue' regardless of loops
- Missing generated_script artifact ref → KeyError
- Registration: model='none', worker_version='2.0.0', prompt_version='v2'
- build_script_packager_worker returns a callable
"""

from datetime import datetime, timezone
from typing import Optional

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.idea_to_script_schemas import GeneratedScriptArtifact
from cf_platform.core.schemas import IdeaToScriptState, LineageEnvelope, StageState
from cf_platform.workers.script_packager import (
    SCRIPT_PACKAGER_REGISTRATION,
    ScriptArtifact,
    build_script_packager_worker,
)

_NOW = datetime(2026, 6, 18, tzinfo=timezone.utc)
_LINEAGE = LineageEnvelope(
    run_id="run-001",
    worker="test",
    worker_version="1.0.0",
    prompt_version="v1",
    model="none",
    created_at=_NOW,
)
_IDEA_TITLE = "Why Starter Homes Vanished"
_NICHE = "US housing"
_SCRIPT = "In 1980 the average family could save for a home in 3 years. Today it takes 12."


def _make_generated_script(niche: Optional[str] = _NICHE, script: str = _SCRIPT) -> GeneratedScriptArtifact:
    return GeneratedScriptArtifact(
        idea_title=_IDEA_TITLE,
        niche=niche,
        script=script,
        word_count=len(script.split()),
        target_duration_seconds=60,
        generated_at=_NOW,
    )


async def _run_packager(
    storage: InMemoryArtifactStorage,
    generated_script: Optional[GeneratedScriptArtifact],
    *,
    integrity_loops: int = 0,
    integrity_verdict: str = "continue",
):
    artifacts: dict[str, str] = {}
    if generated_script is not None:
        a = await write_artifact(
            storage, generated_script, name="generated_script", stage="idea_to_script",
            run_id="run-001", user_id="operator", lineage=_LINEAGE,
        )
        artifacts["generated_script"] = a.r2_key

    state = IdeaToScriptState(
        run_id="run-001",
        user_id="operator",
        inputs={},
        artifacts=artifacts,
        integrity_loops=integrity_loops,
        integrity_verdict=integrity_verdict,  # type: ignore[arg-type]
    )
    worker = build_script_packager_worker(storage)
    return await worker(state)


@pytest.mark.asyncio
async def test_happy_path_emits_script_artifact():
    """Packager emits a ScriptArtifact with status='ok' on the normal path."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script())
    assert isinstance(output.artifact, ScriptArtifact)
    assert output.artifact.status == "ok"
    assert output.artifact.script == _SCRIPT


@pytest.mark.asyncio
async def test_idea_title_propagated():
    """ScriptArtifact.idea_title matches the generated_script artifact."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script())
    assert output.artifact.idea_title == _IDEA_TITLE  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_niche_propagated():
    """ScriptArtifact.niche matches the generated_script artifact."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script(niche=_NICHE))
    assert output.artifact.niche == _NICHE  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_niche_none_propagated():
    """ScriptArtifact.niche is None when the generated_script has no niche."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script(niche=None))
    assert output.artifact.niche is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_overall_score_is_none():
    """overall_score is None — not computed in the Blueprint IR pipeline."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script())
    assert output.artifact.overall_score is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_draft_number_is_none():
    """draft_number is None — not applicable in the Blueprint IR pipeline."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(storage, _make_generated_script())
    assert output.artifact.draft_number is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_manual_review_when_integrity_exhausted():
    """status='manual_review' when integrity_verdict='retry' and loops >= MAX_INTEGRITY_LOOPS."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage, _make_generated_script(),
        integrity_loops=2, integrity_verdict="retry",
    )
    assert output.artifact.status == "manual_review"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_ok_when_retry_but_loops_below_cap():
    """status='ok' when integrity_verdict='retry' but integrity_loops < MAX_INTEGRITY_LOOPS."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage, _make_generated_script(),
        integrity_loops=1, integrity_verdict="retry",
    )
    # loops=1 is below cap (2), so this is the "pass" path — should be ok
    assert output.artifact.status == "ok"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_ok_when_integrity_passed():
    """status='ok' when integrity_verdict='continue' regardless of loop count."""
    storage = InMemoryArtifactStorage()
    output = await _run_packager(
        storage, _make_generated_script(),
        integrity_loops=5, integrity_verdict="continue",
    )
    assert output.artifact.status == "ok"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_missing_generated_script_raises_key_error():
    """KeyError is raised when generated_script artifact ref is absent."""
    storage = InMemoryArtifactStorage()
    with pytest.raises(KeyError, match="generated_script"):
        await _run_packager(storage, None)


def test_registration_model_none():
    """SCRIPT_PACKAGER_REGISTRATION.model is 'none' — no LLM call."""
    assert SCRIPT_PACKAGER_REGISTRATION.model == "none"


def test_registration_worker_version():
    """SCRIPT_PACKAGER_REGISTRATION pins worker_version 2.0.0."""
    assert SCRIPT_PACKAGER_REGISTRATION.worker_version == "2.0.0"


def test_registration_prompt_version():
    """SCRIPT_PACKAGER_REGISTRATION pins prompt_version v2."""
    assert SCRIPT_PACKAGER_REGISTRATION.prompt_version == "v2"


def test_build_returns_callable():
    """build_script_packager_worker returns a callable (the WorkerNode)."""
    storage = InMemoryArtifactStorage()
    worker = build_script_packager_worker(storage)
    assert callable(worker)
