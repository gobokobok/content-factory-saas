"""Tests for P9-S2 StoryboardWorker — generate→review→patch internal cycle."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.schemas import LineageEnvelope, StageState
from cf_platform.workers.script_packager import ScriptArtifact
from cf_platform.workers.storyboard_worker import (
    STORYBOARD_PROMPT_VERSION,
    STORYBOARD_WORKER_REGISTRATION,
    VerifiedStoryboardArtifact,
    _apply_patches_and_render_options,
    _parse_review_response,
    build_storyboard_worker,
)
from src.models import Storyboard


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_storyboard_json(**scene_overrides) -> str:
    """Return a minimal valid storyboard JSON string."""
    scene = {
        "scene": "1",
        "clip_type": "still_with_motion",
        "duration_s": 2.5,
        "voiceover_line": "Homeownership rates have dropped dramatically.",
        "segment_type": "B-roll",
        "primary_stk": "house exterior keys decline",
        "context_stk": "housing",
        "concept_stk": "housing",
        "on_screen_text": None,
        "on_screen_text_type": None,
        "motion_effect": "ken_burns_in",
        "sfx": "ambient city traffic",
        "sfx_timing": "on cut",
        "person_name": None,
        "person_title": None,
    }
    scene.update(scene_overrides)
    data = {
        "global": {
            "subtitle_style": "white bold bottom",
            "bg_music": "ambient piano",
            "visual_style": "cinematic",
        },
        "scenes": [scene],
        "summary": {"total_scenes": 1, "total_duration_s": 2.5, "rhythm": "SM"},
    }
    return json.dumps(data)


def _make_two_scene_storyboard_json() -> str:
    """Return a storyboard with a Character scene (wrong segment_type) and a B-roll scene."""
    data = {
        "global": {
            "subtitle_style": "white bold bottom",
            "bg_music": "ambient piano",
            "visual_style": "cinematic",
        },
        "scenes": [
            {
                "scene": "1",
                "clip_type": "still_with_motion",
                "duration_s": 2.5,
                "voiceover_line": "Homeownership rates have dropped.",
                "segment_type": "B-roll",
                "primary_stk": "house exterior keys",
                "context_stk": "housing",
                "concept_stk": "housing",
                "on_screen_text": None,
                "on_screen_text_type": None,
                "motion_effect": "ken_burns_in",
                "sfx": "ambient city traffic",
                "sfx_timing": "on cut",
                "person_name": None,
                "person_title": None,
            },
            {
                "scene": "2",
                "clip_type": "still_with_motion",
                "duration_s": 3.0,
                "voiceover_line": "Jerome Powell raised interest rates.",
                "segment_type": "B-roll",  # wrong — should be Character
                "primary_stk": "interest rates federal reserve",
                "context_stk": "federal reserve",
                "concept_stk": "economy",
                "on_screen_text": None,
                "on_screen_text_type": None,
                "motion_effect": "ken_burns_in",
                "sfx": "sound",  # vague — should be flagged
                "sfx_timing": "on cut",
                "person_name": "Jerome Powell",
                "person_title": "Chair, Federal Reserve",
            },
        ],
        "summary": {"total_scenes": 2, "total_duration_s": 5.5, "rhythm": "SM / SM"},
    }
    return json.dumps(data)


def _make_review_json(patches=None, coverage_ok=True, issues=None) -> str:
    return json.dumps({
        "coverage_ok": coverage_ok,
        "patches": patches or [],
        "issues": issues or [],
    })


def _mock_message(text: str) -> MagicMock:
    """Return a mock Anthropic message object."""
    msg = MagicMock()
    msg.content = [MagicMock()]
    msg.content[0].text = text
    return msg


async def _write_script_artifact(storage, run_id: str, script_text: str) -> str:
    """Write a ScriptArtifact to storage and return the r2_key."""
    script_artifact = ScriptArtifact(
        idea_title="Test idea",
        niche="housing",
        script=script_text,
        word_count=len(script_text.split()),
        status="ok",
        generated_at=datetime.now(timezone.utc),
    )
    lineage = LineageEnvelope(
        run_id=run_id,
        worker="script_packager",
        worker_version="2.0.0",
        prompt_version="v2",
        model="none",
        created_at=datetime.now(timezone.utc),
    )
    artifact = await write_artifact(
        storage,
        script_artifact,
        name="script",
        stage="script",
        run_id=run_id,
        user_id="operator",
        lineage=lineage,
    )
    return artifact.r2_key


# ── Registration pin tests ────────────────────────────────────────────────────


def test_prompt_version_constant():
    assert STORYBOARD_PROMPT_VERSION == "v0.14"


def test_registration_model():
    assert STORYBOARD_WORKER_REGISTRATION.model == "claude-sonnet-4-6"


def test_registration_worker_version():
    assert STORYBOARD_WORKER_REGISTRATION.worker_version == "1.1.0"


def test_registration_prompt_version():
    assert STORYBOARD_WORKER_REGISTRATION.prompt_version == "v0.14"


# ── _parse_review_response unit tests ────────────────────────────────────────


def test_parse_review_valid_json():
    patches, coverage_ok, issues = _parse_review_response(
        json.dumps({"coverage_ok": True, "patches": [], "issues": []})
    )
    assert coverage_ok is True
    assert patches == []
    assert issues == []


def test_parse_review_with_patches():
    raw = json.dumps({
        "coverage_ok": True,
        "patches": [{"scene_id": "2", "field": "segment_type", "value": "Character"}],
        "issues": ["Scene 2 misclassified"],
    })
    patches, coverage_ok, issues = _parse_review_response(raw)
    assert len(patches) == 1
    assert patches[0]["field"] == "segment_type"
    assert coverage_ok is True
    assert "Scene 2 misclassified" in issues


def test_parse_review_coverage_failure():
    raw = json.dumps({"coverage_ok": False, "patches": [], "issues": ["Word 'equity' missing"]})
    _, coverage_ok, issues = _parse_review_response(raw)
    assert coverage_ok is False
    assert "equity" in issues[0]


def test_parse_review_invalid_json_returns_safe_defaults():
    patches, coverage_ok, issues = _parse_review_response("not json at all")
    assert patches == []
    assert coverage_ok is True
    assert issues == []


def test_parse_review_strips_markdown_fences():
    raw = "```json\n" + json.dumps({"coverage_ok": True, "patches": [], "issues": []}) + "\n```"
    patches, coverage_ok, _ = _parse_review_response(raw)
    assert coverage_ok is True
    assert patches == []


# ── _apply_patches_and_render_options unit tests ─────────────────────────────


def _load_storyboard(json_str: str) -> Storyboard:
    return Storyboard.model_validate(json.loads(json_str))


def test_character_scene_gets_lower_third_and_null_on_screen_text():
    """Character scene with person_name → lower_third in render_options; on_screen_text nulled."""
    storyboard = _load_storyboard(_make_storyboard_json(
        segment_type="Character",
        person_name="Jerome Powell",
        person_title="Chair, Federal Reserve",
        on_screen_text="Powell on rates",
        on_screen_text_type="stat",
    ))
    result = _apply_patches_and_render_options(storyboard, [])
    scene = result.scenes[0]
    assert scene.render_options is not None
    assert scene.render_options.lower_third is not None
    assert scene.render_options.lower_third.name == "Jerome Powell"
    assert scene.render_options.lower_third.title == "Chair, Federal Reserve"
    assert scene.render_options.lower_third.caption_y_override == 1540
    # on_screen_text must be nulled out when lower_third is active
    assert scene.on_screen_text is None
    assert scene.on_screen_text_type is None


def test_event_scene_gets_film_look():
    """Event scene → render_options.film_look = True."""
    storyboard = _load_storyboard(_make_storyboard_json(segment_type="Event"))
    result = _apply_patches_and_render_options(storyboard, [])
    scene = result.scenes[0]
    assert scene.render_options is not None
    assert scene.render_options.film_look is True


def test_broll_scene_no_render_options():
    """Plain B-roll scene without on_screen_text → no render_options."""
    storyboard = _load_storyboard(_make_storyboard_json(segment_type="B-roll"))
    result = _apply_patches_and_render_options(storyboard, [])
    scene = result.scenes[0]
    assert scene.render_options is None


def test_stat_on_screen_text_gets_enable_expr():
    """on_screen_text with type='stat' → on_screen_text_overlay with enable_expr."""
    storyboard = _load_storyboard(_make_storyboard_json(
        duration_s=3.0,
        on_screen_text="38% decline",
        on_screen_text_type="stat",
    ))
    result = _apply_patches_and_render_options(storyboard, [])
    scene = result.scenes[0]
    assert scene.render_options is not None
    overlay = scene.render_options.on_screen_text_overlay
    assert overlay is not None
    assert overlay.text == "38% decline"
    assert overlay.type == "stat"
    assert "between(t," in overlay.enable_expr
    assert "0.000" in overlay.enable_expr
    assert "3.000" in overlay.enable_expr


def test_enable_expr_uses_cumulative_offset():
    """Second scene's enable_expr starts at the cumulative offset from scene 1."""
    data = {
        "global": {"subtitle_style": "", "bg_music": "", "visual_style": ""},
        "scenes": [
            {
                "scene": "1", "clip_type": "still_with_motion", "duration_s": 2.5,
                "voiceover_line": "First line.", "segment_type": "B-roll",
                "primary_stk": "house", "context_stk": "housing", "concept_stk": "housing",
                "on_screen_text": None, "on_screen_text_type": None, "motion_effect": "ken_burns_in",
                "sfx": "traffic", "sfx_timing": "on cut", "person_name": None, "person_title": None,
            },
            {
                "scene": "2", "clip_type": "still_with_motion", "duration_s": 2.0,
                "voiceover_line": "Second line.", "segment_type": "B-roll",
                "primary_stk": "house", "context_stk": "housing", "concept_stk": "housing",
                "on_screen_text": "2024", "on_screen_text_type": "date",
                "motion_effect": "ken_burns_in",
                "sfx": "traffic", "sfx_timing": "on cut", "person_name": None, "person_title": None,
            },
        ],
        "summary": {"total_scenes": 2, "total_duration_s": 4.5, "rhythm": "SM / SM"},
    }
    storyboard = Storyboard.model_validate(data)
    result = _apply_patches_and_render_options(storyboard, [])
    scene2 = result.scenes[1]
    overlay = scene2.render_options.on_screen_text_overlay
    assert overlay is not None
    # Scene 2 starts at t=2.5, ends at t=4.5
    assert "2.500" in overlay.enable_expr
    assert "4.500" in overlay.enable_expr


