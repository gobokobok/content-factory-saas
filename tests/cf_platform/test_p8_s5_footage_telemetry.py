"""Tests for P8-S5: footage_summary computation, formatting, and Telegram reply wiring."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.adapters.legacy_video import VideoResult, _compute_footage_summary
from cf_platform.interfaces.telegram import format_footage_summary, format_produce_reply
from src.models import AssetManifest, ManifestEntry

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_entry(
    scene_id: str,
    status: str = "acquired",
    source: str = "pexels",
    qa_passed: bool | None = True,
) -> ManifestEntry:
    """Build a minimal ManifestEntry for testing."""
    return ManifestEntry(
        scene_id=scene_id,
        clip_type="hard_cut",
        primary_query="test",
        fallback_query="test fallback",
        ai_generate_prompt="test prompt",
        status=status,
        source=source if status == "acquired" else None,
        qa_passed=qa_passed,
        file_key=f"runs/test-run/images/{scene_id}.jpg" if status == "acquired" else None,
    )


def _make_manifest(entries: list[ManifestEntry]) -> AssetManifest:
    """Build an AssetManifest from a list of entries."""
    return AssetManifest(run_id="test-run", entries=entries)


# ── _compute_footage_summary ──────────────────────────────────────────────────


class TestComputeFootageSummary:
    def test_counts_all_sources(self) -> None:
        """Each known source type is counted correctly."""
        manifest = _make_manifest([
            _make_entry("s1", source="pexels"),
            _make_entry("s2", source="pexels"),
            _make_entry("s3", source="pixabay"),
            _make_entry("s4", source="wikimedia"),
            _make_entry("s5", source="wikimedia_person"),
            _make_entry("s6", source="replicate"),
        ])
        result = _compute_footage_summary(manifest)
        assert result["pexels"] == 2
        assert result["pixabay"] == 1
        assert result["wikimedia"] == 1
        assert result["wikimedia_person"] == 1
        assert result["replicate"] == 1
        assert result["failed"] == 0
        assert result["qa_failed_scenes"] == 0

    def test_counts_failed_entries(self) -> None:
        """Entries with status='failed' increment the failed counter."""
        manifest = _make_manifest([
            _make_entry("s1", source="pexels"),
            _make_entry("s2", status="failed", source=""),
        ])
        result = _compute_footage_summary(manifest)
        assert result["pexels"] == 1
        assert result["failed"] == 1

    def test_counts_qa_failed_scenes(self) -> None:
        """Entries with qa_passed=False (accepted best-available) are counted separately."""
        manifest = _make_manifest([
            _make_entry("s1", source="pexels", qa_passed=True),
            _make_entry("s2", source="pixabay", qa_passed=False),
            _make_entry("s3", source="wikimedia", qa_passed=False),
        ])
        result = _compute_footage_summary(manifest)
        assert result["qa_failed_scenes"] == 2

    def test_qa_none_not_counted_as_failure(self) -> None:
        """qa_passed=None (person photos, etc.) is not counted as a QA failure."""
        manifest = _make_manifest([
            _make_entry("s1", source="wikimedia_person", qa_passed=None),
        ])
        result = _compute_footage_summary(manifest)
        assert result["qa_failed_scenes"] == 0

    def test_empty_manifest_returns_zero_counts(self) -> None:
        """An empty manifest yields all-zero summary."""
        result = _compute_footage_summary(_make_manifest([]))
        assert all(v == 0 for v in result.values())

    def test_unknown_source_not_counted_in_known_keys(self) -> None:
        """An unknown source value doesn't increment any known counter or crash."""
        manifest = _make_manifest([
            _make_entry("s1", source="unknown_future_source"),
        ])
        result = _compute_footage_summary(manifest)
        assert result["pexels"] == 0
        assert result["pixabay"] == 0


# ── format_footage_summary ────────────────────────────────────────────────────


