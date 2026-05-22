"""Tests for asset manifest generation — src/manifest.py and POST /runs/{run_id}/manifest."""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import ManifestError, StorageError
from src.main import app
from src.manifest import build_manifest, clip_type_breakdown
from src.models import AssetManifest, ManifestEntry


# ── Fixtures & helpers ─────────────────────────────────────────────────────────

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
}

RUN_ID = "2026-05-22_test-run"
MANIFEST_KEY = f"runs/{RUN_ID}/asset_manifest.json"
STORYBOARD_KEY = f"runs/{RUN_ID}/storyboard.json"


def _make_settings(**overrides) -> Settings:
    """Build a Settings instance from VALID_ENV with optional field overrides."""
    return Settings.model_validate({**VALID_ENV, **overrides})


def _make_storyboard_data(
    scenes: Optional[List[dict]] = None,
) -> dict:
    """Return a minimal valid storyboard dict suitable for Storyboard.model_validate."""
    if scenes is None:
        scenes = [
            {
                "scene": "01",
                "clip_type": "hard_cut",
                "duration_s": 3.0,
                "voiceover_line": "Housing costs are up.",
                "visual_prompts": {
                    "primary_stk": "city skyline real estate",
                    "fallback_stk": "urban apartment buildings",
                    "ai_generate": "photorealistic city skyline at dusk, housing crisis",
                },
                "sfx": "none",
                "sfx_timing": "n/a",
            },
            {
                "scene": "02",
                "clip_type": "still_with_motion",
                "duration_s": 4.5,
                "voiceover_line": "Rents have doubled.",
                "visual_prompts": {
                    "primary_stk": "rent eviction notice",
                    "fallback_stk": "apartment lease document",
                    "ai_generate": "close-up of eviction notice on door",
                },
                "motion_effect": "zoom_in",
                "sfx": "paper_rustle",
                "sfx_timing": "0.5s",
            },
        ]
    return {
        "global": {
            "subtitle_style": "bold_white",
            "bg_music": "ambient_tension",
            "visual_style": "documentary",
        },
        "scenes": scenes,
        "summary": {
            "total_scenes": len(scenes),
            "total_duration_s": sum(s["duration_s"] for s in scenes),
            "rhythm": "slow",
        },
    }


# ── Unit tests: build_manifest ─────────────────────────────────────────────────


class TestBuildManifest:
    def test_returns_asset_manifest_instance(self):
        """build_manifest returns an AssetManifest model."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert isinstance(result, AssetManifest)

    def test_run_id_preserved(self):
        """AssetManifest carries the supplied run_id."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.run_id == RUN_ID

    def test_entry_count_matches_scenes(self):
        """One ManifestEntry per storyboard scene."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert len(result.entries) == 2

    def test_scene_id_mapped(self):
        """scene_id is taken from StoryboardScene.scene."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.entries[0].scene_id == "01"
        assert result.entries[1].scene_id == "02"

    def test_clip_type_mapped(self):
        """clip_type is preserved from the storyboard scene."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.entries[0].clip_type == "hard_cut"
        assert result.entries[1].clip_type == "still_with_motion"

    def test_primary_query_from_primary_stk(self):
        """primary_query maps from visual_prompts.primary_stk."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.entries[0].primary_query == "city skyline real estate"

    def test_fallback_query_from_fallback_stk(self):
        """fallback_query maps from visual_prompts.fallback_stk."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.entries[0].fallback_query == "urban apartment buildings"

    def test_ai_generate_prompt_from_ai_generate(self):
        """ai_generate_prompt maps from visual_prompts.ai_generate."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert result.entries[0].ai_generate_prompt == (
            "photorealistic city skyline at dusk, housing crisis"
        )

    def test_all_entries_status_pending(self):
        """Every ManifestEntry is initialised with status 'pending'."""
        result = build_manifest(RUN_ID, _make_storyboard_data())
        assert all(e.status == "pending" for e in result.entries)

    def test_invalid_storyboard_raises_manifest_error(self):
        """build_manifest raises ManifestError when storyboard data is invalid."""
        with pytest.raises(ManifestError):
            build_manifest(RUN_ID, {"bad": "data"})

    def test_single_scene_storyboard(self):
        """A one-scene storyboard produces exactly one manifest entry."""
        data = _make_storyboard_data(
            scenes=[
                {
                    "scene": "01",
                    "clip_type": "animated",
                    "duration_s": 2.0,
                    "voiceover_line": "Test line.",
                    "visual_prompts": {
                        "primary_stk": "p",
                        "fallback_stk": "f",
                        "ai_generate": "a",
                    },
                    "sfx": "none",
                    "sfx_timing": "n/a",
                }
            ]
        )
        result = build_manifest(RUN_ID, data)
        assert len(result.entries) == 1


# ── Unit tests: clip_type_breakdown ───────────────────────────────────────────


