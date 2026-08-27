"""One-time operator utility — seeds the curated sfx-library/ R2 prefix from Freesound.

For each entry in cf_platform.core.sfx_library.SFX_LIBRARY, searches Freesound
(CC0-licensed results only, D076), picks the best candidate by a simple
heuristic, downloads its preview audio, and uploads it to
sfx-library/{key}.mp3 in R2 — mirroring the existing music-library/ pattern.

Run manually, offline, before the SFX picker is usable in Studio. Not part of
any worker or pipeline stage. Safe to re-run any time; accepts --key to
re-seed a single entry after a listening pass turns up a bad automated pick.

Automated selection (highest avg_rating, tie-broken by num_downloads, among
candidates in a sane 0.5-6.0s duration range) is a heuristic, not a quality
guarantee — always do a quick listening pass after seeding.

Usage:
    python scripts/seed_sfx_library.py
    python scripts/seed_sfx_library.py --key cash_register
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from cf_platform.core.sfx_library import SFX_LIBRARY, SfxLibraryEntry  # noqa: E402
from src.config import Settings  # noqa: E402
from src.exceptions import StorageError  # noqa: E402
from src.freesound_client import FreesoundClient, FreesoundResult  # noqa: E402
from src.storage import R2Client  # noqa: E402

_MIN_DURATION_S = 0.5
_MAX_DURATION_S = 6.0


def _pick_best(candidates: list[FreesoundResult]) -> FreesoundResult | None:
    """Pick the best duration-eligible candidate by (avg_rating, num_downloads).

    Heuristic only — not a quality guarantee. Returns None if nothing in
    candidates falls within the sane duration range for a short SFX clip.
    """
    eligible = [c for c in candidates if _MIN_DURATION_S <= c.duration <= _MAX_DURATION_S]
    if not eligible:
        return None
    eligible.sort(key=lambda c: (c.avg_rating or 0.0, c.num_downloads or 0), reverse=True)
    return eligible[0]


async def _seed_entry(client: FreesoundClient, r2: R2Client, entry: SfxLibraryEntry) -> None:
    """Search, pick, download, and upload the audio file for one manifest entry."""
    print(f"Searching Freesound for '{entry.key}' — query: {entry.search_query!r}")
    candidates = await client.search(entry.search_query)
    best = _pick_best(candidates)
    if best is None:
        print(f"  WARNING: no eligible ({_MIN_DURATION_S}-{_MAX_DURATION_S}s, CC0) result — skipped.")
        return

    audio_bytes = await client.download_preview(best)
    dest_key = f"sfx-library/{entry.key}.mp3"
    r2.upload_bytes(dest_key, audio_bytes, "audio/mpeg")
    print(
        f"  chosen: {best.name!r} (rating={best.avg_rating}, downloads={best.num_downloads}, "
        f"duration={best.duration:.1f}s) -> {dest_key}"
    )
    if best.page_url:
        print(f"  spot-check by ear: {best.page_url}")


async def _seed_all(api_key: str, r2: R2Client, only_key: str | None) -> None:
    """Seed every manifest entry, or just only_key if given."""
    client = FreesoundClient(api_key)
    entries = [e for e in SFX_LIBRARY if only_key is None or e.key == only_key]
    if only_key and not entries:
        print(f"ERROR: no manifest entry with key {only_key!r}", file=sys.stderr)
        sys.exit(1)

    for entry in entries:
        await _seed_entry(client, r2, entry)
        print()


def main() -> None:
    """Parse args and seed the curated sfx-library/ R2 prefix from Freesound."""
    parser = argparse.ArgumentParser(description="Seed the curated SFX library from Freesound (D076)")
    parser.add_argument(
        "--key",
        metavar="KEY",
        help="Only (re-)seed this one manifest key, e.g. cash_register",
    )
    args = parser.parse_args()

    settings = Settings()
    if not settings.FREESOUND_API_KEY:
        print("ERROR: FREESOUND_API_KEY is not set in the environment.", file=sys.stderr)
        sys.exit(1)

    r2 = R2Client(
        account_id=settings.R2_ACCOUNT_ID,
        access_key_id=settings.R2_ACCESS_KEY_ID,
        secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        bucket_name=settings.R2_BUCKET_NAME,
    )

    print(f"Seeding sfx-library/ (bucket: {settings.R2_BUCKET_NAME}) ...")
    print()

    try:
        asyncio.run(_seed_all(settings.FREESOUND_API_KEY, r2, args.key))
    except StorageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