def test_patches_applied_before_render_options():
    """Review patches are applied before render_options computation."""
    storyboard = _load_storyboard(_make_storyboard_json(
        segment_type="B-roll",  # wrong
        person_name="Jerome Powell",
        person_title="Chair, Federal Reserve",
    ))
    patches = [{"scene_id": "1", "field": "segment_type", "value": "Character"}]
    result = _apply_patches_and_render_options(storyboard, patches)
    scene = result.scenes[0]
    # After patch, segment_type is Character → lower_third should be set
    assert scene.segment_type == "Character"
    assert scene.render_options is not None
    assert scene.render_options.lower_third is not None


def test_unknown_patch_field_ignored():
    """Patches targeting disallowed fields are silently ignored."""
    storyboard = _load_storyboard(_make_storyboard_json())
    patches = [{"scene_id": "1", "field": "render_options", "value": {"film_look": True}}]
    result = _apply_patches_and_render_options(storyboard, patches)
    # render_options should not be set (B-roll with no on_screen_text)
    assert result.scenes[0].render_options is None


# ── Full round-trip integration test (mocked Sonnet + Haiku) ─────────────────


@pytest.mark.asyncio
async def test_generate_review_patch_round_trip():
    """Full worker round-trip: generate→review→patch with mocked API calls."""
    storage = InMemoryArtifactStorage()
    script_key = await _write_script_artifact(storage, "run-001", "Homeownership rates have dropped.")

    generate_response = _mock_message(_make_storyboard_json())
    review_response = _mock_message(_make_review_json())

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[generate_response, review_response])
        mock_cls.return_value = mock_client

        worker = build_storyboard_worker(storage, "test-key")
        state = StageState(
            run_id="run-001",
            user_id="operator",
            inputs={},
            artifacts={"script": script_key},
        )
        output = await worker(state)

    artifact = output.artifact
    assert isinstance(artifact, VerifiedStoryboardArtifact)
    assert artifact.prompt_version == "v0.14"
    assert artifact.scene_count == 1
    assert "scenes" in artifact.storyboard
    # Two API calls: generate (Sonnet) + review (Haiku)
    assert mock_client.messages.create.call_count == 2


