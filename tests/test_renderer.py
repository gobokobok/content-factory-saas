"""Tests for src/renderer.py and the render routes."""

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.exceptions import RenderError, StorageError
from src.main import app
from src.models import AssetManifest, ManifestEntry

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "ANTHROPIC_API_KEY": "test-anthropic",
    "PEXELS_API_KEY": "test-pexels",
    "REPLICATE_API_TOKEN": "test-replicate",
    "FREESOUND_API_KEY": "test-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret-key",
}

RUN_ID = "2026-05-22_test-run"


@pytest.fixture
def settings():
    """Settings with all required ENV vars."""
    return Settings(**VALID_ENV)


@pytest.fixture
def client(settings):
    """TestClient with settings injected."""
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def manifest():
    """A two-entry AssetManifest with one acquired video and one acquired image."""
    return AssetManifest(
        run_id=RUN_ID,
        entries=[
            ManifestEntry(
                scene_id="01",
                clip_type="hard_cut",
                primary_query="q1",
                fallback_query="f1",
                ai_generate_prompt="p1",
                status="acquired",
                file_key=f"runs/{RUN_ID}/video/01.mp4",
            ),
            ManifestEntry(
                scene_id="02",
                clip_type="still_with_motion",
                primary_query="q2",
                fallback_query="f2",
                ai_generate_prompt="p2",
                status="acquired",
                file_key=f"runs/{RUN_ID}/images/02.jpeg",
            ),
        ],
    )


# ── Storage additions: get_bytes ───────────────────────────────────────────────


class TestR2ClientGetBytes:
    def test_returns_bytes_on_success(self):
        with patch("src.storage.boto3.client") as mock_boto:
            mock_s3 = mock_boto.return_value
            mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: b"raw data")}
            from src.storage import R2Client

            r2 = R2Client("acc", "key", "secret", "bucket")
            result = r2.get_bytes("runs/x/video/01.mp4")

        assert result == b"raw data"
        mock_s3.get_object.assert_called_once_with(Bucket="bucket", Key="runs/x/video/01.mp4")

    def test_raises_storage_error_on_client_error(self):
        from botocore.exceptions import ClientError

        with patch("src.storage.boto3.client") as mock_boto:
            mock_s3 = mock_boto.return_value
            mock_s3.get_object.side_effect = ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject"
            )
            from src.storage import R2Client

            r2 = R2Client("acc", "key", "secret", "bucket")
            with pytest.raises(StorageError):
                r2.get_bytes("missing/key")


# ── Storage additions: list_keys ──────────────────────────────────────────────


class TestR2ClientListKeys:
    def test_returns_list_of_keys(self):
        with patch("src.storage.boto3.client") as mock_boto:
            mock_s3 = mock_boto.return_value
            mock_s3.list_objects_v2.return_value = {
                "Contents": [
                    {"Key": "runs/x/voiceover/vo.mp3"},
                    {"Key": "runs/x/voiceover/vo2.mp3"},
                ]
            }
            from src.storage import R2Client

            r2 = R2Client("acc", "key", "secret", "bucket")
            result = r2.list_keys("runs/x/voiceover/")

        assert result == ["runs/x/voiceover/vo.mp3", "runs/x/voiceover/vo2.mp3"]

    def test_returns_empty_list_when_no_objects(self):
        with patch("src.storage.boto3.client") as mock_boto:
            mock_s3 = mock_boto.return_value
            mock_s3.list_objects_v2.return_value = {}
            from src.storage import R2Client

            r2 = R2Client("acc", "key", "secret", "bucket")
            result = r2.list_keys("runs/x/voiceover/")

        assert result == []

    def test_raises_storage_error_on_failure(self):
        from botocore.exceptions import BotoCoreError

        with patch("src.storage.boto3.client") as mock_boto:
            mock_s3 = mock_boto.return_value
            mock_s3.list_objects_v2.side_effect = BotoCoreError()
            from src.storage import R2Client

            r2 = R2Client("acc", "key", "secret", "bucket")
            with pytest.raises(StorageError):
                r2.list_keys("runs/x/voiceover/")


# ── renderer: _write_run_log_txt ──────────────────────────────────────────────


