"""Shared fixtures-as-functions for the Sprint P13 tests (storyboard control).

A seeded run is: 12 voiceover words of 0.5s each, a three-scene storyboard cut at
words 0 / 4 / 8, a voice_alignment artifact, and optionally an acquired manifest.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient

from cf_platform.core.artifact_manager import InMemoryArtifactStorage, write_artifact
from cf_platform.core.config import get_platform_settings
from cf_platform.core.schemas import LineageEnvelope
from cf_platform.core.trace_repo import InMemoryTraceEventRepository
from cf_platform.interfaces.api import get_artifact_storage
from cf_platform.interfaces.dependencies import PLATFORM_USER_ID, get_trace_event_repository
from cf_platform.workers.acquisition_worker import build_manifest_artifact, manifest_entry_for_scene
from cf_platform.workers.storyboard_worker import (
    VerifiedStoryboardArtifact,
    _apply_patches_and_render_options,
    _reify_scene,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp
from src.config import Settings, get_settings
from src.main import app
from src.models import AssetManifest, Storyboard

RUN_ID = "run1"
WORD_MS = 500
N_WORDS = 12
MIN_SCENE_S = 1.0

VALID_ENV = {
    "ENVIRONMENT": "dev",
    "R2_ACCOUNT_ID": "fake",
    "R2_ACCESS_KEY_ID": "fake",
    "R2_SECRET_ACCESS_KEY": "fake",
    "R2_BUCKET_NAME": "fake-bucket",
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "PEXELS_API_KEY": "fake-pexels",
    "REPLICATE_API_TOKEN": "fake-replicate",
    "FREESOUND_API_KEY": "fake-freesound",
    "OPERATOR_PASSWORD": "testpass",
    "SESSION_SECRET_KEY": "test-secret",
}


def make_words(n: int = N_WORDS, word_ms: int = WORD_MS) -> list[VoiceWordTimestamp]:
    """Return n words "w0".."w{n-1}", back to back, word_ms each."""
    return [
        VoiceWordTimestamp(word=f"w{i}", start_ms=i * word_ms, end_ms=(i + 1) * word_ms, confidence=1.0)
        for i in range(n)
    ]


def make_storyboard(
    words: list[VoiceWordTimestamp],
    starts: tuple[int, ...] = (0, 4, 8),
    **scene_overrides: dict,
) -> Storyboard:
    """Build a storyboard cut at the given start words, reified like the worker does.

    scene_overrides maps a scene id to extra fields, e.g. **{"2": {"sfx": "whoosh"}}.
    """
    scenes: list[dict] = []
    for k, start in enumerate(starts):
        end = (starts[k + 1] - 1) if k + 1 < len(starts) else len(words) - 1
        raw = {
            "scene": str(k + 1), "start_word": start, "end_word": end,
            "primary_stk": f"query {k + 1}", "context_stk": f"context {k + 1}",
            "concept_stk": f"concept {k + 1}", "segment_type": "B-roll",
        }
        _reify_scene(raw, words, k)
        raw.update(scene_overrides.get(str(k + 1), {}))
        scenes.append(raw)
    storyboard = Storyboard.model_validate({
        "global": {"subtitle_style": "x", "bg_music": "none", "visual_style": "x"},
        "scenes": scenes,
        "summary": {"total_scenes": len(scenes), "total_duration_s": 6.0, "rhythm": "x"},
    })
    return _apply_patches_and_render_options(storyboard, [])


def make_manifest(storyboard: Storyboard, acquired: bool = True, ext: str = ".jpg") -> AssetManifest:
    """Return a manifest with one entry per scene; acquired entries point at {id}{ext}."""
    entries = []
    for scene in storyboard.scenes:
        entry = manifest_entry_for_scene(scene)
        if acquired:
            folder = "images" if ext == ".jpg" else "video"
            entry.status = "acquired"
            entry.source = "pexels"
            entry.file_key = f"runs/{RUN_ID}/{folder}/{scene.scene}{ext}"
            entry.qa_passed = True
        entries.append(entry)
    return AssetManifest(run_id=RUN_ID, entries=entries)


def _lineage() -> LineageEnvelope:
    """Return a throwaway lineage envelope for seeded artifacts."""
    return LineageEnvelope(
        run_id=RUN_ID, worker="test", worker_version="1.0.0",
        prompt_version="test", model="none", created_at=datetime.now(),
    )


async def seed_storyboard(storage: InMemoryArtifactStorage, storyboard: Storyboard) -> str:
    """Write a verified_storyboard artifact version; returns its key."""
    record = await write_artifact(
        storage,
        VerifiedStoryboardArtifact(
            prompt_version="test", scene_count=len(storyboard.scenes),
            storyboard=storyboard.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(),
        ),
        name="verified_storyboard", stage="storyboard",
        run_id=RUN_ID, user_id=PLATFORM_USER_ID, lineage=_lineage(),
    )
    return record.r2_key


async def seed_voice(storage: InMemoryArtifactStorage, words: list[VoiceWordTimestamp]) -> str:
    """Write a voice_alignment artifact version; returns its key."""
    record = await write_artifact(
        storage,
        VoiceAlignmentArtifact(
            mp3_r2_key="", word_timestamps=words, alignment_method="deepgram_nova2",
            total_duration_s=words[-1].end_ms / 1000,
        ),
        name="voice_alignment", stage="voice",
        run_id=RUN_ID, user_id=PLATFORM_USER_ID, lineage=_lineage(),
    )
    return record.r2_key


async def seed_manifest(storage: InMemoryArtifactStorage, manifest: AssetManifest) -> str:
    """Write an asset_manifest artifact version; returns its key."""
    record = await write_artifact(
        storage, build_manifest_artifact(manifest, datetime.now()),
        name="asset_manifest", stage="acquisition",
        run_id=RUN_ID, user_id=PLATFORM_USER_ID, lineage=_lineage(),
    )
    return record.r2_key


@dataclass
class P13Env:
    """A TestClient wired to in-memory storage holding one seeded run."""

    client: TestClient
    storage: InMemoryArtifactStorage
    words: list[VoiceWordTimestamp]
    settings: SimpleNamespace

    def storyboard(self) -> dict:
        """Return the latest storyboard (with effective strategies) through the API."""
        r = self.client.get(f"/platform/studio/runs/{RUN_ID}/storyboard")
        assert r.status_code == 200, r.text
        return r.json()["storyboard"]

    def scenes(self) -> list[dict]:
        """Return the latest storyboard's scenes."""
        return self.storyboard()["scenes"]

    def manifest_entries(self) -> list[dict]:
        """Return the latest manifest's entries through the API."""
        r = self.client.get(f"/platform/studio/runs/{RUN_ID}/manifest")
        assert r.status_code == 200, r.text
        return r.json()["manifest"]["entries"]

    def versions(self, stage: str, name: str) -> int:
        """Count the stored versions of one artifact."""
        prefix = f"users/{PLATFORM_USER_ID}/runs/{RUN_ID}/{stage}/{name}@v"
        return len([k for k in self.storage._objects if k.startswith(prefix)])


