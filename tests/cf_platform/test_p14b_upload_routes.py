"""Uploaded voiceover (P14b-S1..S4): creation mode, upload, transcript, guards, end to end."""

import asyncio
import io
import json
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.config import get_platform_settings
from cf_platform.core.run_manager import InMemoryRunRepository, create_run
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.interfaces.dependencies import (
    PLATFORM_USER_ID,
    get_artifact_storage,
    get_run_repository,
    get_trace_event_repository,
)
from cf_platform.interfaces.routes._helpers import prepare_run_timeline
from cf_platform.workers.render_worker import build_render_script_from_timeline
from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact
from cf_platform.workers.voice_production import DeepgramTranscript, VoiceAlignmentArtifact
from src.config import Settings, get_settings
from src.main import app
from src.models import AssetManifest, Storyboard
from tests.cf_platform.p12_helpers import p12_env
from tests.cf_platform.p13_helpers import (
    VALID_ENV,
    make_manifest,
    make_storyboard,
    make_words,
    seed_manifest,
)

RUN = "run1"
MP3 = b"ID3\x04\x00\x00" + b"\x00" * 200
DG = "cf_platform.workers.voice_upload._deepgram_transcribe"


def transcript(words=None, duration=6.0) -> DeepgramTranscript:
    """A mocked Deepgram answer: 12 back-to-back words by default."""
    return DeepgramTranscript(words=words if words is not None else make_words(), duration_s=duration)


@dataclass
class Env:
    """TestClient with in-memory storage, runs and trace events; one uploaded run `run1`."""

    client: TestClient
    storage: InMemoryArtifactStorage
    runs: InMemoryRunRepository
    trace: InMemoryTraceEventRepository
    settings: SimpleNamespace

    def upload(self, data=MP3, name="vo.mp3", mime="audio/mpeg", query="", dg=None):
        """POST a voiceover, with Deepgram mocked to `dg`; background job runs before this returns."""
        with patch(DG, AsyncMock(return_value=dg or transcript())):
            return self.client.post(
                f"/platform/studio/runs/{RUN}/voice/upload{query}", files={"file": (name, data, mime)}
            )

    def status(self) -> dict:
        """Current voice job status through the API."""
        return self.client.get(f"/platform/studio/runs/{RUN}/voice/status").json()

    def transcript(self) -> dict:
        """The transcript through the API."""
        return self.client.get(f"/platform/studio/runs/{RUN}/transcript").json()

    def patch(self, **body):
        """PATCH the transcript."""
        return self.client.patch(f"/platform/studio/runs/{RUN}/transcript", json=body)

    def latest(self, stage: str, name: str) -> dict:
        """Body of the newest stored version of an artifact."""
        prefix = f"users/{PLATFORM_USER_ID}/runs/{RUN}/{stage}/{name}@v"
        from cf_platform.core.artifact_manager import latest_version_key
        key = latest_version_key([k for k in self.storage._objects if k.startswith(prefix)])
        return self.storage._objects[key]["body"]

    def versions(self, stage: str, name: str) -> int:
        """Count stored versions of an artifact."""
        prefix = f"users/{PLATFORM_USER_ID}/runs/{RUN}/{stage}/{name}@v"
        return len([k for k in self.storage._objects if k.startswith(prefix)])


