"""One-time operator utility — initialises the required R2 directory structure for a new run.

Creates a visible music-library/ prefix and, optionally, a run's voiceover/ folder so
both are visible in the R2 console and ready for manual file uploads.

Usage:
    python scripts/init_r2_structure.py
    python scripts/init_r2_structure.py --run-id 2026-05-22_my-slug
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Settings
from src.exceptions import StorageError
from src.storage import R2Client

_KEEP_CONTENT = b""


def create_prefix(client: R2Client, key: str) -> None:
    """Upload a zero-byte .keep file at key to make the prefix visible in the R2 console."""
    client.upload_bytes(key, _KEEP_CONTENT, "application/octet-stream")
    print(f"  created: {key}")


def init_music_library(client: R2Client) -> None:
    """Ensure music-library/ prefix exists in R2."""
    create_prefix(client, "music-library/.keep")


def init_voiceover_folder(client: R2Client, run_id: str) -> None:
    """Ensure runs/{run_id}/voiceover/ prefix exists in R2."""
    create_prefix(client, f"runs/{run_id}/voiceover/.keep")


def print_upload_instructions(run_id: Optional[str], bucket: str) -> None:
    """Print the R2 paths where the operator should upload files."""
    print()
    print("Upload your files to the following R2 paths:")
    print(f"  Bucket: {bucket}")
    print()
    print("  music-library/")
    print("    ← upload background music .mp3 files here")
    print("    (shared across all runs — upload once, reuse forever)")
    if run_id:
        print()
        print(f"  runs/{run_id}/voiceover/")
        print("    ← upload your voiceover .mp3 here")
        print("    (one file per run — must be present before rendering)")
    print()


def main() -> None:
    """Parse args, initialise R2 structure, and print upload instructions."""
    parser = argparse.ArgumentParser(
        description="Initialise R2 directory structure for Content Factory"
    )
    parser.add_argument(
        "--run-id",
        metavar="RUN_ID",
        help="Optional run ID (e.g. 2026-05-22_my-slug). Creates the voiceover/ folder for this run.",
    )
    args = parser.parse_args()

    settings = Settings()
    client = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    print(f"Initialising R2 structure (bucket: {settings.R2_BUCKET_NAME}) ...")
    print()

    try:
        init_music_library(client)
        if args.run_id:
            init_voiceover_folder(client, args.run_id)
    except StorageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print()
    print("Done.")
    print_upload_instructions(args.run_id, settings.R2_BUCKET_NAME)


if __name__ == "__main__":
    main()