@pytest.mark.asyncio
async def test_coverage_issue_caught_by_review():
    """Review step flags coverage failure; worker logs and continues."""
    storage = InMemoryArtifactStorage()
    script_key = await _write_script_artifact(storage, "run-002", "Rates dropped in 2022.")

    generate_response = _mock_message(_make_storyboard_json())
    review_response = _mock_message(_make_review_json(
        coverage_ok=False,
        issues=["Word '2022' not found in any voiceover_line"],
    ))

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[generate_response, review_response])
        mock_cls.return_value = mock_client

        worker = build_storyboard_worker(storage, "test-key")
        state = StageState(
            run_id="run-002",
            user_id="operator",
            inputs={},
            artifacts={"script": script_key},
        )
        # Worker continues despite coverage failure (logs warning; doesn't raise)
        output = await worker(state)

    assert isinstance(output.artifact, VerifiedStoryboardArtifact)


@pytest.mark.asyncio
async def test_character_scene_review_patch_applied_in_worker():
    """End-to-end: review patches a B-roll scene to Character; render_options set."""
    storage = InMemoryArtifactStorage()
    script_key = await _write_script_artifact(
        storage, "run-003",
        "Jerome Powell raised interest rates. Homeownership dropped.",
    )
    generate_response = _mock_message(_make_two_scene_storyboard_json())
    review_response = _mock_message(_make_review_json(
        patches=[
            {"scene_id": "2", "field": "segment_type", "value": "Character"},
            {"scene_id": "2", "field": "sfx", "value": "microphone feedback conference room"},
        ],
    ))

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[generate_response, review_response])
        mock_cls.return_value = mock_client

        worker = build_storyboard_worker(storage, "test-key")
        state = StageState(
            run_id="run-003",
            user_id="operator",
            inputs={},
            artifacts={"script": script_key},
        )
        output = await worker(state)

    storyboard = Storyboard.model_validate(output.artifact.storyboard)
    scene2 = next(s for s in storyboard.scenes if s.scene == "2")
    assert scene2.segment_type == "Character"
    assert scene2.render_options is not None
    assert scene2.render_options.lower_third is not None
    assert scene2.render_options.lower_third.name == "Jerome Powell"
    assert scene2.on_screen_text is None  # nulled by patch step