@contextmanager
def uv_env(voice_source: str | None = "uploaded", language: str | None = None) -> Iterator[Env]:
    """Yield an Env whose run `run1` has the given voice_source (None = no run row) and language."""
    storage, runs, trace = InMemoryArtifactStorage(), InMemoryRunRepository(), InMemoryTraceEventRepository()
    if voice_source is not None:
        inputs = {"voice_source": voice_source} if voice_source else {}
        if language:
            inputs["language"] = language
        asyncio.run(create_run(PLATFORM_USER_ID, "studio", inputs, runs, run_id=RUN))
    settings = SimpleNamespace(
        VOICE_UPLOAD_MAX_MB=1, VOICE_UPLOAD_MIN_S=3.0, VOICE_UPLOAD_MAX_S=180.0,
        DEEPGRAM_API_KEY="dg-key", DEEPGRAM_COST_PER_MIN_USD=0.006, VOICE_LOW_CONFIDENCE=0.6, ANTHROPIC_API_KEY="k",
        STORYBOARD_MIN_SCENE_S=1.0, PEXELS_API_KEY="", PIXABAY_API_KEY="", OUTPUT_UPLOAD_MAX_MB=500,
        COLOR_GRADE_PRESET="neutral", BLUR_FILL_ENABLED=True, FFMPEG_TIMEOUT_SECONDS=60, FFMPEG_SCENE_THREADS=2,
    )
    overrides = {
        get_settings: lambda: Settings.model_validate(VALID_ENV),
        get_artifact_storage: lambda: storage,
        get_platform_settings: lambda: settings,
        get_run_repository: lambda: runs,
        get_trace_event_repository: lambda: trace,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield Env(TestClient(app, raise_server_exceptions=True), storage, runs, trace, settings)
    finally:
        for dep in overrides:
            app.dependency_overrides.pop(dep, None)


# ── S1: creation mode ────────────────────────────────────────────────────


def test_default_run_is_generated_and_uploaded_is_stored_on_the_run():
    with p12_env() as env:
        pid = env.create_project()
        item = env.add_item(pid, "Why rents rise")
        plain = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item]}).json()
        up = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item], "voice_source": "uploaded"}).json()
        ctx = lambda r: env.client.get(f"/platform/studio/runs/{r['run_id']}/context").json()  # noqa: E731
        assert ctx(plain)["voice_source"] == "generated"
        assert ctx(up)["voice_source"] == "uploaded"
        assert env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item], "voice_source": "x"}).status_code == 422


def test_language_seed_defaults_to_project_then_english_and_can_be_chosen_per_run():
    with p12_env() as env:
        pid = env.create_project()
        item = env.add_item(pid, "Why rents rise")
        make = lambda **kw: env.client.post(  # noqa: E731
            f"/platform/projects/{pid}/runs", json={"item_ids": [item], **kw}).json()["run_id"]
        lang = lambda rid: env.client.get(f"/platform/studio/runs/{rid}/context").json()["language"]  # noqa: E731
        assert lang(make()) == "en"                                           # no project language
        env.client.patch(f"/platform/projects/{pid}", json={"config": {"language": "ru"}})
        assert lang(make()) == "ru"                                           # project default
        assert lang(make(language="en")) == "en"                              # per-run choice beats it
        assert lang(make(voice_source="uploaded", language="ru")) == "ru"
        assert env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item], "language": "RU"}).status_code == 422


def test_the_runs_language_is_sent_to_deepgram():
    with uv_env(language="ru") as env:
        mock = AsyncMock(return_value=transcript())
        with patch(DG, mock):
            env.client.post(f"/platform/studio/runs/{RUN}/voice/upload", files={"file": ("vo.mp3", MP3, "audio/mpeg")})
        assert mock.await_args.kwargs["language"] == "ru"
    with uv_env() as env:                                                     # run from before the seed
        mock = AsyncMock(return_value=transcript())
        with patch(DG, mock):
            env.client.post(f"/platform/studio/runs/{RUN}/voice/upload", files={"file": ("vo.mp3", MP3, "audio/mpeg")})
        assert mock.await_args.kwargs["language"] == "en"


def test_deepgram_request_carries_the_language_parameter():
    import httpx

    from cf_platform.workers.voice_production import _deepgram_transcribe
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={
            "metadata": {"duration": 2.5},
            "results": {"channels": [{"alternatives": [{"words": [{"word": "привет", "start": 0.0, "end": 0.5}]}]}]},
        })

    real = httpx.AsyncClient
    with patch("cf_platform.workers.voice_production.httpx.AsyncClient",
               lambda **kw: real(transport=httpx.MockTransport(handler), **kw)):
        out = asyncio.run(_deepgram_transcribe("https://x/a.mp3", "k", language="ru"))
        assert seen["params"]["language"] == "ru" and out.duration_s == 2.5 and out.words[0].word == "привет"
        asyncio.run(_deepgram_transcribe("https://x/a.mp3", "k"))
        assert "language" not in seen["params"]


# ── S1: validation ───────────────────────────────────────────────────────


