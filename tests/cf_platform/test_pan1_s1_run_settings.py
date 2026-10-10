"""Tests for P-AN1-S1: a run's visual mode and master style in settings.json (D108)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cf_platform.core.ai_images import resolve_master_style
from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.run_visuals import load_run_visuals, visuals_from
from src.config import Settings, get_settings
from src.main import app
from src.models import VideoSettings
from src.routes.runs import merge_video_settings
from tests.cf_platform.p13_helpers import VALID_ENV

RUN_ID = "2026-10-11_animation"
OLD_SETTINGS = {"aspect_ratio": "9:16", "visual_style": "Realistic", "subtitles": "TikTok", "caption_style": "punch"}


@pytest.fixture
def client():
    """TestClient with legacy settings injected."""
    app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
    yield TestClient(app)
    app.dependency_overrides.pop(get_settings, None)


class TestModel:
    def test_defaults_are_stock_with_no_style_and_no_cap(self):
        s = VideoSettings()
        assert (s.visual_mode, s.master_style, s.image_spend_cap_usd) == ("stock", "", None)

    def test_settings_stored_before_the_new_keys_load_unchanged(self):
        s = VideoSettings.model_validate(OLD_SETTINGS)
        assert s.visual_mode == "stock" and s.master_style == "" and s.caption_style == "punch"

    def test_round_trip_keeps_mode_and_style(self):
        s = VideoSettings(visual_mode="ai_animation", master_style="  ink and wash  ")
        again = VideoSettings.model_validate(s.model_dump())
        assert again.visual_mode == "ai_animation" and again.master_style == "ink and wash"

    def test_unknown_mode_is_rejected_and_null_style_is_empty(self):
        with pytest.raises(ValueError):
            VideoSettings(visual_mode="cartoon")
        assert VideoSettings.model_validate({"master_style": None}).master_style == ""


class TestMerge:
    def test_a_patch_without_the_new_fields_keeps_the_stored_ones(self):
        stored = VideoSettings(visual_mode="ai_animation", master_style="ink", image_spend_cap_usd=4.0)
        merged = merge_video_settings(stored, VideoSettings.model_validate({"aspect_ratio": "9:16"}))
        assert (merged.visual_mode, merged.master_style, merged.image_spend_cap_usd) == ("ai_animation", "ink", 4.0)
        assert merged.aspect_ratio == "9:16"

    def test_a_field_the_patch_names_wins_even_when_it_is_the_default(self):
        stored = VideoSettings(visual_mode="ai_animation", master_style="ink")
        merged = merge_video_settings(stored, VideoSettings.model_validate({"visual_mode": "stock", "master_style": ""}))
        assert (merged.visual_mode, merged.master_style) == ("stock", "")

    def test_without_stored_settings_the_patch_is_the_result(self):
        patch_ = VideoSettings(visual_mode="ai_animation")
        assert merge_video_settings(None, patch_) is patch_


class TestRoute:
    def test_post_then_get_round_trips_mode_and_style(self, client):
        store: dict = {}
        r2 = MagicMock()
        r2.upload_json.side_effect = lambda key, data: store.__setitem__(key, data)
        r2.get_json.side_effect = lambda key: store[key]
        with patch("src.routes.runs.R2Client", return_value=r2):
            store[f"runs/{RUN_ID}/settings.json"] = dict(OLD_SETTINGS)
            r = client.post(f"/runs/{RUN_ID}/settings", json={"visual_mode": "ai_animation", "master_style": "ink"})
            assert r.status_code == 200, r.text
            got = client.get(f"/runs/{RUN_ID}/settings").json()["settings"]
        assert (got["visual_mode"], got["master_style"]) == ("ai_animation", "ink")
        # the fields the request did not name were not reset
        assert got["caption_style"] == "punch" and got["aspect_ratio"] == "9:16"

    def test_an_older_client_does_not_reset_the_mode(self, client):
        store = {f"runs/{RUN_ID}/settings.json": {**OLD_SETTINGS, "visual_mode": "ai_animation", "master_style": "ink"}}
        r2 = MagicMock()
        r2.upload_json.side_effect = lambda key, data: store.__setitem__(key, data)
        r2.get_json.side_effect = lambda key: store[key]
        with patch("src.routes.runs.R2Client", return_value=r2):
            client.post(f"/runs/{RUN_ID}/settings", json={"aspect_ratio": "16:9", "subtitles": "none"})
        saved = store[f"runs/{RUN_ID}/settings.json"]
        assert (saved["visual_mode"], saved["master_style"], saved["aspect_ratio"]) == ("ai_animation", "ink", "16:9")

    def test_unknown_mode_is_422(self, client):
        with patch("src.routes.runs.R2Client", return_value=MagicMock()):
            assert client.post(f"/runs/{RUN_ID}/settings", json={"visual_mode": "cartoon"}).status_code == 422


class TestInheritance:
    def test_the_run_value_wins(self):
        assert resolve_master_style(" run style ", {"ai_image_style": "project style"}) == "run style"

    def test_an_empty_run_value_falls_back_to_the_project(self):
        assert resolve_master_style("  ", {"ai_image_style": " project style "}) == "project style"

    def test_nothing_anywhere_is_none(self):
        assert resolve_master_style("", {}) is None
        assert resolve_master_style(None, None) is None
        assert resolve_master_style("", {"ai_image_style": 7}) is None

    def test_visuals_from_resolves_mode_style_aspect_and_cap(self):
        v = visuals_from(
            {"visual_mode": "ai_animation", "aspect_ratio": "16:9", "image_spend_cap_usd": "4"},
            {"ai_image_style": "project style"},
        )
        assert v.is_animation and v.master_style == "project style" and v.project_style == "project style"
        assert (v.aspect_ratio, v.spend_cap_usd) == ("16:9", 4.0)

    def test_garbage_settings_are_the_stock_default(self):
        v = visuals_from({"visual_mode": "x", "aspect_ratio": "4:3", "image_spend_cap_usd": "lots"}, None)
        assert (v.visual_mode, v.master_style, v.aspect_ratio, v.spend_cap_usd) == ("stock", None, None, None)

    @pytest.mark.asyncio
    async def test_a_run_without_settings_json_is_stock(self):
        v = await load_run_visuals(InMemoryArtifactStorage(), "no-such-run")
        assert not v.is_animation and v.master_style is None