class TestFormatFootageSummary:
    def test_all_sources_present(self) -> None:
        """Coverage line lists every source that has a non-zero count."""
        summary = {
            "pexels": 14, "pixabay": 4, "wikimedia": 3,
            "wikimedia_person": 2, "replicate": 3,
            "failed": 0, "qa_failed_scenes": 0,
        }
        text = format_footage_summary(summary)
        assert "14 Pexels" in text
        assert "4 Pixabay" in text
        assert "3 Wikimedia" in text
        assert "2 Person" in text
        assert "3 AI" in text
        assert text.startswith("Footage:")

    def test_zero_count_sources_omitted(self) -> None:
        """Sources with count=0 do not appear in the coverage line."""
        summary = {"pexels": 5, "pixabay": 0, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 0}
        text = format_footage_summary(summary)
        assert "Pixabay" not in text
        assert "Wikimedia" not in text
        assert "5 Pexels" in text

    def test_qa_warning_shown_when_nonzero(self) -> None:
        """QA warning line appears when qa_failed_scenes > 0."""
        summary = {"pexels": 5, "pixabay": 0, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 3}
        text = format_footage_summary(summary)
        assert "⚠️" in text
        assert "3 scenes below QA threshold" in text

    def test_no_qa_warning_when_zero(self) -> None:
        """No QA warning when qa_failed_scenes is 0."""
        summary = {"pexels": 5, "pixabay": 0, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 0}
        text = format_footage_summary(summary)
        assert "⚠️" not in text

    def test_empty_summary_shows_none(self) -> None:
        """All-zero summary shows (none) placeholder rather than crashing."""
        summary = {"pexels": 0, "pixabay": 0, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 0}
        text = format_footage_summary(summary)
        assert "Footage: (none)" in text


# ── format_produce_reply — footage_summary integration ───────────────────────


class TestFormatProduceReplyWithSummary:
    def test_no_summary_backward_compat(self) -> None:
        """format_produce_reply with footage_summary=None is unchanged from P7 behaviour."""
        text = format_produce_reply("My Idea", "run-123", "https://example.com/v.mp4")
        assert "My Idea" in text
        assert "run-123" in text
        assert "Footage:" not in text

    def test_summary_appended_when_provided(self) -> None:
        """Coverage line appears in the reply when footage_summary is provided."""
        summary = {"pexels": 10, "pixabay": 2, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 0}
        text = format_produce_reply(
            "My Idea", "run-123", "https://example.com/v.mp4",
            footage_summary=summary,
        )
        assert "Footage:" in text
        assert "10 Pexels" in text

    def test_summary_before_metadata_block(self) -> None:
        """Coverage line appears before the YouTube metadata block."""
        from datetime import datetime

        from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

        meta = YoutubeMetadataArtifact(
            title="Test Title",
            description="Test desc",
            tags=["tag1"],
            generated_at=datetime.utcnow().isoformat(),
        )
        summary = {"pexels": 3, "pixabay": 0, "wikimedia": 0,
                   "wikimedia_person": 0, "replicate": 0,
                   "failed": 0, "qa_failed_scenes": 0}
        text = format_produce_reply(
            "My Idea", "run-123", "https://example.com/v.mp4",
            metadata=meta,
            footage_summary=summary,
        )
        footage_pos = text.index("Footage:")
        metadata_pos = text.index("YouTube Metadata")
        assert footage_pos < metadata_pos


# ── VideoResult model ─────────────────────────────────────────────────────────


class TestVideoResultModel:
    def test_footage_summary_defaults_to_none(self) -> None:
        """VideoResult.footage_summary is Optional and defaults to None."""
        result = VideoResult(r2_key="key", legacy_run_id="run-1", status="complete")
        assert result.footage_summary is None

    def test_footage_summary_set(self) -> None:
        """VideoResult.footage_summary can carry the computed dict."""
        fs = {"pexels": 5, "pixabay": 2, "wikimedia": 0,
              "wikimedia_person": 0, "replicate": 0,
              "failed": 0, "qa_failed_scenes": 0}
        result = VideoResult(
            r2_key="key", legacy_run_id="run-1", status="complete",
            footage_summary=fs,
        )
        assert result.footage_summary == fs


# ── InProcessLegacyVideoAdapter.render — footage_summary ─────────────────────