def test_each_validation_failure_is_a_422_with_a_reason():
    with uv_env() as env:
        cases = [
            dict(name="vo.ogg", mime="audio/ogg"),                       # extension
            dict(name="vo.mp3", mime="video/mp4"),                       # MIME
            dict(data=b"", name="vo.mp3"),                               # empty
            dict(data=b"not audio at all"),                              # header
            dict(data=b"RIFF\x00\x00\x00\x00NOPE", name="vo.wav", mime="audio/wav"),
            dict(data=b"ID3" + b"\x00" * (1024 * 1024 + 10)),            # > 1 MB limit
        ]
        for case in cases:
            r = env.upload(**case)
            assert r.status_code == 422, (case, r.text)
            assert r.json()["detail"]
        assert "Maximum is 1 MB" in env.upload(**cases[-1]).json()["detail"]
        assert env.storage._bytes == {}                                   # nothing stored


def test_wav_and_m4a_pass_validation():
    with uv_env() as env:
        wav = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 50
        m4a = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 50
        assert env.upload(data=wav, name="a.wav", mime="audio/x-wav").status_code == 202
        assert env.upload(data=m4a, name="a.m4a", mime="audio/mp4", query="?confirm_discard=true").status_code == 202


def test_upload_needs_an_uploaded_run():
    for source in ("generated", "", None):
        with uv_env(voice_source=source) as env:
            r = env.upload()
            assert r.status_code == 409 and "uploaded voiceover" in r.json()["detail"]


# ── S1: happy path ───────────────────────────────────────────────────────


def test_upload_transcribes_and_stores_the_transcript_as_the_script():
    with uv_env() as env:
        r = env.upload()
        assert r.status_code == 202
        assert env.status()["status"] == "complete" and env.status()["word_count"] == 12
        assert asyncio.run(env.storage.get_bytes(f"runs/{RUN}/voiceover/uploaded.mp3")) == MP3

        va = env.latest("voice", "voice_alignment")
        VoiceAlignmentArtifact.model_validate(va)                          # same shape as a generated run's
        assert set(va) == set(VoiceAlignmentArtifact.model_fields)
        assert va["alignment_method"] == "uploaded_deepgram_nova2"
        assert va["mp3_r2_key"] == f"runs/{RUN}/voiceover/uploaded.mp3"

        script = env.client.get(f"/platform/studio/runs/{RUN}/script").json()
        assert script["source"] == "uploaded_vo" and script["script"] == " ".join(f"w{i}" for i in range(12))
        voice = env.client.get(f"/platform/studio/runs/{RUN}/voice").json()
        assert voice["word_count"] == 12 and voice["mp3_url"]


def test_trace_events_record_upload_and_transcription_with_cost():
    with uv_env() as env:
        env.upload()
        events = {e.op: e for e in asyncio.run(env.trace.list_for_run(RUN))}
        assert events["voice_upload"].meta["filename"] == "vo.mp3" and events["voice_upload"].status == "ok"
        t = events["transcribe"]
        assert t.status == "ok" and t.meta["word_count"] == 12 and t.meta["duration_s"] == 6.0
        assert t.cost_usd == round(6.0 / 60 * 0.006, 6)


def test_contraction_split_words_are_collapsed_like_the_storyboard_reads_them():
    from cf_platform.workers.voice_production import VoiceWordTimestamp as W
    raw = [W(word="it", start_ms=0, end_ms=300), W(word="'s", start_ms=0, end_ms=300), W(word="fine", start_ms=300, end_ms=900)]
    with uv_env() as env:
        env.upload(dg=transcript(words=raw, duration=6.0))
        words = [w["word"] for w in env.transcript()["words"]]
    assert words == ["it's", "fine"]                                       # editor indices == storyboard indices


def test_transcript_endpoint_before_and_during_a_job():
    with uv_env() as env:
        assert env.client.get(f"/platform/studio/runs/{RUN}/transcript").status_code == 404
        asyncio.run(env.storage.put_json(f"runs/{RUN}/voice/current_job.json", {"status": "running"}))
        body = env.transcript()
        assert body["words"] == [] and body["job_status"] == "running"


# ── S2: edits over HTTP ──────────────────────────────────────────────────


