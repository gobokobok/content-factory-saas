"""Return path for the CapCut render (P13b-S4): upload, source record, overwrite rules."""

import asyncio

from cf_platform.core.final_video import final_source_key, final_video_state, record_final_source
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.interfaces.dependencies import get_trace_event_repository
from src.main import app
from tests.cf_platform.p13_helpers import RUN_ID, p13_env

UPLOAD = f"/platform/studio/runs/{RUN_ID}/output/upload"
FINAL = f"runs/{RUN_ID}/output/final.mp4"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def _post(env, data: bytes = MP4, name: str = "cut.mp4", mime: str = "video/mp4", query: str = ""):
    """POST a file to the upload route."""
    return env.client.post(UPLOAD + query, files={"file": (name, data, mime)})


def test_accepts_an_mp4_and_stores_it_as_the_final_video():
    with p13_env() as env:
        r = _post(env)
        assert r.status_code == 200, r.text
        assert asyncio.run(env.storage.get_bytes(FINAL)) == MP4
    body = r.json()
    assert body["source"] == "capcut" and body["source_at"] and body["video_key"] == FINAL
    assert body["size_bytes"] == len(MP4)


def test_rejects_a_wrong_type_name_or_container():
    with p13_env() as env:
        assert _post(env, mime="video/quicktime", name="cut.mov").status_code == 422
        assert _post(env, name="cut.mov").status_code == 422          # right MIME, wrong extension
        assert _post(env, mime="application/octet-stream").status_code == 422
        assert _post(env, data=b"not a video at all").status_code == 422   # no ftyp box
        assert asyncio.run(env.storage.list_keys(FINAL)) == []


def test_rejects_a_file_over_the_size_limit():
    with p13_env() as env:
        env.settings.OUTPUT_UPLOAD_MAX_MB = 1
        r = _post(env, data=MP4 + b"\x00" * (1024 * 1024))
        assert r.status_code == 422 and "1 MB" in r.json()["detail"]
        assert asyncio.run(env.storage.list_keys(FINAL)) == []


def test_source_is_recorded_and_returned_by_the_video_endpoints():
    with p13_env() as env:
        _post(env)
        video = env.client.get(f"/platform/studio/runs/{RUN_ID}/video").json()
        status = env.client.get(f"/platform/studio/runs/{RUN_ID}/render/status").json()
        state = asyncio.run(final_video_state(env.storage, RUN_ID))
    assert video["source"] == "capcut" and video["source_at"]
    assert status["status"] == "complete" and status["source"] == "capcut" and status["source_at"]
    assert state["source"] == "capcut"


def test_a_video_with_no_record_counts_as_an_ffmpeg_render():
    with p13_env() as env:
        asyncio.run(env.storage.put_bytes(FINAL, MP4))
        video = env.client.get(f"/platform/studio/runs/{RUN_ID}/video").json()
    assert video["source"] == "ffmpeg" and video["source_at"] is None


def test_upload_over_an_ffmpeg_render_needs_confirmation():
    with p13_env() as env:
        asyncio.run(env.storage.put_bytes(FINAL, b"FFMPEG"))
        asyncio.run(record_final_source(env.storage, RUN_ID, "ffmpeg"))
        refused = _post(env)
        assert refused.status_code == 409 and "FFmpeg render" in refused.json()["detail"]
        assert asyncio.run(env.storage.get_bytes(FINAL)) == b"FFMPEG"
        ok = _post(env, query="?confirm_overwrite=true")
        assert ok.status_code == 200
        assert asyncio.run(env.storage.get_bytes(FINAL)) == MP4


def test_upload_over_an_earlier_capcut_upload_needs_no_confirmation():
    with p13_env() as env:
        assert _post(env).status_code == 200
        assert _post(env, data=MP4 + b"v2").status_code == 200


