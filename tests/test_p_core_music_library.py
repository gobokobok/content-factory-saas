"""BG music library: the platform's tracks and the tenant's own uploads — no sound effects (P-CORE UX pass)."""

import asyncio

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.library import RunRef, list_shared_music


def test_music_library_lists_platform_and_uploaded_tracks_only():
    async def go():
        storage = InMemoryArtifactStorage()
        await storage.put_bytes("music-library/calm.mp3", b"x", "audio/mpeg")
        await storage.put_bytes("sfx-library/whoosh.mp3", b"x", "audio/mpeg")
        await storage.put_bytes("runs/r1/music/track.mp3", b"x", "audio/mpeg")
        await storage.put_bytes("runs/other/music/track.mp3", b"x", "audio/mpeg")
        ref = RunRef("r1", "My video", "p1", "Project", "2026-10-14T10:00:00")
        return await list_shared_music(storage, [ref])

    items = asyncio.run(go())
    assert {i["key"] for i in items} == {"music-library/calm.mp3", "runs/r1/music/track.mp3"}
    assert {i["facet"] for i in items} == {"platform", "uploaded"}
    uploaded = next(i for i in items if i["facet"] == "uploaded")
    assert uploaded["run_id"] == "r1" and uploaded["run_name"] == "My video"