def test_patch_replace_writes_new_versions_and_the_script_follows():
    with uv_env() as env:
        env.upload()
        audio_before = asyncio.run(env.storage.get_bytes(f"runs/{RUN}/voiceover/uploaded.mp3"))
        va_versions = env.versions("voice", "voice_alignment")
        r = env.patch(edits=[{"start": 3, "end": 3, "text": "fixed"}])
        assert r.status_code == 200 and r.json()["changes"] == ['word 4: "w3" → "fixed"']
        assert env.versions("voice", "voice_alignment") == va_versions + 1
        assert env.latest("voice", "voice_alignment")["word_timestamps"][3]["word"] == "fixed"
        assert "w2 fixed w4" in env.client.get(f"/platform/studio/runs/{RUN}/script").json()["script"]
        assert asyncio.run(env.storage.get_bytes(f"runs/{RUN}/voiceover/uploaded.mp3")) == audio_before


def test_patch_split_changes_word_count_and_keeps_timing_total():
    with uv_env() as env:
        env.upload()
        r = env.patch(edits=[{"start": 0, "end": 0, "text": "a b"}])
        assert r.status_code == 200 and r.json()["word_count"] == 13
        words = env.transcript()["words"]
        assert (words[0]["start_ms"], words[1]["end_ms"]) == (0, 500) and words[0]["end_ms"] == words[1]["start_ms"]


def test_patch_refusals_are_422_with_the_reason_and_change_nothing():
    with uv_env() as env:
        env.upload()
        before = env.versions("voice", "voice_alignment")
        assert "delete" in env.patch(edits=[{"start": 1, "end": 1, "text": ""}]).json()["detail"]
        assert "on-screen text" in env.patch(text="w0 extra w1 w2 w3 w4 w5 w6 w7 w8 w9 w10 w11").json()["detail"]
        assert "leaves out" in env.patch(text="w0 w1 w2").json()["detail"]
        assert env.patch().status_code == 422
        assert env.patch(edits=[], text="x").status_code == 422
        assert env.versions("voice", "voice_alignment") == before


def test_rebuild_from_text_dry_run_reports_changes_without_writing():
    with uv_env() as env:
        env.upload()
        text = " ".join(f"w{i}" for i in range(12)).replace("w5", "five")
        before = env.versions("voice", "voice_alignment")
        r = env.patch(text=text, dry_run=True)
        assert r.status_code == 200 and r.json()["applied"] is False and r.json()["changes"] == ['word 6: "w5" → "five"']
        assert env.versions("voice", "voice_alignment") == before
        assert env.patch(text=text).json()["applied"] is True
        assert env.versions("voice", "voice_alignment") == before + 1


def test_patch_needs_a_transcript_and_an_uploaded_run():
    with uv_env() as env:
        assert env.patch(text="x").status_code == 409                       # no transcript yet
    with uv_env(voice_source="generated") as env:
        assert env.patch(text="x").status_code == 409


# ── S3: storyboard from the transcript ───────────────────────────────────


def _fake_storyboard_worker(captured: dict):
    """A storyboard worker double that records the state it was given."""
    async def worker(state):
        captured["state"] = state
        sb = make_storyboard(make_words())
        from cf_platform.core.schemas import WorkerOutput
        return WorkerOutput(artifact=VerifiedStoryboardArtifact(
            prompt_version="t", scene_count=len(sb.scenes),
            storyboard=sb.model_dump(by_alias=True, mode="json"), generated_at=datetime.now(),
        ))
    return worker


def _build_storyboard(env: Env, script="IGNORED") -> dict:
    """POST /workers/storyboard with a fake worker; return what the worker received."""
    captured: dict = {}
    with patch("cf_platform.interfaces.routes.workers.build_storyboard_worker", lambda *a, **k: _fake_storyboard_worker(captured)):
        r = env.client.post("/platform/workers/storyboard", json={"run_id": RUN, "script": script, "format_track": "portrait"})
    assert r.status_code == 202, r.text
    return captured


def test_storyboard_reads_the_uploaded_transcript_and_alignment_not_the_request_script():
    with uv_env() as env:
        env.upload()
        env.patch(edits=[{"start": 3, "end": 3, "text": "fixed"}])
        scripts_before = env.versions("script", "script")
        captured = _build_storyboard(env, script="SOMETHING ELSE")
        state = captured["state"]
        _, body = asyncio.run(__import__("cf_platform.core.artifact_manager", fromlist=["read_artifact"]).read_artifact(env.storage, state.artifacts["script"]))
        assert body["source"] == "uploaded_vo" and "fixed" in body["script"] and "SOMETHING" not in body["script"]
        assert "voice_alignment" in state.artifacts
        assert env.versions("script", "script") == scripts_before          # no extra script version written
        assert env.status()["status"] == "complete"
        assert env.client.get(f"/platform/studio/runs/{RUN}/storyboard/status").json()["status"] == "complete"