class TestAdapterFootageSummary:
    """Verify the adapter sets footage_summary on VideoResult after acquisition."""

    def _build_manifest(self) -> AssetManifest:
        return _make_manifest([
            _make_entry("s1", source="pexels"),
            _make_entry("s2", source="pixabay"),
        ])

    @pytest.mark.asyncio
    async def test_adapter_sets_footage_summary_on_success(self) -> None:
        """After a successful acquisition the adapter sets footage_summary on VideoResult."""
        from cf_platform.adapters.legacy_video import InProcessLegacyVideoAdapter

        manifest = self._build_manifest()

        mock_settings = MagicMock()
        mock_settings.PEXELS_API_KEY = "pk"
        mock_settings.PEXELS_PER_PAGE = 10
        mock_settings.PIXABAY_API_KEY = "pb"
        mock_settings.ACQUISITION_BATCH_SIZE = 4
        mock_settings.FFMPEG_TIMEOUT_SECONDS = 120

        mock_storage = MagicMock()
        mock_storage.create_run_folder = MagicMock()
        mock_storage.upload_text = MagicMock()
        mock_storage.upload_json = MagicMock()

        storyboard_data = {
            "global": {"subtitle_style": "none", "bg_music": "none", "visual_style": "Realistic"},
            "scenes": [],
            "summary": {"total_scenes": 0, "total_duration_s": 0.0, "rhythm": "fast"},
        }

        adapter = InProcessLegacyVideoAdapter(settings=mock_settings)
        adapter._make_storage = lambda: mock_storage

        mock_trace_repo = AsyncMock()

        with (
            patch("cf_platform.adapters.legacy_video.generate_storyboard") as mock_sb,
            patch("cf_platform.adapters.legacy_video.build_manifest") as mock_bm,
            patch("cf_platform.adapters.legacy_video.run_acquisition") as mock_acq,
            patch("cf_platform.adapters.legacy_video.build_ffmpeg_script") as mock_ffmpeg,
            patch("cf_platform.adapters.legacy_video.render_run") as mock_render,
            patch("cf_platform.adapters.legacy_video.MIN_ACQUIRED_FOR_COMPLETE", 0),
        ):
            mock_validation = MagicMock()
            mock_validation.cost_usd = 0.01
            mock_sb.return_value = (MagicMock(model_dump=MagicMock(return_value=storyboard_data)), mock_validation)
            mock_bm.return_value = manifest
            mock_acq.return_value = {"acquired": 2, "failed": 0, "sources": {"pexels": 1, "pixabay": 1}}
            mock_ffmpeg.return_value = "ffmpeg script"
            mock_render.return_value = {"status": "complete", "output_key": "runs/run-1/output/final.mp4", "exit_code": 0}

            result = await adapter.render("run-1", "Script text", mock_trace_repo)

        assert result.status == "complete"
        assert result.footage_summary is not None
        assert result.footage_summary["pexels"] == 1
        assert result.footage_summary["pixabay"] == 1

    @pytest.mark.asyncio
    async def test_adapter_footage_summary_none_on_acquisition_failure(self) -> None:
        """When acquisition raises, footage_summary stays None and status is failed."""
        from cf_platform.adapters.legacy_video import InProcessLegacyVideoAdapter

        manifest = self._build_manifest()
        mock_settings = MagicMock()
        mock_settings.PEXELS_API_KEY = "pk"
        mock_settings.PEXELS_PER_PAGE = 10
        mock_settings.PIXABAY_API_KEY = ""
        mock_settings.ACQUISITION_BATCH_SIZE = 4
        mock_settings.FFMPEG_TIMEOUT_SECONDS = 120

        mock_storage = MagicMock()
        mock_storage.create_run_folder = MagicMock()
        mock_storage.upload_text = MagicMock()
        mock_storage.upload_json = MagicMock()

        storyboard_data = {
            "global": {"subtitle_style": "none", "bg_music": "none", "visual_style": "Realistic"},
            "scenes": [],
            "summary": {"total_scenes": 0, "total_duration_s": 0.0, "rhythm": "fast"},
        }

        adapter = InProcessLegacyVideoAdapter(settings=mock_settings)
        adapter._make_storage = lambda: mock_storage

        mock_trace_repo = AsyncMock()

        with (
            patch("cf_platform.adapters.legacy_video.generate_storyboard") as mock_sb,
            patch("cf_platform.adapters.legacy_video.build_manifest") as mock_bm,
            patch("cf_platform.adapters.legacy_video.run_acquisition") as mock_acq,
        ):
            mock_validation = MagicMock()
            mock_validation.cost_usd = 0.01
            mock_sb.return_value = (MagicMock(model_dump=MagicMock(return_value=storyboard_data)), mock_validation)
            mock_bm.return_value = manifest
            mock_acq.side_effect = RuntimeError("Network failure")

            result = await adapter.render("run-1", "Script text", mock_trace_repo)

        assert result.status == "failed"
        assert result.footage_summary is None
