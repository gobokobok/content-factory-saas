"""Tests for src/renderer.py and the POST /runs/{run_id}/render route."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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
        storage.upload_text.assert_called_once_with("runs/run-1/run_log.txt", "ffmpeg output here")

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

        with patch("src.renderer.download_asset") as mock_dl:
            download_run_assets(RUN_ID, manifest, storage)

        mock_dl.assert_any_call(f"runs/{RUN_ID}/video/01.mp4", RUN_ID, storage)
        mock_dl.assert_any_call(f"runs/{RUN_ID}/images/02.jpeg", RUN_ID, storage)

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
    def test_copies_first_mp3_from_music_library(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = ["music-library/lofi-beat.mp3"]
        storage.get_bytes.return_value = b"audio bytes"

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/lofi-beat.mp3")
        storage.upload_bytes.assert_called_once_with(
            f"runs/{RUN_ID}/music/lofi-beat.mp3", b"audio bytes", "audio/mpeg"
        )

    def test_copies_wav_file(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = ["music-library/track.wav"]
        storage.get_bytes.return_value = b"wav bytes"

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/track.wav")
        storage.upload_bytes.assert_called_once_with(
            f"runs/{RUN_ID}/music/track.wav", b"wav bytes", "audio/mpeg"
        )

    def test_copies_m4a_file(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = ["music-library/track.m4a"]
        storage.get_bytes.return_value = b"m4a bytes"

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/track.m4a")

    def test_skips_non_audio_keys_and_picks_first_audio(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = [
            "music-library/README.txt",
            "music-library/lofi.mp3",
            "music-library/other.mp3",
        ]
        storage.get_bytes.return_value = b"bytes"

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_called_once_with("music-library/lofi.mp3")

    def test_warns_and_returns_when_no_music_found(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = []

        copy_music_to_run(RUN_ID, storage)

        storage.get_bytes.assert_not_called()
        storage.upload_bytes.assert_not_called()

    def test_uploads_to_correct_run_music_key(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = ["music-library/ambient.mp3"]
        storage.get_bytes.return_value = b"data"

        copy_music_to_run(RUN_ID, storage)

        dest_key = storage.upload_bytes.call_args[0][0]
        assert dest_key == f"runs/{RUN_ID}/music/ambient.mp3"

    def test_lists_music_library_prefix(self):
        from src.renderer import copy_music_to_run

        storage = MagicMock()
        storage.list_keys.return_value = []

        copy_music_to_run(RUN_ID, storage)

        storage.list_keys.assert_called_once_with("music-library/")


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

    def test_copy_music_called_before_download_run_assets(self, manifest):
        """copy_music_to_run must run before download_run_assets so music is in R2 when assets download."""
        from src.renderer import render_run

        call_order = []
        storage = MagicMock()

        with (
            patch("src.renderer.copy_music_to_run", side_effect=lambda *_: call_order.append("copy_music")),
            patch("src.renderer.download_run_assets", side_effect=lambda *_: call_order.append("download_assets")),
            patch("src.renderer.download_script", return_value=Path("/tmp/r/s.sh")),
            patch("src.renderer.execute_script", return_value=self._mock_execute(0)),
            patch("src.renderer._write_run_log_txt"),
            patch("src.renderer.upload_output", return_value="runs/r/output/final.mp4"),
            patch("src.renderer.cleanup"),
        ):
            render_run(RUN_ID, manifest, storage, 300)

        assert call_order == ["copy_music", "download_assets"]

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


class TestRenderRoute:
    def test_success_returns_200_with_complete_body(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT),
        ):
            MockR2.return_value.get_json.return_value = _MANIFEST_DATA
            resp = client.post(f"/runs/{RUN_ID}/render")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "complete"
        assert body["output_key"] == f"runs/{RUN_ID}/output/final.mp4"
        assert body["exit_code"] == 0
        assert body["duration_seconds"] == 12.34

    def test_failed_render_returns_200_with_failed_status(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_FAILED_RESULT),
        ):
            MockR2.return_value.get_json.return_value = _MANIFEST_DATA
            resp = client.post(f"/runs/{RUN_ID}/render")

        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        assert resp.json()["exit_code"] == 1

    def test_manifest_not_found_returns_404(self, client):
        with patch("src.routes.render.R2Client") as MockR2:
            MockR2.return_value.get_json.side_effect = StorageError("no such key")
            resp = client.post(f"/runs/missing-run/render")

        assert resp.status_code == 404
        assert "missing-run" in resp.json()["detail"]

    def test_storage_error_in_render_returns_500(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", side_effect=StorageError("R2 down")),
        ):
            MockR2.return_value.get_json.return_value = _MANIFEST_DATA
            resp = client.post(f"/runs/{RUN_ID}/render")

        assert resp.status_code == 500

    def test_run_log_updated_complete_on_success(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_SUCCESS_RESULT),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.return_value = _MANIFEST_DATA
            client.post(f"/runs/{RUN_ID}/render")

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "render",
            "complete",
            output_url=f"runs/{RUN_ID}/output/final.mp4",
            error=None,
        )

    def test_run_log_updated_failed_with_error_message(self, client):
        with (
            patch("src.routes.render.R2Client") as MockR2,
            patch("src.routes.render.render_run", return_value=_FAILED_RESULT),
        ):
            mock_storage = MockR2.return_value
            mock_storage.get_json.return_value = _MANIFEST_DATA
            client.post(f"/runs/{RUN_ID}/render")

        mock_storage.update_run_log.assert_called_once_with(
            RUN_ID,
            "render",
            "failed",
            output_url=None,
            error="FFmpeg exit code 1",
        )
