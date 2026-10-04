"""CapCut zip export route (P13b-S2)."""

import asyncio
import io
import json
import zipfile

from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.interfaces.dependencies import get_trace_event_repository
from src.main import app
from tests.cf_platform.p13_helpers import (
    RUN_ID,
    make_manifest,
    make_storyboard,
    make_words,
    p13_env,
    seed_manifest,
)

URL = f"/platform/studio/runs/{RUN_ID}/export/capcut"


def _seed_files(env, with_music: bool = True, sfx: tuple[str, ...] = ()) -> None:
    """Put bytes behind every manifest file and the voiceover (and optional music / sfx)."""
    for entry in env.client.get(f"/platform/studio/runs/{RUN_ID}/manifest").json()["manifest"]["entries"]:
        asyncio.run(env.storage.put_bytes(entry["file_key"], f"IMG{entry['scene_id']}".encode()))
    asyncio.run(env.storage.put_bytes(f"runs/{RUN_ID}/voiceover/vo.mp3", b"VOICE"))
    if with_music:
        asyncio.run(env.storage.put_bytes(f"runs/{RUN_ID}/music/bed.mp3", b"MUSIC"))
    for key in sfx:
        asyncio.run(env.storage.put_bytes(f"runs/{RUN_ID}/sfx/{key}.mp3", b"SFX"))


def _zip(response) -> zipfile.ZipFile:
    """Open a response body as a zip."""
    return zipfile.ZipFile(io.BytesIO(response.content))


def test_zip_holds_timeline_and_exactly_the_files_it_references():
    with p13_env(with_manifest=True, **{"1": {"sfx": "whoosh"}}) as env:
        _seed_files(env, sfx=("whoosh",))
        r = env.client.get(URL)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "capcut_run1.zip" in r.headers["content-disposition"]
    z = _zip(r)
    assert z.testzip() is None
    timeline = json.loads(z.read("timeline.json"))
    referenced = {s["asset_path"] for s in timeline["scenes"]}
    referenced |= {timeline["voiceover_path"], timeline["music_path"], "sfx/whoosh.mp3"}
    assert set(z.namelist()) == referenced | {"timeline.json"}
    assert z.read("images/2.jpg") == b"IMG2"
    assert z.read(timeline["voiceover_path"]) == b"VOICE"
    assert timeline["scenes"][0]["sfx_path"] == "sfx/whoosh.mp3"


def test_optional_media_missing_from_storage_is_dropped_from_the_timeline():
    with p13_env(with_manifest=True, **{"1": {"sfx": "whoosh"}}) as env:
        _seed_files(env, with_music=False)
        r = env.client.get(URL + "?music_enabled=false")
    assert r.status_code == 200, r.text
    z = _zip(r)
    timeline = json.loads(z.read("timeline.json"))
    assert timeline["music_path"] is None
    assert timeline["scenes"][0]["sfx_path"] is None
    assert set(z.namelist()) == {"timeline.json", "images/1.jpg", "images/2.jpg", "images/3.jpg", "voiceover/vo.mp3"}


def test_409_while_a_scene_has_no_file():
    with p13_env(with_manifest=False, **{"2": {"asset_strategy": "upload"}}) as env:
        mf = make_manifest(make_storyboard(env.words, **{"2": {"asset_strategy": "upload"}}))
        mf.entries[1].file_key = None
        mf.entries[1].status = "awaiting_upload"
        asyncio.run(seed_manifest(env.storage, mf))
        r = env.client.get(URL)
    assert r.status_code == 409
    assert "Scene(s) 2" in r.json()["detail"]


def test_409_when_a_scene_file_is_missing_from_storage():
    with p13_env(with_manifest=True) as env:
        _seed_files(env)
        del env.storage._bytes[f"runs/{RUN_ID}/images/2.jpg"]
        r = env.client.get(URL)
    assert r.status_code == 409
    assert "images/2.jpg" in r.json()["detail"]


def test_409_when_the_run_has_no_voice_alignment():
    with p13_env(with_manifest=True, with_voice=False) as env:
        _seed_files(env)
        r = env.client.get(URL)
    assert r.status_code == 409
    assert "voiceover" in r.json()["detail"].lower()


def test_export_stores_the_timeline_and_records_a_trace_event():
    with p13_env(with_manifest=True) as env:
        _seed_files(env)
        trace = InMemoryTraceEventRepository()
        app.dependency_overrides[get_trace_event_repository] = lambda: trace
        r = env.client.get(URL)
        assert r.status_code == 200
        assert env.versions("render", "timeline") == 1
        env.client.get(URL)
        assert env.versions("render", "timeline") == 2
    events = [e for e in trace._events if e.op == "capcut_export"]
    assert events and events[0].worker == "studio_export" and events[0].meta["scenes"] == 3


def test_zip_is_produced_in_chunks_not_one_piece():
    from cf_platform.core.artifact_manager import InMemoryArtifactStorage
    from cf_platform.workers.capcut_export import iter_export_zip
    from cf_platform.workers.timeline import TimelineSettings, build_timeline

    sb = make_storyboard(make_words())
    storage = InMemoryArtifactStorage()
    mf = make_manifest(sb)
    for e in mf.entries:
        asyncio.run(storage.put_bytes(e.file_key, b"x" * 4096))
    asyncio.run(storage.put_bytes(f"runs/{RUN_ID}/voiceover/vo.mp3", b"v" * 4096))
    tl = build_timeline(sb, mf, None, TimelineSettings(voiceover_key=f"runs/{RUN_ID}/voiceover/vo.mp3"))

    async def collect() -> list[bytes]:
        """Gather the chunks the generator yields."""
        return [c async for c in iter_export_zip(storage, tl)]

    chunks = asyncio.run(collect())
    assert len([c for c in chunks if c]) >= 5  # timeline + 3 scenes + voiceover + trailer
    assert max(len(c) for c in chunks) < sum(len(c) for c in chunks)
    assert zipfile.ZipFile(io.BytesIO(b"".join(chunks))).testzip() is None
