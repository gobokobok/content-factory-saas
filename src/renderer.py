"""FFmpeg renderer — downloads assets from R2, executes ffmpeg_script.sh, uploads output."""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from src.exceptions import RenderError, StorageError
from src.ffmpeg_builder import _local_path
from src.models import AssetManifest
from src.storage import R2Client

logger = logging.getLogger(__name__)


def download_asset(key: str, run_id: str, storage: R2Client) -> None:
    """Download a single R2 key to the corresponding /tmp local path, creating parent dirs."""
    local = Path(_local_path(run_id, key))
    local.parent.mkdir(parents=True, exist_ok=True)
    data = storage.get_bytes(key)
    local.write_bytes(data)
    logger.debug("Downloaded %s → %s", key, local)


def download_run_assets(run_id: str, manifest: AssetManifest, storage: R2Client) -> None:
    """
    Download all acquired manifest assets plus voiceover, music, and sfx files.

    Per-scene assets come from manifest entry file_keys (video/, images/).
    Voiceover, music, and sfx files are enumerated by R2 prefix and downloaded.
    """
    for entry in manifest.entries:
        if entry.file_key:
            download_asset(entry.file_key, run_id, storage)

    for subfolder in ("voiceover", "music", "sfx"):
        prefix = f"runs/{run_id}/{subfolder}/"
        for key in storage.list_keys(prefix):
            download_asset(key, run_id, storage)


def download_script(run_id: str, storage: R2Client) -> Path:
    """
    Download ffmpeg_script.sh from R2 to /tmp/{run_id}/ffmpeg_script.sh.

    Makes the file executable and returns its local Path.
    """
    key = f"runs/{run_id}/ffmpeg_script.sh"
    data = storage.get_bytes(key)
    local = Path(f"/tmp/{run_id}/ffmpeg_script.sh")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    local.chmod(0o755)
    logger.info("Script ready: %s", local)
    return local


def execute_script(script_path: Path, timeout_seconds: int) -> subprocess.CompletedProcess:
    """Run ffmpeg_script.sh as a subprocess. Captures stdout and stderr as text."""
    logger.info("Running %s (timeout=%ds)", script_path, timeout_seconds)
    return subprocess.run(
        [str(script_path)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
    )


def upload_output(run_id: str, storage: R2Client) -> str:
    """
    Upload all files in /tmp/{run_id}/output/ to runs/{run_id}/output/ in R2.

    Returns the R2 key for final.mp4. Raises RenderError if final.mp4 is absent.
    """
    output_dir = Path(f"/tmp/{run_id}/output")
    output_key: Optional[str] = None
    for file_path in output_dir.iterdir():
        if not file_path.is_file():
            continue
        key = f"runs/{run_id}/output/{file_path.name}"
        content_type = "video/mp4" if file_path.suffix == ".mp4" else "application/octet-stream"
        storage.upload_bytes(key, file_path.read_bytes(), content_type)
        logger.info("Uploaded output: %s", key)
        if file_path.name == "final.mp4":
            output_key = key
    if output_key is None:
        raise RenderError("final.mp4 not found in output directory after FFmpeg execution")
    return output_key


def cleanup(run_id: str) -> None:
    """Delete /tmp/{run_id}/ and all its contents."""
    shutil.rmtree(f"/tmp/{run_id}", ignore_errors=True)
    logger.info("Cleaned up /tmp/%s", run_id)


def _write_run_log_txt(run_id: str, content: str, storage: R2Client) -> None:
    """Upload FFmpeg stdout+stderr to run_log.txt. Non-fatal — logs a warning on failure."""
    key = f"runs/{run_id}/run_log.txt"
    try:
        storage.upload_text(key, content)
    except StorageError:
        logger.warning("Failed to write run_log.txt for run %s", run_id)


def render_run(
    run_id: str,
    manifest: AssetManifest,
    storage: R2Client,
    timeout_seconds: int,
) -> dict:
    """
    Full render pipeline: download assets → execute ffmpeg_script.sh → upload output → cleanup.

    Returns a dict with keys: status, output_key, duration_seconds, exit_code.
    Always deletes /tmp/{run_id}/ in a finally block regardless of outcome.
    Raises StorageError on unexpected R2 failures (download or upload).
    """
    start = time.monotonic()
    exit_code = -1
    output_key: Optional[str] = None
    ffmpeg_output = ""

    try:
        download_run_assets(run_id, manifest, storage)
        script_path = download_script(run_id, storage)

        try:
            result = execute_script(script_path, timeout_seconds)
            exit_code = result.returncode
            ffmpeg_output = result.stdout + result.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = -1
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout or b"").decode("utf-8", errors="replace")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode("utf-8", errors="replace")
            ffmpeg_output = stdout + stderr
            logger.error("FFmpeg timed out after %ds for run %s", timeout_seconds, run_id)

        _write_run_log_txt(run_id, ffmpeg_output, storage)

        if exit_code == 0:
            try:
                output_key = upload_output(run_id, storage)
            except RenderError as exc:
                logger.error("Output upload failed for run %s: %s", run_id, exc)

    finally:
        cleanup(run_id)

    duration = round(time.monotonic() - start, 2)
    status = "complete" if exit_code == 0 and output_key else "failed"
    logger.info(
        "Render %s: run=%s duration=%.2fs exit_code=%d", status, run_id, duration, exit_code
    )

    return {
        "status": status,
        "output_key": output_key or "",
        "duration_seconds": duration,
        "exit_code": exit_code,
    }