def test_upload_while_a_render_is_marked_running_needs_confirmation():
    with p13_env() as env:
        asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/render/current_job.json", {"job_id": "j", "status": "running"}))
        refused = _post(env)
        assert refused.status_code == 409 and "running" in refused.json()["detail"]
        assert _post(env, query="?confirm_overwrite=true").status_code == 200
        status = env.client.get(f"/platform/studio/runs/{RUN_ID}/render/status").json()
    assert status["status"] == "complete" and status["source"] == "capcut"


def test_ffmpeg_render_over_a_capcut_video_needs_confirmation():
    with p13_env(with_manifest=True) as env:
        _post(env)
        refused = env.client.post("/platform/workers/render", json={"run_id": RUN_ID})
        assert refused.status_code == 409 and "CapCut" in refused.json()["detail"]
        assert asyncio.run(env.storage.get_bytes(FINAL)) == MP4


def test_ffmpeg_render_with_confirmation_is_accepted_over_a_capcut_video():
    from unittest.mock import patch

    with p13_env(with_manifest=True) as env:
        _post(env)
        with patch("cf_platform.interfaces.routes.workers._run_render_background") as bg:
            ok = env.client.post("/platform/workers/render", json={"run_id": RUN_ID, "confirm_overwrite": True})
        assert ok.status_code == 202
        assert bg.called


def test_ffmpeg_render_is_not_blocked_when_the_video_is_ffmpeg_or_absent():
    from unittest.mock import patch

    with p13_env(with_manifest=True) as env:
        with patch("cf_platform.interfaces.routes.workers._run_render_background"):
            assert env.client.post("/platform/workers/render", json={"run_id": RUN_ID}).status_code == 202
            asyncio.run(env.storage.put_bytes(FINAL, b"F"))
            asyncio.run(record_final_source(env.storage, RUN_ID, "ffmpeg"))
            assert env.client.post("/platform/workers/render", json={"run_id": RUN_ID}).status_code == 202


def test_a_finished_ffmpeg_render_records_its_source():
    from cf_platform.interfaces.routes.workers import _run_render_background
    from cf_platform.workers.render_worker import RenderArtifact

    async def run() -> dict:
        """Run the background task with a worker that succeeds, then read the marker."""
        from datetime import datetime

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.schemas import StageState, WorkerOutput

        storage = InMemoryArtifactStorage()

        async def worker(_state):
            """A render that succeeds."""
            return WorkerOutput(artifact=RenderArtifact(
                render_script_key="s", video_key=FINAL, scene_count=3, duration_s=6.0, generated_at=datetime.now()))

        await _run_render_background(RUN_ID, "j1", StageState(run_id=RUN_ID, user_id="u", inputs={}), worker, storage, None)
        return {
            "job": await storage.get_json(f"runs/{RUN_ID}/render/current_job.json"),
            "source": await storage.get_json(final_source_key(RUN_ID)),
        }

    out = asyncio.run(run())
    assert out["job"]["status"] == "complete" and out["job"]["source"] == "ffmpeg"
    assert out["source"]["source"] == "ffmpeg"


def test_a_stale_final_video_from_a_killed_render_is_still_not_a_finished_job():
    with p13_env() as env:
        asyncio.run(env.storage.put_bytes(FINAL, b"STALE"))
        asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/render/current_job.json", {"job_id": "j", "status": "running"}))
        status = env.client.get(f"/platform/studio/runs/{RUN_ID}/render/status").json()
    assert status == {"status": "running"}


def test_the_upload_is_traced_and_metadata_does_not_depend_on_the_render():
    with p13_env() as env:
        trace = InMemoryTraceEventRepository()
        app.dependency_overrides[get_trace_event_repository] = lambda: trace
        _post(env)
    events = [e for e in trace._events if e.op == "capcut_video_upload"]
    assert events and events[0].meta["size_bytes"] == len(MP4)
    # Metadata reads the script only (see the metadata worker route): nothing about the
    # render path gates it, so an uploaded video reaches the Metadata stage as a render does.
    import inspect

    from cf_platform.interfaces.routes import workers

    source = inspect.getsource(workers.metadata_worker_endpoint)
    assert "final.mp4" not in source and "render" not in source.lower().replace("youtube", "")
