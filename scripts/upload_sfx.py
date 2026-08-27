"""Operator utility — uploads a local SFX file to sfx-library/{key}.mp3 in R2.

Use this to replace one of the curated library's automated Freesound picks (or
add audio for a brand-new key you've added to cf_platform/core/sfx_library.py)
with a sound you've sourced and downloaded yourself.

Transcodes the input to MP3 via a local ffmpeg subprocess so any format
ffmpeg can read (wav, ogg, flac, m4a, ...) works — not just files that are
already .mp3. Falls back to uploading the raw bytes, with a warning, if
ffmpeg isn't available locally.

Usage:
    python scripts/upload_sfx.py cash_register ~/Downloads/my-cha-ching.wav
    python scripts/upload_sfx.py new_custom_key ~/Downloads/sound.mp3
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from cf_platform.core.sfx_library import SFX_LIBRARY  # noqa: E402
from src.config import Settings  # noqa: E402
from src.exceptions import StorageError  # noqa: E402
from src.storage import R2Client  # noqa: E402


def _transcode_to_mp3(local_path: Path) -> bytes:
    """Transcode any ffmpeg-readable audio file to MP3 bytes.

    Falls back to the raw file bytes (with a warning) if ffmpeg isn't
    installed locally or the transcode fails for any reason — the render
    pipeline is somewhat tolerant of format/extension mismatches since ffmpeg
    sniffs actual content, but a real transcode is safer and more predictable.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(local_path), "-f", "mp3", "-b:a", "192k", "pipe:1"],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        stderr_snippet = result.stderr[-300:].decode("utf-8", errors="replace")
        print(f"WARNING: ffmpeg transcode failed ({result.returncode}): {stderr_snippet}", file=sys.stderr)
    except FileNotFoundError:
        print(
            "WARNING: ffmpeg not found locally — uploading the file as-is. "
            "Make sure it's already a valid MP3.",
            file=sys.stderr,
        )
    except subprocess.TimeoutExpired:
        print("WARNING: ffmpeg transcode timed out after 60s — uploading the file as-is.", file=sys.stderr)
    return local_path.read_bytes()


def main() -> None:
    """Parse args and upload one local audio file to sfx-library/{key}.mp3 in R2."""
    parser = argparse.ArgumentParser(description="Upload a local SFX file to the curated sfx-library/ (D076)")
    parser.add_argument("key", help="Library key, e.g. cash_register — matches cf_platform/core/sfx_library.py")
    parser.add_argument("file", help="Path to a local audio file (any format ffmpeg can read)")
    args = parser.parse_args()

    local_path = Path(args.file).expanduser()
    if not local_path.is_file():
        print(f"ERROR: file not found: {local_path}", file=sys.stderr)
        sys.exit(1)

    known_keys = {e.key for e in SFX_LIBRARY}
    if args.key not in known_keys:
        print(f"NOTE: {args.key!r} is not yet in cf_platform/core/sfx_library.py's manifest.")
        print("      The file will still upload fine, but the Studio dropdown and the AI's")
        print("      storyboard-generation prompt won't offer it until you add an entry there")
        print("      (key, display_name, prompt_hint, search_query — search_query is unused")
        print("      for a manually-uploaded key, but the field is required).")
        print()

    settings = Settings()
    r2 = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    print(f"Transcoding {local_path} ...")
    audio_bytes = _transcode_to_mp3(local_path)

    dest_key = f"sfx-library/{args.key}.mp3"
    try:
        r2.upload_bytes(dest_key, audio_bytes, "audio/mpeg")
    except StorageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Uploaded {local_path} -> {dest_key} ({len(audio_bytes)} bytes)")
    print("Live immediately — no deploy needed. Refresh Studio to see it in the SFX dropdown.")


if __name__ == "__main__":
    main()
