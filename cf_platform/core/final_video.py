"""Which path produced a run's final video, and when (P13b-S4).

A run's final video is always `runs/{run_id}/output/final.mp4` — the key Studio, the
video endpoints and the Metadata stage read — whether the FFmpeg render on Railway
wrote it or the operator uploaded the video they rendered in CapCut (D100). A small
record beside it names the path and the time, so Studio can show it and neither path
overwrites the other silently.
"""

from datetime import UTC, datetime
from typing import Literal

from cf_platform.core.artifact_manager import ArtifactStorage

FinalSource = Literal["ffmpeg", "capcut"]


def final_video_key(run_id: str) -> str:
    """Return the R2 key of the run's final video."""
    return f"runs/{run_id}/output/final.mp4"


def final_source_key(run_id: str) -> str:
    """Return the R2 key of the record naming which path produced the final video."""
    return f"runs/{run_id}/output/final_source.json"


async def record_final_source(
    storage: ArtifactStorage, run_id: str, source: FinalSource, **extra: object
) -> dict:
    """Write the final-video source record (path + UTC time) and return it."""
    record = {"source": source, "at": datetime.now(UTC).isoformat(), **extra}
    await storage.put_json(final_source_key(run_id), record)
    return record


async def read_final_source(storage: ArtifactStorage, run_id: str) -> dict | None:
    """Return the run's final-video record, or None when the video's source is unknown.

    A final.mp4 rendered before this record existed has no record; callers treat a
    final.mp4 without one as an FFmpeg render.
    """
    try:
        record = await storage.get_json(final_source_key(run_id))
    except Exception:
        return None
    return record if isinstance(record, dict) and record.get("source") in ("ffmpeg", "capcut") else None


async def final_video_state(storage: ArtifactStorage, run_id: str) -> dict:
    """Return {"exists", "source", "at"} for the run's final video.

    `source` is "capcut" or "ffmpeg" (an unrecorded final.mp4 counts as ffmpeg), and
    None when there is no final video at all.
    """
    key = final_video_key(run_id)
    exists = key in await storage.list_keys(key)
    if not exists:
        return {"exists": False, "source": None, "at": None}
    record = await read_final_source(storage, run_id)
    return {
        "exists": True,
        "source": record["source"] if record else "ffmpeg",
        "at": record.get("at") if record else None,
    }