@contextmanager
def p13_env(
    with_manifest: bool = False,
    with_voice: bool = True,
    starts: tuple[int, ...] = (0, 4, 8),
    **scene_overrides: dict,
) -> Iterator[P13Env]:
    """Yield a P13Env with one seeded run; dependency overrides are removed on exit."""
    storage = InMemoryArtifactStorage()
    words = make_words()
    storyboard = make_storyboard(words, starts, **scene_overrides)

    async def _seed() -> None:
        """Seed the storyboard, and the voice alignment / manifest when asked."""
        await seed_storyboard(storage, storyboard)
        if with_voice:
            await seed_voice(storage, words)
        if with_manifest:
            await seed_manifest(storage, make_manifest(storyboard))

    asyncio.run(_seed())

    platform_settings = SimpleNamespace(
        STORYBOARD_MIN_SCENE_S=MIN_SCENE_S, PEXELS_API_KEY="fake-pexels", PIXABAY_API_KEY="",
        OUTPUT_UPLOAD_MAX_MB=500, COLOR_GRADE_PRESET="neutral", BLUR_FILL_ENABLED=True,
        FFMPEG_TIMEOUT_SECONDS=60, FFMPEG_SCENE_THREADS=2,
    )
    trace_repo = InMemoryTraceEventRepository()
    overrides = {
        get_settings: lambda: Settings.model_validate(VALID_ENV),
        get_artifact_storage: lambda: storage,
        get_platform_settings: lambda: platform_settings,
        get_trace_event_repository: lambda: trace_repo,
    }
    app.dependency_overrides.update(overrides)
    try:
        yield P13Env(
            client=TestClient(app, raise_server_exceptions=True), storage=storage, words=words,
            settings=platform_settings,
        )
    finally:
        for dependency in overrides:
            app.dependency_overrides.pop(dependency, None)