class TestWriteRunLogTxt:
    def test_uploads_to_correct_key(self):
        from src.renderer import _write_run_log_txt

        storage = MagicMock()
        _write_run_log_txt("run-1", "ffmpeg output here", storage)
        storage.upload_text.assert_called_once_with("runs/run-1/ffmpeg_log.txt", "ffmpeg output here")

    def test_swallows_storage_error(self):
        from src.renderer import _write_run_log_txt

        storage = MagicMock()
        storage.upload_text.side_effect = StorageError("R2 down")
        # Must not raise
        _write_run_log_txt("run-1", "output", storage)


# ── renderer: download_asset ──────────────────────────────────────────────────


class TestDownloadAsset:
    def test_writes_bytes_to_local_path(self, tmp_path):
        from src.renderer import download_asset

        storage = MagicMock()
        storage.get_bytes.return_value = b"video bytes"
        dest = str(tmp_path / "video" / "01.mp4")

        with patch("src.renderer._local_path", return_value=dest):
            download_asset(f"runs/{RUN_ID}/video/01.mp4", RUN_ID, storage)

        storage.get_bytes.assert_called_once_with(f"runs/{RUN_ID}/video/01.mp4")
        assert Path(dest).read_bytes() == b"video bytes"


# ── renderer: download_run_assets ────────────────────────────────────────────


class TestDownloadRunAssets:
    def test_downloads_each_manifest_file_key(self, manifest):
        from src.renderer import download_run_assets

        storage = MagicMock()
        storage.list_keys.return_value = []

        # Patch Path.exists so the post-download verification doesn't fail in tests
        # (download_asset is mocked and never writes real files to disk).
        with patch("src.renderer.download_asset") as mock_dl, \
             patch.object(Path, "exists", return_value=True):
            download_run_assets(RUN_ID, manifest, storage)

        mock_dl.assert_any_call(f"runs/{RUN_ID}/video/01.mp4", RUN_ID, storage)
        mock_dl.assert_any_call(f"runs/{RUN_ID}/images/02.jpeg", RUN_ID, storage)

    def test_raises_render_error_when_asset_missing_after_download(self, manifest):
        """RenderError is raised when an expected file is absent after download."""
        from src.renderer import download_run_assets

        storage = MagicMock()
        storage.list_keys.return_value = []

        # download_asset is a no-op — files are never written to disk.
        # Path.exists returns False (default) so the verification detects missing files.
        with patch("src.renderer.download_asset"), \
             patch.object(Path, "exists", return_value=False), \
             pytest.raises(RenderError, match="Asset files missing after download"):
            download_run_assets(RUN_ID, manifest, storage)

    def test_skips_entries_with_no_file_key(self):
        from src.renderer import download_run_assets

        storage = MagicMock()
        storage.list_keys.return_value = []
        manifest = AssetManifest(
            run_id=RUN_ID,
            entries=[
                ManifestEntry(
                    scene_id="01",
                    clip_type="hard_cut",
                    primary_query="q",
                    fallback_query="f",
                    ai_generate_prompt="p",
                    status="pending",
                    file_key=None,
                )
            ],
        )

        with patch("src.renderer.download_asset") as mock_dl:
            download_run_assets(RUN_ID, manifest, storage)

        mock_dl.assert_not_called()

    def test_downloads_voiceover_prefix_files(self):
        from src.renderer import download_run_assets

        storage = MagicMock()
        storage.list_keys.side_effect = lambda prefix: (
            [f"runs/{RUN_ID}/voiceover/vo.mp3"] if "voiceover" in prefix else []
        )
        manifest = AssetManifest(run_id=RUN_ID, entries=[])

        with patch("src.renderer.download_asset") as mock_dl:
            download_run_assets(RUN_ID, manifest, storage)

        mock_dl.assert_called_once_with(f"runs/{RUN_ID}/voiceover/vo.mp3", RUN_ID, storage)

    def test_queries_all_three_subfolders(self):
        from src.renderer import download_run_assets

        storage = MagicMock()
        storage.list_keys.return_value = []
        manifest = AssetManifest(run_id=RUN_ID, entries=[])

        with patch("src.renderer.download_asset"):
            download_run_assets(RUN_ID, manifest, storage)

        called_prefixes = [c.args[0] for c in storage.list_keys.call_args_list]
        assert f"runs/{RUN_ID}/voiceover/" in called_prefixes
        assert f"runs/{RUN_ID}/music/" in called_prefixes
        assert f"runs/{RUN_ID}/sfx/" in called_prefixes


# ── renderer: download_script ─────────────────────────────────────────────────