def test_a_generated_run_still_writes_the_request_script():
    with uv_env(voice_source="generated") as env:
        captured = _build_storyboard(env, script="my own script")
        _, body = asyncio.run(__import__("cf_platform.core.artifact_manager", fromlist=["read_artifact"]).read_artifact(env.storage, captured["state"].artifacts["script"]))
        assert body["script"] == "my own script" and body.get("source") is None


def test_generating_a_voice_for_an_uploaded_run_is_refused():
    with uv_env() as env:
        env.upload()
        r = env.client.post("/platform/workers/voice", json={"run_id": RUN, "script": "x"})
        assert r.status_code == 409 and "uploaded voiceover" in r.json()["detail"]


def test_editing_is_locked_once_a_storyboard_exists():
    with uv_env() as env:
        env.upload()
        _build_storyboard(env)
        r = env.patch(edits=[{"start": 0, "end": 0, "text": "x"}])
        assert r.status_code == 409 and "upload the voiceover again" in r.json()["detail"]
        t = env.transcript()
        assert t["storyboard_exists"] is True and t["editable"] is False


def _acquire_everything(env: Env) -> None:
    """Seed an acquired manifest and bytes behind every scene file."""
    sb = Storyboard.model_validate(env.client.get(f"/platform/studio/runs/{RUN}/storyboard").json()["storyboard"])
    asyncio.run(seed_manifest_for(env, make_manifest(sb)))
    for e in make_manifest(sb).entries:
        asyncio.run(env.storage.put_bytes(e.file_key, b"IMG"))


async def seed_manifest_for(env: Env, manifest: AssetManifest) -> str:
    """Seed the manifest artifact for run1."""
    return await seed_manifest(env.storage, manifest)


def test_timeline_render_script_and_capcut_zip_use_the_uploaded_audio():
    with uv_env() as env:
        env.upload()
        _build_storyboard(env)
        _acquire_everything(env)

        timeline, _ = asyncio.run(prepare_run_timeline(env.storage, RUN, format_track="portrait"))
        assert timeline.voiceover_key == f"runs/{RUN}/voiceover/uploaded.mp3"
        assert len(timeline.scenes) == 3 and timeline.voiceover_duration_s == 6.0
        # Same shape as a generated run's timeline: only the file behind the voice differs.
        assert set(timeline.model_dump()) == set(
            asyncio.run(prepare_run_timeline(env.storage, RUN, format_track="portrait"))[0].model_dump()
        )
        sb_body = env.client.get(f"/platform/studio/runs/{RUN}/storyboard").json()["storyboard"]
        script = build_render_script_from_timeline(
            RUN, timeline, Storyboard.model_validate(sb_body),
            AssetManifest.model_validate(env.client.get(f"/platform/studio/runs/{RUN}/manifest").json()["manifest"]),
            "neutral", True,
        )
        assert "$BASE/voiceover/" in script          # the script finds the voiceover by folder

        r = env.client.get(f"/platform/studio/runs/{RUN}/export/capcut")
        assert r.status_code == 200, r.text
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert z.read("voiceover/uploaded.mp3") == MP3
        assert json.loads(z.read("timeline.json"))["voiceover_path"] == "voiceover/uploaded.mp3"


def test_metadata_uses_the_transcript_as_the_script():
    from cf_platform.core.schemas import WorkerOutput
    from cf_platform.workers.youtube_metadata import YoutubeMetadataArtifact

    with uv_env() as env:
        env.upload()
        seen = {}

        def fake_builder(storage, api_key):
            async def worker(state):
                from cf_platform.core.artifact_manager import read_artifact
                _, body = await read_artifact(storage, state.artifacts["script"])
                seen["script"] = body["script"]
                return WorkerOutput(artifact=YoutubeMetadataArtifact(title="t", description="d", tags=["a"], generated_at=datetime.now()))
            return worker

        with patch("cf_platform.workers.youtube_metadata.build_youtube_metadata_worker", fake_builder):
            r = env.client.post("/platform/workers/metadata", json={"run_id": RUN})
        assert r.status_code == 200, r.text
        assert seen["script"] == " ".join(f"w{i}" for i in range(12))


