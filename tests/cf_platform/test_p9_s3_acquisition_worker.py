"""Tests for P9-S3 Native AcquisitionWorker.

Coverage:
- Registration pins
- _compute_footage_summary
- _try_candidates: QA pass accepts first passing candidate
- _try_candidates: low-res pre-check skip, CLIP-fail collected for pick_best
- _accept_best: pick_best from collected; last-resort download
- _acquire_character: Wikipedia portrait found → accepted, QA skipped
- _acquire_character: Wikipedia miss → Pexels+Pixabay fallback
- _acquire_event: Wikimedia searched first; Pexels+Pixabay fallback on miss
- _acquire_broll: Pexels+Pixabay concurrent; three-tier cascade on primary miss
- _acquire_broll: no Pixabay when key absent
- Worker integration: verified_storyboard → asset_manifest artifact
- Worker integration: scene failure marked failed; manifest never empty
- API endpoint: registration present
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import StageState
from cf_platform.workers.acquisition_worker import (
    ACQUISITION_WORKER_REGISTRATION,
    AssetManifestArtifact,
    _Candidate,
    _acquire_broll,
    _acquire_character,
    _acquire_event,
    _compute_footage_summary,
    _try_candidates,
    build_acquisition_worker,
)
from src.footage_qa import QAResult
from src.models import AssetManifest, ManifestEntry


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_entry(
    scene_id: str = "1",
    clip_type: str = "still_with_motion",
    segment_type: str = "B-roll",
    primary_stk: str = "housing market",
    context_stk: str = "house",
    concept_stk: str = "housing",
    person_name: Optional[str] = None,
    duration_s: float = 3.0,
) -> ManifestEntry:
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        segment_type=segment_type,
        primary_stk=primary_stk,
        context_stk=context_stk,
        concept_stk=concept_stk,
        person_name=person_name,
        duration_s=duration_s,
    )


def _make_candidate(
    url: str = "https://cdn.example.com/video.mp4",
    width: int = 1920,
    height: int = 1080,
    source: str = "pexels",
    content_type: str = "image/jpeg",
    ext: str = ".jpg",
    duration_seconds: Optional[float] = None,
) -> _Candidate:
    return _Candidate(
        url=url,
        width=width,
        height=height,
        source=source,
        content_type=content_type,
        ext=ext,
        duration_seconds=duration_seconds,
    )


def _make_storage() -> InMemoryArtifactStorage:
    return InMemoryArtifactStorage()


# ── Registration pins ─────────────────────────────────────────────────────────


def test_registration_worker_version():
    assert ACQUISITION_WORKER_REGISTRATION.worker_version == "1.0.0"


def test_registration_model_is_none():
    assert ACQUISITION_WORKER_REGISTRATION.model == "none"


def test_registration_prompt_version_is_none():
    assert ACQUISITION_WORKER_REGISTRATION.prompt_version == "none"


# ── _compute_footage_summary ──────────────────────────────────────────────────


def test_footage_summary_counts_sources():
    entries = [
        ManifestEntry(scene_id="1", clip_type="still_with_motion", status="acquired", source="pexels", qa_passed=True),
        ManifestEntry(scene_id="2", clip_type="still_with_motion", status="acquired", source="pixabay", qa_passed=True),
        ManifestEntry(scene_id="3", clip_type="still_with_motion", status="acquired", source="wikimedia", qa_passed=True),
        ManifestEntry(scene_id="4", clip_type="still_with_motion", status="acquired", source="wikimedia_person", qa_passed=True),
    ]
    summary = _compute_footage_summary(entries)
    assert summary["pexels"] == 1
    assert summary["pixabay"] == 1
    assert summary["wikimedia"] == 1
    assert summary["wikimedia_person"] == 1
    assert summary["failed"] == 0
    assert summary["qa_failed_scenes"] == 0


def test_footage_summary_counts_failed():
    entries = [
        ManifestEntry(scene_id="1", clip_type="still_with_motion", status="failed"),
        ManifestEntry(scene_id="2", clip_type="still_with_motion", status="acquired", source="pexels", qa_passed=True),
    ]
    summary = _compute_footage_summary(entries)
    assert summary["failed"] == 1
    assert summary["pexels"] == 1


def test_footage_summary_qa_failed_scenes():
    entries = [
        ManifestEntry(scene_id="1", clip_type="still_with_motion", status="acquired", source="pexels", qa_passed=False),
        ManifestEntry(scene_id="2", clip_type="still_with_motion", status="acquired", source="pixabay", qa_passed=True),
    ]
    summary = _compute_footage_summary(entries)
    assert summary["qa_failed_scenes"] == 1
    assert summary["pexels"] == 1


# ── _try_candidates ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_try_candidates_accepts_first_qa_pass():
    """First candidate that passes pre-check and full QA is accepted."""
    storage = _make_storage()
    entry = _make_entry()
    candidate = _make_candidate(width=1920, height=1080)
    collected: list = []

    with (
        patch("cf_platform.workers.acquisition_worker.qa_score") as mock_qa,
        patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl,
    ):
        qa_pass = QAResult(passed=True, resolution_ok=True, duration_ok=True, clip_score=None, clip_enabled=False)
        mock_qa.return_value = qa_pass
        mock_dl.return_value = b"fake_image_bytes"

        result = await _try_candidates([candidate], entry, False, "run1", storage, collected)

    assert result is True
    assert entry.status == "acquired"
    assert entry.source == "pexels"
    assert entry.file_key is not None
    assert len(collected) == 0


@pytest.mark.asyncio
async def test_try_candidates_skips_low_res():
    """Candidates that fail the resolution pre-check are skipped without downloading."""
    storage = _make_storage()
    entry = _make_entry()
    candidate = _make_candidate(width=320, height=240)  # too small
    collected: list = []

    with (
        patch("cf_platform.workers.acquisition_worker.qa_score") as mock_qa,
        patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl,
    ):
        # Pre-check fails resolution
        mock_qa.return_value = QAResult(passed=False, resolution_ok=False, duration_ok=True, clip_score=None, clip_enabled=False)
        result = await _try_candidates([candidate], entry, False, "run1", storage, collected)

    assert result is False
    mock_dl.assert_not_called()
    assert len(collected) == 0


@pytest.mark.asyncio
async def test_try_candidates_qa_fail_added_to_collected():
    """A candidate that passes pre-check but fails full QA is added to collected."""
    storage = _make_storage()
    entry = _make_entry()
    candidate = _make_candidate(width=1920, height=1080)
    collected: list = []

    with (
        patch("cf_platform.workers.acquisition_worker.qa_score") as mock_qa,
        patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl,
    ):
        pre_pass = QAResult(passed=True, resolution_ok=True, duration_ok=True, clip_score=None, clip_enabled=False)
        full_fail = QAResult(passed=False, resolution_ok=True, duration_ok=True, clip_score=0.1, clip_enabled=True)
        mock_qa.side_effect = [pre_pass, full_fail]
        mock_dl.return_value = b"image_bytes"

        result = await _try_candidates([candidate], entry, False, "run1", storage, collected)

    assert result is False
    assert len(collected) == 1


# ── _acquire_character ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_character_wikipedia_portrait_found():
    """Character scene: Wikipedia portrait acquired; QA gate skipped."""
    storage = _make_storage()
    entry = _make_entry(segment_type="Character", person_name="Jerome Powell")
    queries = ["Jerome Powell Federal Reserve", "Powell", "person"]

    mock_asset = MagicMock()
    mock_asset.url = "https://upload.wikimedia.org/powell.jpg"
    mock_asset.attribution = "Photo of Jerome Powell via Wikipedia"

    mock_wikimedia = MagicMock()
    mock_wikimedia.fetch_person_photo = AsyncMock(return_value=mock_asset)

    mock_pexels = MagicMock()
    mock_pixabay = MagicMock()

    with patch("cf_platform.workers.acquisition_worker._download_bytes", new_callable=AsyncMock) as mock_dl:
        mock_dl.return_value = b"portrait_bytes"
        result = await _acquire_character(entry, queries, "run1", storage, mock_pexels, mock_pixabay, mock_wikimedia)

    assert result is True
    assert entry.source == "wikimedia_person"
    assert entry.status == "acquired"
    assert entry.qa_passed is True  # QA skipped for Wikipedia portraits
    mock_wikimedia.fetch_person_photo.assert_called_once_with("Jerome Powell")


@pytest.mark.asyncio
async def test_acquire_character_wikipedia_miss_falls_back_to_generic():
    """Character scene: Wikipedia miss → generic Pexels+Pixabay fallback."""
    storage = _make_storage()
    entry = _make_entry(segment_type="Character", person_name="Unknown Person")
    queries = ["Unknown Person", "person", "people"]

    mock_wikimedia = MagicMock()
    mock_wikimedia.fetch_person_photo = AsyncMock(return_value=None)

    mock_pexels = MagicMock()
    mock_pixabay = MagicMock()

    with (
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
        patch("cf_platform.workers.acquisition_worker._try_candidates", new_callable=AsyncMock) as mock_try,
    ):
        mock_thread.return_value = [_make_candidate()]
        mock_pix.return_value = [_make_candidate(source="pixabay")]
        mock_try.return_value = True

        result = await _acquire_character(entry, queries, "run1", storage, mock_pexels, mock_pixabay, mock_wikimedia)

    assert result is True
    mock_wikimedia.fetch_person_photo.assert_called_once_with("Unknown Person")


# ── _acquire_event ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_event_wikimedia_searched_first():
    """Event scene: Wikimedia Commons is tried before Pexels+Pixabay."""
    storage = _make_storage()
    entry = _make_entry(segment_type="Event", clip_type="still_with_motion")
    queries = ["London Blitz 1940 ruins", "London Blitz", "city"]

    call_order: list[str] = []

    async def mock_wikimedia_search(wikimedia_client: Any, query: str) -> list[_Candidate]:
        call_order.append(f"wikimedia:{query}")
        return []

    with (
        patch("cf_platform.workers.acquisition_worker._wikimedia_photo_candidates", side_effect=mock_wikimedia_search),
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
    ):
        mock_thread.return_value = [_make_candidate()]

        async def mock_pix_fn(client: Any, query: str) -> list[_Candidate]:
            call_order.append(f"pixabay:{query}")
            return [_make_candidate(source="pixabay")]
        mock_pix.side_effect = mock_pix_fn

        with patch("cf_platform.workers.acquisition_worker._try_candidates", new_callable=AsyncMock) as mock_try:
            mock_try.return_value = True
            mock_wikimedia = MagicMock()
            result = await _acquire_event(entry, queries, "run1", storage, MagicMock(), MagicMock(), mock_wikimedia)

    # Wikimedia calls must precede Pexels+Pixabay calls
    wikimedia_indices = [i for i, c in enumerate(call_order) if c.startswith("wikimedia")]
    pixabay_indices = [i for i, c in enumerate(call_order) if c.startswith("pixabay")]
    if wikimedia_indices and pixabay_indices:
        assert min(wikimedia_indices) < min(pixabay_indices)


@pytest.mark.asyncio
async def test_acquire_event_pexels_pixabay_fallback_on_wikimedia_miss():
    """Event scene: falls back to Pexels+Pixabay when Wikimedia returns nothing."""
    storage = _make_storage()
    entry = _make_entry(segment_type="Event", clip_type="still_with_motion")
    queries = ["Great Depression housing", "Depression", "economy"]

    mock_wikimedia = MagicMock()

    call_count = {"wikimedia": 0, "pexels_pixabay": 0}

    with (
        patch("cf_platform.workers.acquisition_worker._wikimedia_photo_candidates", new_callable=AsyncMock) as mock_wm,
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
        patch("cf_platform.workers.acquisition_worker._try_candidates", new_callable=AsyncMock) as mock_try,
        patch("cf_platform.workers.acquisition_worker._accept_best", new_callable=AsyncMock) as mock_best,
    ):
        mock_wm.return_value = []  # Wikimedia returns nothing
        mock_thread.return_value = [_make_candidate()]
        mock_pix.return_value = [_make_candidate(source="pixabay")]
        mock_try.return_value = False
        mock_best.return_value = True

        result = await _acquire_event(entry, queries, "run1", storage, MagicMock(), MagicMock(), mock_wikimedia)

    # Wikimedia was searched (3 tiers) and Pexels was also tried (asyncio.to_thread called)
    assert mock_wm.call_count == 3  # one per query tier
    assert mock_thread.call_count == 3  # one per query tier for Pexels


# ── _acquire_broll ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_acquire_broll_concurrent_pexels_pixabay():
    """B-roll: Pexels and Pixabay are searched concurrently for each query tier."""
    storage = _make_storage()
    entry = _make_entry(segment_type="B-roll", clip_type="still_with_motion")
    queries = ["housing market graph", "housing", "economy"]

    search_calls: list[str] = []

    with (
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
        patch("cf_platform.workers.acquisition_worker._try_candidates", new_callable=AsyncMock) as mock_try,
    ):
        mock_thread.side_effect = lambda fn, *args: asyncio.coroutine(lambda: [])()  # empty Pexels results
        mock_pix.return_value = []
        mock_try.return_value = True  # accept on first tier

        result = await _acquire_broll(entry, queries, False, "run1", storage, MagicMock(), MagicMock())

    # Both pexels (via to_thread) and pixabay searched on the first tier
    assert mock_thread.call_count >= 1
    assert mock_pix.call_count >= 1


@pytest.mark.asyncio
async def test_acquire_broll_three_tier_cascade_on_primary_miss():
    """B-roll: advances to context_stk when primary_stk yields no QA pass."""
    storage = _make_storage()
    entry = _make_entry(segment_type="B-roll", clip_type="still_with_motion")
    queries = ["specific housing graph", "housing", "economy"]

    tier_call_count = [0]

    async def mock_try(candidates, entry, is_video, run_id, storage, collected, used_source_urls=None, dup_lock=None):
        tier_call_count[0] += 1
        # Fail primary tier, pass on second
        return tier_call_count[0] == 2

    with (
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
        patch("cf_platform.workers.acquisition_worker._try_candidates", side_effect=mock_try),
    ):
        mock_thread.return_value = [_make_candidate()]
        mock_pix.return_value = []

        result = await _acquire_broll(entry, queries, False, "run1", storage, MagicMock(), MagicMock())

    assert result is True
    assert tier_call_count[0] == 2  # advanced to second tier (context_stk)


@pytest.mark.asyncio
async def test_acquire_broll_no_pixabay_when_key_absent():
    """B-roll: Pixabay skipped silently when pixabay client is None (D048)."""
    storage = _make_storage()
    entry = _make_entry(segment_type="B-roll", clip_type="still_with_motion")
    queries = ["housing", "home", "real estate"]

    with (
        patch("cf_platform.workers.acquisition_worker.asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        patch("cf_platform.workers.acquisition_worker._pixabay_photo_candidates", new_callable=AsyncMock) as mock_pix,
        patch("cf_platform.workers.acquisition_worker._try_candidates", new_callable=AsyncMock) as mock_try,
    ):
        mock_thread.return_value = [_make_candidate()]
        mock_pix.return_value = []
        mock_try.return_value = True

        result = await _acquire_broll(entry, queries, False, "run1", storage, MagicMock(), pixabay=None)

    # Pixabay candidate helper never called
    mock_pix.assert_not_called()


# ── Worker integration ────────────────────────────────────────────────────────


def _make_verified_storyboard_artifact() -> dict:
    """Build a minimal VerifiedStoryboardArtifact dict for storage injection."""
    return {
        "prompt_version": "v0.12",
        "scene_count": 2,
        "storyboard": {
            "global": {"subtitle_style": "TikTok", "bg_music": "upbeat", "visual_style": "Documentary"},
            "scenes": [
                {
                    "scene": "1",
                    "clip_type": "still_with_motion",
                    "duration_s": 3.0,
                    "voiceover_line": "Housing prices rose sharply.",
                    "segment_type": "B-roll",
                    "primary_stk": "housing prices graph",
                    "context_stk": "housing",
                    "concept_stk": "economy",
                    "on_screen_text": None,
                    "on_screen_text_type": None,
                    "sfx": "keyboard typing",
                    "sfx_timing": "on cut",
                    "motion_effect": "ken_burns_in",
                    "person_name": None,
                    "person_title": None,
                },
                {
                    "scene": "2",
                    "clip_type": "still_with_motion",
                    "duration_s": 2.5,
                    "voiceover_line": "Jerome Powell signalled higher rates.",
                    "segment_type": "Character",
                    "primary_stk": "Jerome Powell Federal Reserve",
                    "context_stk": "Powell",
                    "concept_stk": "person",
                    "on_screen_text": None,
                    "on_screen_text_type": None,
                    "sfx": "gavel strike",
                    "sfx_timing": "on cut",
                    "motion_effect": None,
                    "person_name": "Jerome Powell",
                    "person_title": "Chair, Federal Reserve",
                },
            ],
            "summary": {"total_scenes": 2, "total_duration_s": 5.5, "rhythm": "SM / SM"},
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.asyncio
async def test_worker_returns_asset_manifest_artifact():
    """Worker reads verified_storyboard and returns AssetManifestArtifact."""
    storage = _make_storage()

    # Write a verified_storyboard artifact to storage
    sb_data = _make_verified_storyboard_artifact()
    sb_key = "users/operator/runs/run42/storyboard/verified_storyboard@v1.json"
    from cf_platform.core.schemas import LineageEnvelope
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact

    lineage = LineageEnvelope(
        run_id="run42", worker="storyboard_worker", worker_version="1.0.0",
        prompt_version="v0.12", model="claude-sonnet-4-6", created_at=datetime.now(timezone.utc),
    )
    from cf_platform.core.schemas import Artifact
    artifact_record = Artifact(
        name="verified_storyboard", stage="storyboard", version=1, run_id="run42",
        r2_key=sb_key, lineage=lineage,
    )
    await storage.put_json(sb_key, {"artifact": artifact_record.model_dump(mode="json"), "body": sb_data})

    state = StageState(
        run_id="run42",
        user_id="operator",
        inputs={},
        artifacts={"verified_storyboard": sb_key},
    )

    with patch("cf_platform.workers.acquisition_worker._acquire_scene", new_callable=AsyncMock) as mock_acquire:
        async def side_effect_mark_acquired(entry, run_id, storage, pexels, pixabay, wikimedia, used_source_urls=None, dup_lock=None):
            entry.status = "acquired"
            entry.source = "pexels"
            entry.file_key = f"runs/{run_id}/images/{entry.scene_id}.jpg"
            entry.qa_passed = True

        mock_acquire.side_effect = side_effect_mark_acquired

        worker = build_acquisition_worker(storage, pexels_api_key="test_key", pixabay_api_key="test_key2")
        output = await worker(state)

    assert isinstance(output.artifact, AssetManifestArtifact)
    result = output.artifact
    assert result.scene_count == 2
    assert result.acquired == 2
    assert result.failed == 0
    assert "manifest" in result.model_dump()
    assert "footage_summary" in result.model_dump()


@pytest.mark.asyncio
async def test_worker_marks_failed_scenes():
    """Worker marks scenes as failed when _acquire_scene raises an exception."""
    storage = _make_storage()

    sb_data = _make_verified_storyboard_artifact()
    sb_key = "users/operator/runs/run99/storyboard/verified_storyboard@v1.json"
    from cf_platform.core.schemas import Artifact, LineageEnvelope
    lineage = LineageEnvelope(
        run_id="run99", worker="storyboard_worker", worker_version="1.0.0",
        prompt_version="v0.12", model="claude-sonnet-4-6", created_at=datetime.now(timezone.utc),
    )
    artifact_record = Artifact(
        name="verified_storyboard", stage="storyboard", version=1, run_id="run99",
        r2_key=sb_key, lineage=lineage,
    )
    await storage.put_json(sb_key, {"artifact": artifact_record.model_dump(mode="json"), "body": sb_data})

    state = StageState(
        run_id="run99",
        user_id="operator",
        inputs={},
        artifacts={"verified_storyboard": sb_key},
    )

    with patch("cf_platform.workers.acquisition_worker._acquire_scene", new_callable=AsyncMock) as mock_acquire:
        mock_acquire.side_effect = RuntimeError("Network error")

        worker = build_acquisition_worker(storage, pexels_api_key="key")
        output = await worker(state)

    result = output.artifact
    assert isinstance(result, AssetManifestArtifact)
    assert result.failed == 2  # both scenes failed
    assert result.acquired == 0
    # Manifest still produced — never left empty
    manifest = AssetManifest.model_validate(result.manifest)
    assert len(manifest.entries) == 2


@pytest.mark.asyncio
async def test_worker_writes_footage_summary_sidecar():
    """Worker writes footage_summary.json side-car to R2 for legacy compat."""
    storage = _make_storage()

    sb_data = _make_verified_storyboard_artifact()
    sb_key = "users/operator/runs/run77/storyboard/verified_storyboard@v1.json"
    from cf_platform.core.schemas import Artifact, LineageEnvelope
    lineage = LineageEnvelope(
        run_id="run77", worker="storyboard_worker", worker_version="1.0.0",
        prompt_version="v0.12", model="claude-sonnet-4-6", created_at=datetime.now(timezone.utc),
    )
    artifact_record = Artifact(
        name="verified_storyboard", stage="storyboard", version=1, run_id="run77",
        r2_key=sb_key, lineage=lineage,
    )
    await storage.put_json(sb_key, {"artifact": artifact_record.model_dump(mode="json"), "body": sb_data})

    state = StageState(
        run_id="run77",
        user_id="operator",
        inputs={},
        artifacts={"verified_storyboard": sb_key},
    )

    with patch("cf_platform.workers.acquisition_worker._acquire_scene", new_callable=AsyncMock):
        worker = build_acquisition_worker(storage, pexels_api_key="key")
        await worker(state)

    sidecar = await storage.get_json("runs/run77/footage_summary.json")
    assert "pexels" in sidecar
    assert "failed" in sidecar


# ── API endpoint: registration ────────────────────────────────────────────────


def test_acquisition_worker_registered_in_worker_registry():
    """AcquisitionWorker registration is present in the api module's worker registry."""
    from cf_platform.interfaces import api as api_module

    registry = api_module._worker_registry
    assert "acquisition_worker" in registry._registrations