class TestDownloadScript:
    def test_downloads_script_and_makes_executable(self, tmp_path):
        from src.renderer import download_script

        storage = MagicMock()
        storage.get_bytes.return_value = b"#!/bin/bash\necho done"
        expected = tmp_path / "run-1" / "ffmpeg_script.sh"

        with patch("src.renderer.Path", return_value=expected):
            result = download_script("run-1", storage)

        storage.get_bytes.assert_called_once_with("runs/run-1/ffmpeg_script.sh")
        assert expected.read_bytes() == b"#!/bin/bash\necho done"
        assert result == expected


# ── renderer: execute_script ──────────────────────────────────────────────────


class TestExecuteScript:
    def test_calls_subprocess_run_with_correct_args(self):
        from src.renderer import execute_script

        mock_result = MagicMock(returncode=0, stdout="done\n", stderr="")
        with patch("src.renderer.subprocess.run", return_value=mock_result) as mock_run:
            result = execute_script(Path("/tmp/run-1/ffmpeg_script.sh"), 300)

        mock_run.assert_called_once_with(
            ["/tmp/run-1/ffmpeg_script.sh"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
        assert result.returncode == 0


# ── renderer: upload_output ───────────────────────────────────────────────────


class TestUploadOutput:
    def _make_mock_path(self, name: str, data: bytes, suffix: str) -> MagicMock:
        """Create a mock file path object for upload_output tests."""
        f = MagicMock()
        f.is_file.return_value = True
        f.name = name
        f.suffix = suffix
        f.read_bytes.return_value = data
        return f

    def test_uploads_final_mp4_and_returns_r2_key(self):
        from src.renderer import upload_output

        storage = MagicMock()
        mock_file = self._make_mock_path("final.mp4", b"video", ".mp4")

        with patch("src.renderer.Path") as MockPath:
            MockPath.return_value.iterdir.return_value = [mock_file]
            result = upload_output(RUN_ID, storage)

        assert result == f"runs/{RUN_ID}/output/final.mp4"
        storage.upload_bytes.assert_called_once_with(
            f"runs/{RUN_ID}/output/final.mp4", b"video", "video/mp4"
        )

    def test_skips_non_file_entries(self):
        from src.renderer import upload_output

        storage = MagicMock()
        subdir = MagicMock()
        subdir.is_file.return_value = False
        final_mp4 = self._make_mock_path("final.mp4", b"v", ".mp4")

        with patch("src.renderer.Path") as MockPath:
            MockPath.return_value.iterdir.return_value = [subdir, final_mp4]
            upload_output(RUN_ID, storage)

        assert storage.upload_bytes.call_count == 1

    def test_raises_render_error_when_no_final_mp4(self):
        from src.renderer import upload_output

        storage = MagicMock()
        other_file = self._make_mock_path("partial.txt", b"data", ".txt")

        with patch("src.renderer.Path") as MockPath:
            MockPath.return_value.iterdir.return_value = [other_file]
            with pytest.raises(RenderError, match="final.mp4"):
                upload_output(RUN_ID, storage)


# ── renderer: cleanup ─────────────────────────────────────────────────────────


class TestCleanup:
    def test_removes_tmp_dir(self):
        from src.renderer import cleanup

        with patch("src.renderer.shutil.rmtree") as mock_rmtree:
            cleanup("run-1")

        mock_rmtree.assert_called_once_with("/tmp/run-1", ignore_errors=True)


# ── renderer: copy_music_to_run ──────────────────────────────────────────────


class TestCopyMusicToRun:
    # Helper: no existing run music → library returns a file
    def _storage_no_run_music(self, library_keys: list) -> MagicMock:
        storage = MagicMock()
        storage.list_keys.side_effect = [[], library_keys]
        storage.get_bytes.return_value = b"audio bytes"
        return storage

    def test_copies_first_mp3_from_music_library(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music(["music-library/lofi-beat.mp3"])

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/lofi-beat.mp3")
        storage.upload_bytes.assert_called_once_with(
            f"runs/{RUN_ID}/music/lofi-beat.mp3", b"audio bytes", "audio/mpeg"
        )

    def test_copies_wav_file(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music(["music-library/track.wav"])

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/track.wav")
        storage.upload_bytes.assert_called_once_with(
            f"runs/{RUN_ID}/music/track.wav", b"audio bytes", "audio/mpeg"
        )

    def test_copies_m4a_file(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music(["music-library/track.m4a"])

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/track.m4a")

    def test_skips_non_audio_keys_and_picks_first_audio(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music([
            "music-library/README.txt",
            "music-library/lofi.mp3",
            "music-library/other.mp3",
        ])

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/lofi.mp3")

    def test_warns_and_returns_when_no_music_found(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music([])

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()

    def test_uploads_to_correct_run_music_key(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music(["music-library/ambient.mp3"])

        copy_music_to_run(RUN_ID, storage)

        dest_key = storage.upload_bytes.call_args[0][0]
        assert dest_key == f"runs/{RUN_ID}/music/ambient.mp3"

    def test_checks_run_music_prefix_before_library(self):
        from src.renderer import copy_music_to_run

        storage = self._storage_no_run_music([])

        copy_music_to_run(RUN_ID, storage)

        calls = [c.args[0] for c in storage.list_keys.call_args_list]
        assert calls[0] == f"runs/{RUN_ID}/music/"
        assert calls[1] == "music-library/"

    def test_skips_library_copy_when_run_already_has_music(self):
        """Operator-uploaded track must not be overwritten by the shared library."""
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        # First list_keys call → run already has a track
        storage.list_keys.return_value = [f"runs/{RUN_ID}/music/my-track.mp3"]

        copy_music_to_run(RUN_ID, storage)

        # Only one list_keys call (the run prefix check); library never queried
        storage.list_keys.assert_called_once_with(f"runs/{RUN_ID}/music/")
        storage.get_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()

    def test_skips_library_copy_when_run_has_wav(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = [f"runs/{RUN_ID}/music/custom.wav"]

        copy_music_to_run(RUN_ID, storage)

        storage.list_keys.assert_called_once()
        storage.get_bytes.assert_not_called()


# ── renderer: render_run ──────────────────────────────────────────────────────


class TestRenderRun:
    def _mock_execute(self, returncode: int = 0) -> MagicMock:
        return MagicMock(returncode=returncode, stdout="output\n", stderr="")

    def test_success_returns_complete_status(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets"),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch("src.renderer.execute_script", return_value=self._mock_execute(0)),
            patch("src.renderer._write_run_log_txt"),
            patch(
                "src.renderer.upload_output",
                return_value=f"runs/{RUN_ID}/output/final.mp4",
            ),
            patch("src.renderer.cleanup"),
        ):
            result = render_run(RUN_ID, manifest, storage, 300)

        assert result["status"] == "complete"
        assert result["output_key"] == f"runs/{RUN_ID}/output/final.mp4"
        assert result["exit_code"] == 0
        assert isinstance(result["duration_seconds"], float)

    def test_nonzero_exit_returns_failed_status(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets"),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch("src.renderer.execute_script", return_value=self._mock_execute(1)),
            patch("src.renderer._write_run_log_txt"),
            patch("src.renderer.upload_output"),
            patch("src.renderer.cleanup"),
        ):
            result = render_run(RUN_ID, manifest, storage, 300)

        assert result["status"] == "failed"
        assert result["exit_code"] == 1
        assert result["output_key"] == ""

    def test_timeout_returns_failed_with_exit_code_minus_one(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets"),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch(
                "src.renderer.execute_script",
                side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=300),
            ),
            patch("src.renderer._write_run_log_txt"),
            patch("src.renderer.upload_output"),
            patch("src.renderer.cleanup"),
        ):
            result = render_run(RUN_ID, manifest, storage, 300)

        assert result["status"] == "failed"
        assert result["exit_code"] == -1

    def test_upload_output_render_error_returns_failed(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets"),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch("src.renderer.execute_script", return_value=self._mock_execute(0)),
            patch("src.renderer._write_run_log_txt"),
            patch("src.renderer.upload_output", side_effect=RenderError("no final.mp4")),
            patch("src.renderer.cleanup"),
        ):
            result = render_run(RUN_ID, manifest, storage, 300)

        assert result["status"] == "failed"
        assert result["output_key"] == ""

    def test_cleanup_called_even_on_storage_error(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets", side_effect=StorageError("R2 down")),
            patch("src.renderer.cleanup") as mock_cleanup,
        ):
            with pytest.raises(StorageError):
                render_run(RUN_ID, manifest, storage, 300)

        mock_cleanup.assert_called_once_with(RUN_ID)

    def test_download_run_assets_called_in_render_run(self, manifest):
        """download_run_assets is called during render_run.

        copy_music_to_run was removed from the render pipeline — music is only
        used when the operator explicitly uploads a file.  This test confirms
        the overall call sequence is correct without the auto-copy step.
        """
        from src.renderer import render_run

        call_order = []
        storage = MagicMock()

        with (
            patch("src.renderer.download_run_assets", side_effect=lambda *_: call_order.append("download_assets")),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch("src.renderer.execute_script", return_value=self._mock_execute(0)),
            patch("src.renderer._write_run_log_txt"),
            patch("src.renderer.upload_output", return_value="runs/r/output/final.mp4"),
            patch("src.renderer.cleanup"),
        ):
            render_run(RUN_ID, manifest, storage, 300)

        assert call_order == ["download_assets"]

    def test_write_run_log_txt_called_with_combined_output(self, manifest):
        from src.renderer import render_run

        storage = MagicMock()
        with (
            patch("src.renderer.copy_music_to_run"),
            patch("src.renderer.download_run_assets"),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch(
                "src.renderer.execute_script",
                return_value=MagicMock(returncode=0, stdout="stdout\n", stderr="stderr\n"),
            ),
            patch("src.renderer._write_run_log_txt") as mock_log,
            patch("src.renderer.upload_output", return_value="runs/r/output/final.mp4"),
            patch("src.renderer.cleanup"),
        ):
            render_run(RUN_ID, manifest, storage, 300)

        mock_log.assert_called_once_with(RUN_ID, "stdout\nstderr\n", storage)


# ── Route integration tests ────────────────────────────────────────────────────

_SUCCESS_RESULT = {
    "status": "complete",
    "output_key": f"runs/{RUN_ID}/output/final.mp4",
    "duration_seconds": 12.34,
    "exit_code": 0,
}

_FAILED_RESULT = {
    "status": "failed",
    "output_key": "",
    "duration_seconds": 5.0,
    "exit_code": 1,
}

_MANIFEST_DATA = {"run_id": RUN_ID, "entries": []}
_STORYBOARD_DATA = {"summary": {"total_duration_s": 60, "total_scenes": 3, "rhythm": "fast"}}


class TestRenderRoute:
    def _mock_get_json(self, manifest_data=_MANIFEST_DATA, storyboard_data=None):
        """Return side_effect list for storage.get_json: manifest first, then storyboard."""
        sd = storyboard_data or _STORYBOARD_DATA

        def _get_json(key):
            if "asset_manifest" in key:
                return manifest_data
            if "storyboard" in key:
                return sd
            raise StorageError("unknown key")

        return _get_json

    def test_returns_202_accepted(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT),
        ):
            MockR2.return_value.get_json.side_effect = self._mock_get_json()
            resp = client.post(f"/runs/{RUN_ID}/render")

        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "running"
        assert body["poll_url"] == f"/runs/{RUN_ID}/render/status"

    def test_manifest_not_found_returns_404(self, client):
        with patch("src.routes.render.R2Client") as MockR2:
            MockR2.return_value.get_json.side_effect = StorageError("no such key")
            resp = client.post(f"/runs/missing-run/render")

        assert resp.status_code == 404
        assert "missing-run" in resp.json()["detail"]

    def test_background_task_updates_run_log_on_success(self, client):
        """TestClient runs background tasks synchronously before returning the response."""
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = self._mock_get_json()
            client.post(f"/runs/{RUN_ID}/render")

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "render",
            "complete",
            output_url=f"runs/{RUN_ID}/output/final.mp4",
            error=None,
        )

    def test_background_task_updates_run_log_on_failure(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_FAILED_RESULT),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = self._mock_get_json()
            client.post(f"/runs/{RUN_ID}/render")

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "render",
            "failed",
            output_url=None,
            error="FFmpeg exit code 1",
        )

    def test_storage_error_in_background_task_marks_failed(self, client):
        """StorageError during render is caught by background task — status endpoint shows failed."""
        import src.renderer as renderer_module

        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", side_effect=StorageError("R2 down")),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = self._mock_get_json()
            client.post(f"/runs/{RUN_ID}/render")

        assert renderer_module._RENDER_STATE.get(RUN_ID, {}).get("status") == "failed"

    def test_total_frames_derived_from_storyboard(self, client):
        """render_run is called with total_frames = total_duration_s * 25."""
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT) as mock_rr,
        ):
            mock_storage = MockR2.return_value
            # storyboard has 60s → 1500 frames
            mock_storage.get_json.side_effect = self._mock_get_json(
                storyboard_data={"summary": {"total_duration_s": 60}}
            )
            client.post(f"/runs/{RUN_ID}/render")

        _, kwargs = mock_rr.call_args
        assert kwargs.get("total_frames", mock_rr.call_args[0][4] if len(mock_rr.call_args[0]) > 4 else 0) == 1500

    def test_total_frames_defaults_to_zero_when_storyboard_missing(self, client):
        """Missing storyboard does not block render — total_frames falls back to 0."""
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT) as mock_rr,
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = lambda key: (
                _MANIFEST_DATA if "asset_manifest" in key else (_ for _ in ()).throw(StorageError("missing"))
            )
            client.post(f"/runs/{RUN_ID}/render")

        assert mock_rr.called


# ── render/status endpoint ─────────────────────────────────────────────────────


class TestRenderStatusRoute:
    def test_returns_running_while_task_in_progress(self, client):
        """Manually set state to running and confirm the endpoint reflects it."""
        import src.renderer as renderer_module

        renderer_module._RENDER_STATE[RUN_ID] = {
            "status": "running",
            "progress_pct": 0,
            "output_key": None,
            "error": None,
        }
        resp = client.get(f"/runs/{RUN_ID}/render/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "running"
        assert body["progress_pct"] == 0

    def test_returns_complete_after_successful_render(self, client):
        import src.renderer as renderer_module

        renderer_module._RENDER_STATE[RUN_ID] = {
            "status": "complete",
            "progress_pct": 100,
            "output_key": f"runs/{RUN_ID}/output/final.mp4",
            "error": None,
        }
        resp = client.get(f"/runs/{RUN_ID}/render/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert body["progress_pct"] == 100
        assert body["output_key"] == f"runs/{RUN_ID}/output/final.mp4"
        assert body["error"] is None

    def test_returns_failed_with_error_message(self, client):
        import src.renderer as renderer_module

        renderer_module._RENDER_STATE[RUN_ID] = {
            "status": "failed",
            "progress_pct": 0,
            "output_key": None,
            "error": "FFmpeg exit code 1",
        }
        resp = client.get(f"/runs/{RUN_ID}/render/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "failed"
        assert body["error"] == "FFmpeg exit code 1"

    def test_returns_404_when_no_render_started(self, client):
        import src.renderer as renderer_module

        renderer_module._RENDER_STATE.pop("nonexistent-run", None)
        resp = client.get("/runs/nonexistent-run/render/status")
        assert resp.status_code == 404

    def test_status_reflects_state_set_by_post(self, client):
        """Full round-trip: POST → 202 then GET /status → complete."""
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.side_effect = lambda key: (
                _MANIFEST_DATA if "asset_manifest" in key else _STORYBOARD_DATA
            )
            client.post(f"/runs/{RUN_ID}/render")

        resp = client.get(f"/runs/{RUN_ID}/render/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "complete"


# ── parse_ffmpeg_progress ──────────────────────────────────────────────────────


class TestParseFfmpegProgress:
    def test_returns_0_when_total_frames_zero(self):
        from src.renderer import parse_ffmpeg_progress

        assert parse_ffmpeg_progress("frame=  500", 0) == 0

    def test_returns_0_when_no_frame_line(self):
        from src.renderer import parse_ffmpeg_progress

        assert parse_ffmpeg_progress("no progress info here", 1000) == 0

    def test_parses_frame_count_correctly(self):
        from src.renderer import parse_ffmpeg_progress

        # 250 frames out of 1000 = 25%
        assert parse_ffmpeg_progress("frame=  250 fps=25 q=...", 1000) == 25

    def test_uses_last_frame_line(self):
        from src.renderer import parse_ffmpeg_progress

        stderr = "frame=  100 fps=25\nframe=  500 fps=25"
        assert parse_ffmpeg_progress(stderr, 1000) == 50

    def test_caps_at_99_never_returns_100(self):
        from src.renderer import parse_ffmpeg_progress

        # Completion is signalled by status=complete, not progress_pct=100
        assert parse_ffmpeg_progress("frame= 1000 fps=25", 1000) == 99

    def test_handles_no_spaces_around_equals(self):
        from src.renderer import parse_ffmpeg_progress

        assert parse_ffmpeg_progress("frame=750", 1000) == 75

    def test_returns_0_when_total_frames_negative(self):
        from src.renderer import parse_ffmpeg_progress

        assert parse_ffmpeg_progress("frame=500", -1) == 0
