"""CapCut export (P13b-S2, D100) — a zip of a run's timeline and the media it references.

The zip is what the laptop script (tools/capcut/export_capcut.py) reads: `timeline.json`
at the root plus every referenced file under the relative path the timeline gives it.
It is streamed, one stored file at a time, so a run with minutes of footage is never
held in memory in one piece.
"""

import io
import zipfile
from collections.abc import AsyncIterator

from cf_platform.core.artifact_manager import ArtifactStorage
from cf_platform.workers.timeline import MissingAssetsError, Timeline

TIMELINE_ARCNAME = "timeline.json"


class _ChunkSink(io.RawIOBase):
    """A write-only, non-seekable sink that collects what zipfile writes until drained.

    zipfile falls back to data descriptors on a stream it cannot seek in, so the zip
    can be produced front to back and handed to the client as it goes.
    """

    def __init__(self) -> None:
        """Start empty at offset zero."""
        super().__init__()
        self._chunks: list[bytes] = []
        self._offset = 0

    def writable(self) -> bool:
        """The sink accepts writes."""
        return True

    def write(self, data: bytes) -> int:
        """Collect data and advance the offset zipfile reads through tell()."""
        self._chunks.append(bytes(data))
        self._offset += len(data)
        return len(data)

    def tell(self) -> int:
        """Return how many bytes have been written so far."""
        return self._offset

    def drain(self) -> bytes:
        """Return and clear everything written since the last drain."""
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


def prune_missing_media(timeline: Timeline, present_keys: set[str]) -> Timeline:
    """Drop optional media that is not in storage; raise when required media is not.

    Scene files and the voiceover are required — a missing one raises MissingAssetsError
    naming it. Music and SFX are optional, as they are in the FFmpeg render (the script
    skips a missing file): the timeline loses the reference, so it still lists exactly
    the files the zip holds.
    """
    absent = [s.asset_path for s in timeline.scenes if s.asset_key not in present_keys]
    if timeline.voiceover_key and timeline.voiceover_key not in present_keys:
        absent.append(timeline.voiceover_path or timeline.voiceover_key)
    if timeline.voiceover_key is None:
        absent.append("voiceover")
    if absent:
        raise MissingAssetsError(
            "These files are missing from storage, so the export cannot be built: " + ", ".join(absent)
        )

    scenes = []
    for scene in timeline.scenes:
        sfx_key = f"{timeline.run_id}/{scene.sfx_path}" if scene.sfx_path else None
        if scene.sfx_path and f"runs/{sfx_key}" not in present_keys:
            scene = scene.model_copy(update={"sfx_key": None, "sfx_path": None, "sfx_delay_ms": None})
        scenes.append(scene)
    update: dict = {"scenes": scenes}
    if timeline.music_key and timeline.music_key not in present_keys:
        update.update(music_key=None, music_path=None)
    return timeline.model_copy(update=update)


async def iter_export_zip(storage: ArtifactStorage, timeline: Timeline) -> AsyncIterator[bytes]:
    """Yield the export zip: timeline.json, then each referenced file, stored uncompressed.

    Media is already compressed, so entries are stored rather than deflated; the
    timeline itself is deflated. Each file is read from storage when its turn comes.
    """
    sink = _ChunkSink()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        zf.writestr(
            zipfile.ZipInfo(TIMELINE_ARCNAME, date_time=(1980, 1, 1, 0, 0, 0)),
            timeline.model_dump_json(indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        yield sink.drain()
        for path, key in zip(timeline.referenced_paths(), timeline.referenced_keys(), strict=True):
            data = await storage.get_bytes(key)
            zf.writestr(zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0)), data)
            del data
            yield sink.drain()
    yield sink.drain()
