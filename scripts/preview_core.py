"""Local UI preview with in-memory storage — for looking at the pages, never for real data.

Run with the `core-preview` entry of .claude/launch.json (it sets fake provider keys and no database).
Replaces the two places that would reach R2 — the platform's artifact storage and the legacy R2Client
used by the run settings routes — with process memory, so every screen can be opened and clicked
without credentials. Nothing is persisted; every paid provider call still fails with its own error.
"""

import json

import src.routes.runs as runs_module
from cf_platform.core.artifact_manager import ArtifactStorageError, InMemoryArtifactStorage
from cf_platform.interfaces.dependencies import get_artifact_storage
from src import routes  # noqa: F401
from src.exceptions import StorageError
from src.main import app

_storage = InMemoryArtifactStorage()


class _MemR2:
    """The few R2Client methods the run settings routes use, backed by the same memory."""

    def upload_json(self, key: str, data: dict) -> None:
        """Store JSON in the shared in-memory storage."""
        _storage._objects[key] = json.loads(json.dumps(data))

    def get_json(self, key: str) -> dict:
        """Read JSON back; StorageError when absent, like R2Client."""
        try:
            return _storage._objects[key]
        except KeyError:
            raise StorageError(f"not found: {key}") from None

    def get_bytes(self, key: str) -> bytes:
        """Read bytes back; StorageError when absent."""
        try:
            return _storage._bytes[key]
        except KeyError:
            raise StorageError(f"not found: {key}") from None

    def delete_run(self, run_id: str) -> int:
        """Drop every object of a run."""
        keys = [k for k in list(_storage._objects) + list(_storage._bytes) if f"runs/{run_id}/" in k]
        for k in keys:
            _storage._objects.pop(k, None)
            _storage._bytes.pop(k, None)
        return len(keys)

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """A fake URL."""
        return f"https://fake-r2.example.com/{key}"


app.dependency_overrides[get_artifact_storage] = lambda: _storage
runs_module._make_r2_client = lambda settings: _MemR2()
_ = ArtifactStorageError


# ── Preview-only seeding: GET /__seed/{run_id} gives a run a voice, a storyboard and a manifest ──
from datetime import datetime  # noqa: E402

from fastapi import Request  # noqa: E402

from cf_platform.core.artifact_manager import write_artifact  # noqa: E402
from cf_platform.core.schemas import LineageEnvelope  # noqa: E402
from cf_platform.workers.acquisition_worker import build_manifest_artifact, manifest_entry_for_scene  # noqa: E402
from cf_platform.workers.storyboard_worker import (  # noqa: E402
    VerifiedStoryboardArtifact,
    _apply_patches_and_render_options,
    _reify_scene,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact, VoiceWordTimestamp  # noqa: E402
from src.models import AssetManifest, Storyboard  # noqa: E402


@app.get("/__seed/{run_id}", include_in_schema=False)
async def _seed(run_id: str, request: Request, tenant: str = "operator") -> dict:
    """Seed one run with 12 words, a 3-scene stock storyboard and a manifest with two acquired scenes."""
    words = [VoiceWordTimestamp(word=f"word{i}", start_ms=i * 500, end_ms=(i + 1) * 500, confidence=1.0) for i in range(12)]
    scenes = []
    for k, start in enumerate((0, 4, 8)):
        end = (start + 3) if k < 2 else 11
        raw = {"scene": str(k + 1), "start_word": start, "end_word": end, "primary_stk": f"housing market {k + 1}",
               "context_stk": "x", "concept_stk": "y", "segment_type": "B-roll"}
        _reify_scene(raw, words, k)
        scenes.append(raw)
    sb = Storyboard.model_validate({
        "global": {"subtitle_style": "x", "bg_music": "none", "visual_style": "x"}, "scenes": scenes,
        "summary": {"total_scenes": 3, "total_duration_s": 6.0, "rhythm": "x"},
    })
    sb = _apply_patches_and_render_options(sb, [])
    lineage = LineageEnvelope(run_id=run_id, worker="seed", worker_version="1", prompt_version="1", model="none",
                              created_at=datetime.now())
    await write_artifact(_storage, VerifiedStoryboardArtifact(
        prompt_version="x", scene_count=3, storyboard=sb.model_dump(by_alias=True, mode="json"),
        generated_at=datetime.now()), name="verified_storyboard", stage="storyboard", run_id=run_id,
        user_id=tenant, lineage=lineage)
    await write_artifact(_storage, VoiceAlignmentArtifact(
        mp3_r2_key="", word_timestamps=words, alignment_method="deepgram_nova2", total_duration_s=6.0),
        name="voice_alignment", stage="voice", run_id=run_id, user_id=tenant, lineage=lineage)
    entries = []
    for i, scene in enumerate(sb.scenes):
        e = manifest_entry_for_scene(scene)
        if i < 2:
            e.status, e.source, e.file_key, e.qa_passed = "acquired", "pexels", f"runs/{run_id}/images/{scene.scene}.jpg", True
        entries.append(e)
    await write_artifact(_storage, build_manifest_artifact(AssetManifest(run_id=run_id, entries=entries), datetime.now()),
                         name="asset_manifest", stage="acquisition", run_id=run_id, user_id=tenant, lineage=lineage)
    return {"seeded": run_id}