@pytest.mark.asyncio
async def test_verified_storyboard_artifact_written_to_r2():
    """Worker output can be serialised and validated as VerifiedStoryboardArtifact."""
    storage = InMemoryArtifactStorage()
    script_key = await _write_script_artifact(storage, "run-004", "Housing prices rose 40%.")

    generate_response = _mock_message(_make_storyboard_json(
        on_screen_text="40%", on_screen_text_type="stat",
    ))
    review_response = _mock_message(_make_review_json())

    with patch("cf_platform.workers.storyboard_worker.anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=[generate_response, review_response])
        mock_cls.return_value = mock_client

        worker = build_storyboard_worker(storage, "test-key")
        state = StageState(
            run_id="run-004",
            user_id="operator",
            inputs={},
            artifacts={"script": script_key},
        )
        output = await worker(state)

    # Simulate writing to R2 and reading back
    artifact = output.artifact
    assert isinstance(artifact, VerifiedStoryboardArtifact)
    dumped = artifact.model_dump(mode="json")
    # Must round-trip cleanly
    recovered = VerifiedStoryboardArtifact.model_validate(dumped)
    assert recovered.scene_count == artifact.scene_count
    assert recovered.prompt_version == "v0.14"
    # Storyboard should contain render_options with on_screen_text_overlay
    storyboard = Storyboard.model_validate(recovered.storyboard)
    scene = storyboard.scenes[0]
    assert scene.render_options is not None
    assert scene.render_options.on_screen_text_overlay is not None
    assert "40%" in scene.render_options.on_screen_text_overlay.text
