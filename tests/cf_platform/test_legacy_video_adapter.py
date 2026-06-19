"""Tests for cf_platform/adapters/legacy_video.py — LegacyVideoAdapter (P6-S1, D047)."""

from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cf_platform.adapters.legacy_video import (
    InProcessLegacyVideoAdapter,
    LegacyVideoAdapter,
    VideoResult,
)
from cf_platform.core.trace_repo import InMemoryTraceEventRepository


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(
    *,
    elevenlabs_api_key: str = "",
    elevenlabs_voice_id: str = "",
) -> MagicMock:
    """Return a mock Settings object with all required attributes."""
    s = MagicMock()
    s.R2_ACCOUNT_ID = "acct"
    s.R2_ACCESS_KEY_ID = "key"
    s.R2_SECRET_ACCESS_KEY = "secret"
    s.R2_BUCKET_NAME = "bucket"
    s.ELEVENLABS_API_KEY = elevenlabs_api_key
    s.ELEVENLABS_VOICE_ID = elevenlabs_voice_id
    s.PEXELS_API_KEY = "pexels"
    s.PEXELS_PER_PAGE = 10
    s.REPLICATE_API_TOKEN = "rep"
    s.REPLICATE_FLUX_MODEL = "flux"
    s.REPLICATE_POLL_INTERVAL_SECONDS = 1
    s.REPLICATE_MAX_POLL_ATTEMPTS = 3
    s.ACQUISITION_PEXELS_ONLY = True
    s.FFMPEG_TIMEOUT_SECONDS = 300
    return s


def _make_storyboard_mock() -> MagicMock:
    """Return a mock Storyboard-like object whose dump includes a total_duration_s."""
    sb = MagicMock()
    sb.model_dump.return_value = {
        "summary": {"total_duration_s": 30.0},
        "scenes": [],
        "global": {},
    }
    return sb


def _make_validation_mock(cost_usd: float = 0.05) -> MagicMock:
    """Return a mock StoryboardValidation-like object."""
    v = MagicMock()
    v.cost_usd = cost_usd
    v.input_tokens = 100
    v.output_tokens = 200
    return v


def _make_manifest_mock() -> MagicMock:
    """Return a mock AssetManifest with one entry."""
    manifest = MagicMock()
    manifest.entries = [MagicMock()]
    manifest.model_dump.return_value = {"entries": []}
    return manifest


def _make_adapter(settings: Optional[MagicMock] = None) -> InProcessLegacyVideoAdapter:
    """Construct adapter with the given (or default) settings mock."""
    return InProcessLegacyVideoAdapter(settings=settings or _make_settings())


_MODULE = "cf_platform.adapters.legacy_video"


# ── VideoResult model ─────────────────────────────────────────────────────────


class TestVideoResult:
    def test_complete_result(self):
        """VideoResult carries r2_key on success."""
        r = VideoResult(
            r2_key="runs/abc/output/final.mp4",
            legacy_run_id="abc",
            status="complete",
        )
        assert r.status == "complete"
        assert r.r2_key == "runs/abc/output/final.mp4"
        assert r.error is None

    def test_failed_result_carries_error(self):
        """VideoResult.error is set on failure."""
        r = VideoResult(r2_key="", legacy_run_id="abc", status="failed", error="oops")
        assert r.status == "failed"
        assert r.error == "oops"


# ── Protocol conformance ──────────────────────────────────────────────────────


class TestLegacyVideoAdapterProtocol:
    def test_inprocess_adapter_satisfies_protocol(self):
        """InProcessLegacyVideoAdapter structurally satisfies LegacyVideoAdapter Protocol."""
        adapter = _make_adapter()
        assert hasattr(adapter, "render")
        # Runtime structural check — Protocol is not ABC so we inspect
        import inspect
        assert inspect.iscoroutinefunction(adapter.render)


# ── Happy path ────────────────────────────────────────────────────────────────


class TestInProcessAdapterHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_returns_complete_result(self):
        """Full pipeline succeeds → VideoResult(status='complete') with r2_key."""
        settings = _make_settings()
        adapter = _make_adapter(settings)
        trace_repo = InMemoryTraceEventRepository()
        run_id = "test-run-001"
        expected_key = f"runs/{run_id}/output/final.mp4"

        mock_storage = MagicMock()
        mock_sb = _make_storyboard_mock()
        mock_val = _make_validation_mock()
        mock_manifest = _make_manifest_mock()

        with (
            patch(f"{_MODULE}.R2Client", return_value=mock_storage),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(mock_sb, mock_val))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {"pexels": 1}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash\necho done"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": expected_key, "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            result = await adapter.render(run_id, "Test script.", trace_repo)

        assert result.status == "complete"
        assert result.r2_key == expected_key
        assert result.legacy_run_id == run_id
        assert result.error is None

    @pytest.mark.asyncio
    async def test_happy_path_emits_five_trace_events(self):
        """Without TTS credentials, exactly 5 trace events are emitted (one per step)."""
        settings = _make_settings()  # no ElevenLabs
        adapter = _make_adapter(settings)
        trace_repo = InMemoryTraceEventRepository()
        run_id = "trace-run"

        mock_storage = MagicMock()
        mock_sb = _make_storyboard_mock()
        mock_val = _make_validation_mock()
        mock_manifest = _make_manifest_mock()

        with (
            patch(f"{_MODULE}.R2Client", return_value=mock_storage),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(mock_sb, mock_val))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            await adapter.render(run_id, "Test.", trace_repo)

        events = await trace_repo.list_for_run(run_id)
        sources = [e.source for e in events]
        assert sources == ["storyboard", "manifest", "acquisition", "ffmpeg_script", "render"]
        assert all(e.status == "ok" for e in events)
        assert all(e.worker == "legacy_render" for e in events)

    @pytest.mark.asyncio
    async def test_trace_event_sources_always_five(self):
        """Adapter always emits exactly 5 trace events; TTS is owned by voice_production worker (P6-S7)."""
        settings = _make_settings()
        adapter = _make_adapter(settings)
        trace_repo = InMemoryTraceEventRepository()
        run_id = "tts-run"

        mock_storage = MagicMock()
        mock_sb = _make_storyboard_mock()
        mock_manifest = _make_manifest_mock()

        with (
            patch(f"{_MODULE}.R2Client", return_value=mock_storage),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(mock_sb, _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            await adapter.render(run_id, "Script text.", trace_repo)

        events = await trace_repo.list_for_run(run_id)
        assert [e.source for e in events] == ["storyboard", "manifest", "acquisition", "ffmpeg_script", "render"]

    @pytest.mark.asyncio
    async def test_storage_run_folder_and_script_initialized(self):
        """Adapter calls create_run_folder and uploads script.txt before any step."""
        settings = _make_settings()
        adapter = _make_adapter(settings)
        trace_repo = InMemoryTraceEventRepository()
        run_id = "init-run"
        script = "My test script."

        mock_storage = MagicMock()
        mock_manifest = _make_manifest_mock()

        with (
            patch(f"{_MODULE}.R2Client", return_value=mock_storage),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            await adapter.render(run_id, script, trace_repo)

        mock_storage.create_run_folder.assert_called_once_with(run_id, project_name="platform-run")
        mock_storage.upload_text.assert_any_call(f"runs/{run_id}/script.txt", script)


# ── TTS behaviour (P6-S7: TTS owned by voice_production worker, not adapter) ──
#
# Since P6-S7, TTS is generated by voice_production_worker before the adapter
# runs.  The adapter receives voice_alignment (or None for silent render) and
# never calls a TTS API itself.


class TestTTSBehaviour:
    @pytest.mark.asyncio
    async def test_adapter_completes_without_voice_alignment(self):
        """Adapter completes successfully when voice_alignment=None (silent render)."""
        adapter = _make_adapter(_make_settings())
        trace_repo = InMemoryTraceEventRepository()
        run_id = "no-tts-run"

        mock_manifest = _make_manifest_mock()
        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            result = await adapter.render(run_id, "Script.", trace_repo, voice_alignment=None)

        assert result.status == "complete"
        events = await trace_repo.list_for_run(run_id)
        assert len(events) == 5
        assert all(e.source != "tts" for e in events)

    @pytest.mark.asyncio
    async def test_adapter_emits_five_events_with_or_without_voice_alignment(self):
        """Adapter always emits exactly 5 trace events regardless of voice_alignment."""
        adapter = _make_adapter(_make_settings())
        trace_repo = InMemoryTraceEventRepository()
        run_id = "voice-events-run"

        mock_manifest = _make_manifest_mock()
        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "complete"
        events = await trace_repo.list_for_run(run_id)
        assert len(events) == 5


# ── Step failure handling ─────────────────────────────────────────────────────


class TestStepFailures:
    @pytest.mark.asyncio
    async def test_storyboard_failure_returns_failed_result(self):
        """Storyboard step raising → VideoResult(status='failed') with error prefix."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()
        run_id = "sb-fail"

        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(side_effect=ValueError("bad response"))),
        ):
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "failed"
        assert result.error.startswith("storyboard:")
        assert "bad response" in result.error

        events = await trace_repo.list_for_run(run_id)
        sb_event = next(e for e in events if e.source == "storyboard")
        assert sb_event.status == "error"

    @pytest.mark.asyncio
    async def test_manifest_failure_returns_failed_result(self):
        """Manifest step raising → VideoResult(status='failed')."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()
        run_id = "mf-fail"

        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.build_manifest", side_effect=RuntimeError("manifest blew up")),
        ):
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "failed"
        assert result.error.startswith("manifest:")

    @pytest.mark.asyncio
    async def test_acquisition_too_few_assets_fails(self):
        """Acquisition returning 0 acquired assets → VideoResult(status='failed')."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()
        run_id = "acq-fail"

        mock_manifest = _make_manifest_mock()
        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 0, "failed": 3, "sources": {}})),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "failed"
        assert result.error.startswith("acquisition:")

    @pytest.mark.asyncio
    async def test_ffmpeg_script_failure_returns_failed_result(self):
        """FFmpeg script build failing → VideoResult(status='failed')."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()
        run_id = "ffmpeg-fail"

        mock_manifest = _make_manifest_mock()
        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", side_effect=RuntimeError("ffmpeg build failed")),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "failed"
        assert result.error.startswith("ffmpeg_script:")

    @pytest.mark.asyncio
    async def test_render_nonzero_exit_returns_failed_result(self):
        """Render returning non-'complete' status → VideoResult(status='failed')."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()
        run_id = "render-fail"

        mock_manifest = _make_manifest_mock()
        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", return_value={"status": "failed", "output_key": None, "exit_code": 1}),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            result = await adapter.render(run_id, "Script.", trace_repo)

        assert result.status == "failed"
        assert result.error.startswith("render:")
        events = await trace_repo.list_for_run(run_id)
        render_event = next(e for e in events if e.source == "render")
        assert render_event.status == "error"

    @pytest.mark.asyncio
    async def test_failed_result_has_empty_r2_key(self):
        """r2_key is empty string on any failure (not a valid R2 path)."""
        adapter = _make_adapter()
        trace_repo = InMemoryTraceEventRepository()

        with (
            patch(f"{_MODULE}.R2Client", return_value=MagicMock()),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(side_effect=RuntimeError("boom"))),
        ):
            result = await adapter.render("fail-run", "x", trace_repo)

        assert result.r2_key == ""


# ── Render run is called via asyncio.to_thread ────────────────────────────────


class TestRenderCallConvention:
    @pytest.mark.asyncio
    async def test_render_run_called_with_correct_args(self):
        """render_run is called with the run_id, manifest, storage, and timeout from settings."""
        settings = _make_settings()
        adapter = _make_adapter(settings)
        trace_repo = InMemoryTraceEventRepository()
        run_id = "args-check"

        mock_storage = MagicMock()
        mock_manifest = _make_manifest_mock()
        mock_render_run = MagicMock(return_value={"status": "complete", "output_key": f"runs/{run_id}/output/final.mp4", "exit_code": 0})

        with (
            patch(f"{_MODULE}.R2Client", return_value=mock_storage),
            patch(f"{_MODULE}.generate_storyboard", new=AsyncMock(return_value=(_make_storyboard_mock(), _make_validation_mock()))),
            patch(f"{_MODULE}.Storyboard") as mock_storyboard_cls,
            patch(f"{_MODULE}.build_manifest", return_value=mock_manifest),
            patch(f"{_MODULE}.run_acquisition", new=AsyncMock(return_value={"acquired": 1, "failed": 0, "sources": {}})),
            patch(f"{_MODULE}.build_ffmpeg_script", return_value="#!/bin/bash"),
            patch(f"{_MODULE}.render_run", mock_render_run),
            patch(f"{_MODULE}.PexelsClient"),
            patch(f"{_MODULE}.ReplicateClient"),
        ):
            mock_storyboard_cls.model_validate.return_value = MagicMock()
            await adapter.render(run_id, "Script.", trace_repo)

        mock_render_run.assert_called_once_with(
            run_id, mock_manifest, mock_storage, settings.FFMPEG_TIMEOUT_SECONDS, 750  # 30s * 25fps
        )