# ── S4: guards ───────────────────────────────────────────────────────────


def _job_error(env: Env, **kw) -> str:
    """Upload with a mocked Deepgram answer and return the job's error message."""
    assert env.upload(**kw).status_code == 202
    s = env.status()
    assert s["status"] == "error", s
    return s["error"]


def test_silent_audio_ends_in_a_readable_error():
    with uv_env() as env:
        assert "No speech" in _job_error(env, dg=transcript(words=[]))
        assert env.client.get(f"/platform/studio/runs/{RUN}/voice").status_code == 404
        failed = [e for e in asyncio.run(env.trace.list_for_run(RUN)) if e.op == "transcribe"]
        assert failed and failed[0].status == "error"


def test_too_short_and_too_long_are_refused():
    with uv_env() as env:
        assert "too short" in _job_error(env, dg=transcript(duration=1.0))
    with uv_env() as env:
        assert "too long" in _job_error(env, dg=transcript(duration=400.0))


def test_a_language_that_looks_wrong_is_a_warning_not_a_failure():
    from cf_platform.workers.voice_production import VoiceWordTimestamp as W
    cyrillic = [W(word=w, start_ms=i * 500, end_ms=(i + 1) * 500, confidence=0.95)
                for i, w in enumerate("это совсем другой язык речи тут".split())]
    with uv_env() as env:                                                  # run language: en
        assert env.upload(dg=transcript(words=cyrillic)).status_code == 202
        status = env.status()
        assert status["status"] == "complete"                              # transcript is kept
        assert status["language_warning"]["expected"] == "en" and status["language_warning"]["detected"] == "ru"
        assert env.transcript()["language_warning"]["reason"]
        assert env.transcript()["language"] == "en"


def test_low_confidence_is_a_warning_without_a_detected_language():
    from cf_platform.workers.voice_production import VoiceWordTimestamp as W
    unsure = [W(word=f"w{i}", start_ms=i * 500, end_ms=(i + 1) * 500, confidence=0.3) for i in range(8)]
    with uv_env() as env:
        env.upload(dg=transcript(words=unsure))
        warning = env.status()["language_warning"]
        assert warning["detected"] is None and "unsure" in warning["reason"]


def test_a_matching_transcript_has_no_warning():
    with uv_env() as env:
        env.upload()
        assert env.status()["language_warning"] is None


def test_the_operator_confirms_or_changes_the_run_language():
    from cf_platform.workers.voice_production import VoiceWordTimestamp as W
    cyrillic = [W(word="привет", start_ms=i * 500, end_ms=(i + 1) * 500, confidence=0.95) for i in range(6)]
    with uv_env() as env:
        env.upload(dg=transcript(words=cyrillic))
        r = env.client.put(f"/platform/studio/runs/{RUN}/language", json={"language": "ru"})
        assert r.json() == {"language": "ru", "changed": True, "transcript_stale": True}
        assert env.transcript()["language"] == "ru" and env.transcript()["language_warning"]["acknowledged"] is True
        again = env.client.put(f"/platform/studio/runs/{RUN}/language", json={"language": "ru"}).json()
        assert again["changed"] is False and again["transcript_stale"] is False
        assert env.client.put(f"/platform/studio/runs/{RUN}/language", json={"language": "Russian"}).status_code == 422
        assert env.client.put("/platform/studio/runs/nope/language", json={"language": "en"}).status_code == 404


def test_deepgram_failure_is_an_error_not_a_stuck_running_job():
    with uv_env() as env:
        with patch(DG, AsyncMock(side_effect=RuntimeError("Deepgram returned 400: corrupt data"))):
            env.client.post(f"/platform/studio/runs/{RUN}/voice/upload", files={"file": ("vo.mp3", MP3, "audio/mpeg")})
        s = env.status()
        assert s["status"] == "error" and "could not transcribe" in s["error"] and "corrupt" in s["error"]