class TestClipTypeBreakdown:
    def _manifest(self, clip_types: list[str]) -> AssetManifest:
        """Build a minimal AssetManifest with the given clip_types."""
        entries = [
            ManifestEntry(
                scene_id=str(i),
                clip_type=ct,  # type: ignore[arg-type]
                primary_query="p",
                fallback_query="f",
                ai_generate_prompt="a",
            )
            for i, ct in enumerate(clip_types)
        ]
        return AssetManifest(run_id=RUN_ID, entries=entries)

    def test_single_type(self):
        """All hard_cut → {'hard_cut': N}."""
        m = self._manifest(["hard_cut", "hard_cut", "hard_cut"])
        assert clip_type_breakdown(m) == {"hard_cut": 3}

    def test_mixed_types(self):
        """Mixed clip types are counted independently."""
        m = self._manifest(["hard_cut", "still_with_motion", "hard_cut", "animated"])
        breakdown = clip_type_breakdown(m)
        assert breakdown["hard_cut"] == 2
        assert breakdown["still_with_motion"] == 1
        assert breakdown["animated"] == 1

    def test_empty_manifest(self):
        """Empty entries list returns empty dict."""
        m = AssetManifest(run_id=RUN_ID, entries=[])
        assert clip_type_breakdown(m) == {}


# ── Integration tests: POST /runs/{run_id}/manifest ───────────────────────────


@pytest.fixture()
def client():
    """TestClient with settings injected."""
    settings = _make_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def mock_r2(client):
    """Patch R2Client in the manifest route. Preconfigures get_json with valid storyboard."""
    mock_instance = MagicMock()
    mock_instance.get_json.return_value = _make_storyboard_data()
    with patch("src.routes.manifest.R2Client", return_value=mock_instance):
        yield mock_instance


class TestCreateManifestRoute:
    def test_returns_200_on_success(self, client, mock_r2):
        """POST /runs/{run_id}/manifest returns HTTP 200 for a valid storyboard."""
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.status_code == 200

    def test_response_status_complete(self, client, mock_r2):
        """Response body status field is 'complete'."""
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.json()["status"] == "complete"

    def test_response_manifest_key(self, client, mock_r2):
        """manifest_key in response points to the correct R2 path."""
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.json()["manifest_key"] == MANIFEST_KEY

    def test_response_scene_count(self, client, mock_r2):
        """scene_count matches the number of scenes in the storyboard."""
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.json()["scene_count"] == 2

    def test_response_clip_type_breakdown(self, client, mock_r2):
        """clip_type_breakdown reflects actual scene distribution."""
        response = client.post(f"/runs/{RUN_ID}/manifest")
        breakdown = response.json()["clip_type_breakdown"]
        assert breakdown["hard_cut"] == 1
        assert breakdown["still_with_motion"] == 1

    def test_storyboard_read_from_correct_key(self, client, mock_r2):
        """R2Client.get_json is called with the run's storyboard.json key."""
        client.post(f"/runs/{RUN_ID}/manifest")
        mock_r2.get_json.assert_called_once_with(STORYBOARD_KEY)

    def test_manifest_uploaded_to_correct_key(self, client, mock_r2):
        """R2Client.upload_json is called with the run's asset_manifest.json key."""
        client.post(f"/runs/{RUN_ID}/manifest")
        mock_r2.upload_json.assert_called_once_with(MANIFEST_KEY, mock_r2.upload_json.call_args[0][1])

    def test_run_log_updated_complete(self, client, mock_r2):
        """update_run_log is called with 'asset_manifest' and 'complete'."""
        client.post(f"/runs/{RUN_ID}/manifest")
        mock_r2.update_run_log.assert_called_once_with(
            RUN_ID, "asset_manifest", "complete", output_url=MANIFEST_KEY
        )

    def test_storyboard_not_found_returns_404(self, client, mock_r2):
        """StorageError reading storyboard maps to HTTP 404."""
        mock_r2.get_json.side_effect = StorageError("key not found")
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.status_code == 404

    def test_invalid_storyboard_returns_422(self, client, mock_r2):
        """Corrupt storyboard data (ManifestError) maps to HTTP 422."""
        mock_r2.get_json.return_value = {"not": "a storyboard"}
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.status_code == 422

    def test_invalid_storyboard_updates_run_log_failed(self, client, mock_r2):
        """run_log is updated to 'failed' when storyboard is invalid."""
        mock_r2.get_json.return_value = {"not": "a storyboard"}
        client.post(f"/runs/{RUN_ID}/manifest")
        mock_r2.update_run_log.assert_called_once()
        call_kwargs = mock_r2.update_run_log.call_args
        assert call_kwargs[0][2] == "failed"

    def test_upload_error_returns_500(self, client, mock_r2):
        """StorageError during upload maps to HTTP 500."""
        mock_r2.upload_json.side_effect = StorageError("upload failed")
        response = client.post(f"/runs/{RUN_ID}/manifest")
        assert response.status_code == 500

    def test_r2_client_constructed_with_settings(self, client):
        """R2Client is constructed with the four R2 ENV vars from settings."""
        mock_instance = MagicMock()
        mock_instance.get_json.return_value = _make_storyboard_data()
        with patch("src.routes.manifest.R2Client", return_value=mock_instance) as mock_cls:
            client.post(f"/runs/{RUN_ID}/manifest")
            mock_cls.assert_called_once_with(
                "fake-account-id", "fake-access-key", "fake-secret-key", "content-factory-dev"
            )