def test_an_unexpected_crash_is_also_an_error():
    with uv_env() as env:
        with patch(DG, AsyncMock(side_effect=ValueError("boom"))):
            env.client.post(f"/platform/studio/runs/{RUN}/voice/upload", files={"file": ("vo.mp3", MP3, "audio/mpeg")})
        assert env.status()["status"] == "error"


def test_missing_deepgram_key_is_a_readable_error():
    with uv_env() as env:
        env.settings.DEEPGRAM_API_KEY = ""
        assert "DEEPGRAM_API_KEY" in _job_error(env)


def test_upload_while_a_job_is_running_is_refused():
    with uv_env() as env:
        asyncio.run(env.storage.put_json(f"runs/{RUN}/voice/current_job.json", {"status": "running"}))
        assert env.upload().status_code == 409


def test_re_upload_asks_for_confirmation_and_lists_what_is_discarded():
    with uv_env() as env:
        env.upload()
        r = env.upload()
        assert r.status_code == 409 and r.json()["needs_confirmation"] is True
        assert "transcript" in " ".join(r.json()["discards"]) and "storyboard" not in r.json()["detail"]
        _build_storyboard(env)
        r = env.upload()
        assert r.status_code == 409 and "the storyboard" in r.json()["discards"]
        assert env.versions("voice", "voice_alignment") == 1                # nothing replaced yet


def test_confirmed_re_upload_discards_storyboard_and_assets_and_unlocks_editing():
    with uv_env() as env:
        env.upload()
        _build_storyboard(env)
        _acquire_everything(env)
        assert env.client.get(f"/platform/studio/runs/{RUN}/manifest").json()["manifest"]["entries"]

        r = env.upload(query="?confirm_discard=true", dg=transcript(words=make_words(8), duration=4.0))
        assert r.status_code == 202 and env.status()["status"] == "complete"
        assert env.client.get(f"/platform/studio/runs/{RUN}/storyboard").status_code == 404
        assert env.client.get(f"/platform/studio/runs/{RUN}/manifest").json().get("manifest", {}).get("entries", []) == []
        assert env.transcript()["editable"] is True and len(env.transcript()["words"]) == 8
        assert env.patch(edits=[{"start": 0, "end": 0, "text": "ok"}]).status_code == 200
        # acquisition / render refuse the discarded storyboard
        assert env.client.post("/platform/workers/acquisition", json={"run_id": RUN}).status_code == 404
        # a newly generated storyboard is live again
        _build_storyboard(env)
        assert env.client.get(f"/platform/studio/runs/{RUN}/storyboard").status_code == 200


# ── S4: end to end ───────────────────────────────────────────────────────


def test_end_to_end_create_upload_edit_storyboard_render_script_timeline():
    """Create an uploaded run through the API, then upload, edit, storyboard, acquire, timeline, render script."""
    with p12_env() as penv:
        pid = penv.create_project()
        item = penv.add_item(pid, "Why rents rise")
        created = penv.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item], "voice_source": "uploaded"})
        assert created.status_code == 201
        run_row = asyncio.run(penv.runs.get(created.json()["run_id"]))
        assert run_row.inputs["voice_source"] == "uploaded"

    with uv_env() as env:                                   # same shape of run, bound to run1
        assert env.upload().status_code == 202 and env.status()["status"] == "complete"
        assert env.patch(edits=[{"start": 5, "end": 5, "text": "corrected"}]).status_code == 200
        _build_storyboard(env)
        _acquire_everything(env)
        timeline, key = asyncio.run(prepare_run_timeline(env.storage, RUN, format_track="portrait", write=True))
        assert key and timeline.voiceover_key == f"runs/{RUN}/voiceover/uploaded.mp3"
        sb = Storyboard.model_validate(env.client.get(f"/platform/studio/runs/{RUN}/storyboard").json()["storyboard"])
        manifest = AssetManifest.model_validate(env.client.get(f"/platform/studio/runs/{RUN}/manifest").json()["manifest"])
        script = build_render_script_from_timeline(RUN, timeline, sb, manifest, "neutral", True)
        assert script.startswith("#!") and "$BASE/voiceover/" in script
        assert "corrected" in env.client.get(f"/platform/studio/runs/{RUN}/script").json()["script"]
