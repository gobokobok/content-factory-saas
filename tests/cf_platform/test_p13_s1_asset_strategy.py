"""Tests for P13-S1: per-scene asset strategy — model, patch, acquisition.

Covers:
- the vocabulary constant and effective_asset_strategy
- PATCH …/storyboard/scenes/{id}: accept, reject (422), tier / clip type / motion follow
- storyboard GET returns the effective strategy for every scene
- AcquisitionWorker: each strategy's path; upload scenes skipped and reported
- only-missing acquisition and collision-free file names
- render refused while an upload scene has no file
- upload before the first acquisition
- a storyboard with no asset_strategy behaves exactly as before
"""

import asyncio
from typing import get_args
from unittest.mock import AsyncMock, patch

import pytest

from cf_platform.core.schemas import StageState
from cf_platform.workers.acquisition_worker import (
    _acquire_scene,
    _acquire_single_scene,
    _compute_footage_summary,
    _wants_video,
    build_acquisition_worker,
    manifest_entry_for_scene,
)
from cf_platform.workers.render_worker import missing_assets_message
from cf_platform.workers.storyboard_worker import apply_asset_strategy
from src.models import (
    ASSET_STRATEGIES,
    AssetStrategy,
    ManifestEntry,
    StoryboardScene,
    effective_asset_strategy,
)
from tests.cf_platform.p13_helpers import (
    RUN_ID,
    make_manifest,
    make_storyboard,
    make_words,
    p13_env,
    seed_manifest,
    seed_storyboard,
)

_SCENE_URL = f"/platform/studio/runs/{RUN_ID}/storyboard/scenes"
_WORKER = "cf_platform.workers.acquisition_worker"


# ── Vocabulary ────────────────────────────────────────────────────────────────


class TestVocabulary:
    def test_one_definition(self):
        assert ASSET_STRATEGIES == ("stock_image", "stock_video", "upload")
        assert ASSET_STRATEGIES == get_args(AssetStrategy)

    def test_scene_field_defaults_to_none_and_rejects_unknown(self):
        scene = StoryboardScene(scene="1", clip_type="hard_cut", duration_s=1.0, voiceover_line="x")
        assert scene.asset_strategy is None
        with pytest.raises(ValueError):
            StoryboardScene(scene="1", clip_type="hard_cut", duration_s=1.0, voiceover_line="x", asset_strategy="hologram")

    @pytest.mark.parametrize(
        ("strategy", "tier", "clip_type", "expected"),
        [
            ("upload", "video", "hard_cut", "upload"),
            ("stock_image", "video", "hard_cut", "stock_image"),
            (None, "video", "still_with_motion", "stock_video"),
            (None, "still", "hard_cut", "stock_image"),
            (None, "still_motion", "hard_cut", "stock_image"),
            (None, None, "hard_cut", "stock_video"),
            (None, None, "still_with_motion", "stock_image"),
        ],
    )
    def test_effective_strategy(self, strategy, tier, clip_type, expected):
        assert effective_asset_strategy(strategy, tier, clip_type) == expected


# ── apply_asset_strategy ──────────────────────────────────────────────────────


class TestApplyAssetStrategy:
    def _scene(self, **fields) -> StoryboardScene:
        """Return a 4s still scene, overridable."""
        base = {
            "scene": "1", "clip_type": "still_with_motion", "duration_s": 4.0, "voiceover_line": "x",
            "asset_tier": "still_motion", "motion_effect": "pan_left",
        }
        return StoryboardScene(**{**base, **fields})

    def test_still_to_video_clears_motion(self):
        scene = apply_asset_strategy(self._scene(), "stock_video")
        assert (scene.asset_tier, scene.clip_type, scene.motion_effect) == ("video", "hard_cut", None)
        assert scene.asset_strategy == "stock_video"

    def test_video_to_still_takes_the_still_default_motion(self):
        video = self._scene(clip_type="hard_cut", asset_tier="video", motion_effect=None, duration_s=8.0)
        scene = apply_asset_strategy(video, "stock_image")
        # 8s would derive "video"; a still is floored to still_motion.
        assert (scene.asset_tier, scene.clip_type, scene.motion_effect) == ("still_motion", "still_with_motion", "ken_burns")

    def test_still_stays_still_and_keeps_the_chosen_motion(self):
        scene = apply_asset_strategy(self._scene(), "stock_image")
        assert (scene.asset_tier, scene.motion_effect) == ("still_motion", "pan_left")

    def test_upload_leaves_the_contract_alone(self):
        scene = apply_asset_strategy(self._scene(), "upload")
        assert (scene.asset_tier, scene.clip_type, scene.motion_effect) == ("still_motion", "still_with_motion", "pan_left")
        assert scene.asset_strategy == "upload"


# ── PATCH + GET ───────────────────────────────────────────────────────────────


class TestPatchAndGet:
    def test_get_returns_effective_strategy_for_every_scene(self):
        with p13_env(**{"3": {"asset_tier": "video", "clip_type": "hard_cut", "motion_effect": None}}) as env:
            scenes = env.scenes()

            assert [s["asset_strategy"] for s in scenes] == [None, None, None]
            assert [s["effective_asset_strategy"] for s in scenes] == ["stock_image", "stock_image", "stock_video"]

    @pytest.mark.parametrize("strategy", ASSET_STRATEGIES)
    def test_every_strategy_is_accepted(self, strategy):
        with p13_env() as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": strategy})

            assert r.status_code == 200, r.text
            scene = env.scenes()[1]
            assert scene["asset_strategy"] == strategy
            assert scene["effective_asset_strategy"] == strategy
            assert env.versions("storyboard", "verified_storyboard") == 2

    def test_unknown_strategy_is_rejected(self):
        with p13_env() as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "ai_image"})

            assert r.status_code == 422
            assert "ai_image" in r.json()["detail"]
            assert env.versions("storyboard", "verified_storyboard") == 1

    def test_image_to_video_and_back_resets_motion(self):
        with p13_env(**{"2": {"motion_effect": "pan_right"}}) as env:
            env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_video"})
            video = env.scenes()[1]
            assert (video["asset_tier"], video["clip_type"], video["motion_effect"]) == ("video", "hard_cut", None)

            env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_image"})
            still = env.scenes()[1]
            assert (still["asset_tier"], still["clip_type"], still["motion_effect"]) == ("still", "still_with_motion", "ken_burns")

    def test_other_scenes_are_untouched(self):
        with p13_env() as env:
            before = env.scenes()
            env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_video"})
            after = env.scenes()

            assert after[0] == before[0] and after[2] == before[2]

    def test_asset_strategy_is_in_patchable_fields(self):
        import inspect

        from cf_platform.workers.storyboard_worker import _apply_patches_and_render_options

        assert '"asset_strategy"' in inspect.getsource(_apply_patches_and_render_options)

    def test_no_manifest_means_no_manifest_write(self):
        with p13_env() as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_video"})

            assert "needs_acquisition" not in r.json()
            assert env.versions("acquisition", "asset_manifest") == 0


class TestPatchAfterAcquisition:
    def test_changing_kind_releases_the_asset(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_video"})

            assert r.json()["needs_acquisition"] == ["2"]
            entry = env.manifest_entries()[1]
            assert (entry["status"], entry["file_key"], entry["asset_strategy"]) == ("pending", None, "stock_video")
            assert (entry["asset_tier"], entry["clip_type"]) == ("video", "hard_cut")

    def test_same_kind_keeps_the_asset(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "stock_image"})

            assert r.json()["needs_acquisition"] == []
            assert env.manifest_entries()[1]["file_key"] == f"runs/{RUN_ID}/images/2.jpg"

    def test_switching_to_upload_awaits_a_file(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "upload"})

            assert r.json()["needs_acquisition"] == ["2"]
            assert env.manifest_entries()[1]["status"] == "awaiting_upload"


# ── Acquisition routing ───────────────────────────────────────────────────────


def _entry(**fields) -> ManifestEntry:
    """Return a manifest entry for a 4s B-roll still, overridable."""
    base = {
        "scene_id": "1", "clip_type": "still_with_motion", "asset_tier": "still_motion",
        "primary_stk": "a", "context_stk": "b", "concept_stk": "c", "duration_s": 4.0,
    }
    return ManifestEntry(**{**base, **fields})


class TestAcquisitionRouting:
    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({"asset_strategy": "stock_video"}, True),                                   # forced over a still tier
            ({"asset_strategy": "stock_image", "asset_tier": "video", "clip_type": "hard_cut"}, False),
            ({"asset_tier": "video"}, True),                                             # derived, as before
            ({}, False),
            ({"asset_tier": None, "clip_type": "hard_cut"}, True),                       # legacy fallback
        ],
    )
    def test_wants_video(self, fields, expected):
        assert _wants_video(_entry(**fields)) is expected

    async def _route(self, acquire, entry: ManifestEntry) -> dict[str, AsyncMock]:
        """Run one acquisition function with every source route mocked; return the mocks."""
        with (
            patch(f"{_WORKER}._acquire_broll", new_callable=AsyncMock, return_value=True) as broll,
            patch(f"{_WORKER}._acquire_character", new_callable=AsyncMock, return_value=True) as character,
            patch(f"{_WORKER}._acquire_event", new_callable=AsyncMock, return_value=True) as event,
        ):
            if acquire is _acquire_scene:
                await _acquire_scene(entry, RUN_ID, None, None, None, None)
            else:
                await _acquire_single_scene(None, entry, None, None, None, None, RUN_ID)
        return {"broll": broll, "character": character, "event": event}

    @pytest.mark.parametrize("acquire", [_acquire_scene, _acquire_single_scene])
    @pytest.mark.parametrize(
        "fields",
        [{}, {"segment_type": "Character", "person_name": "Jane Jacobs"}, {"segment_type": "Event"}],
    )
    def test_stock_video_always_takes_the_video_search(self, acquire, fields):
        mocks = asyncio.run(self._route(acquire, _entry(asset_strategy="stock_video", **fields)))

        mocks["broll"].assert_awaited_once()
        assert mocks["broll"].await_args.args[2] is True  # is_video
        mocks["character"].assert_not_awaited()
        mocks["event"].assert_not_awaited()

    @pytest.mark.parametrize("acquire", [_acquire_scene, _acquire_single_scene])
    def test_stock_image_forces_the_photo_search_on_a_video_tier(self, acquire):
        entry = _entry(asset_strategy="stock_image", asset_tier="video", clip_type="hard_cut")
        mocks = asyncio.run(self._route(acquire, entry))

        assert mocks["broll"].await_args.args[2] is False

    @pytest.mark.parametrize("acquire", [_acquire_scene, _acquire_single_scene])
    def test_stock_image_keeps_the_character_route(self, acquire):
        entry = _entry(asset_strategy="stock_image", segment_type="Character", person_name="Jane Jacobs")
        mocks = asyncio.run(self._route(acquire, entry))

        mocks["character"].assert_awaited_once()
        mocks["broll"].assert_not_awaited()


# ── AcquisitionWorker ─────────────────────────────────────────────────────────


async def _run_worker(storyboard, prior_manifest=None, only_missing=False):
    """Run the AcquisitionWorker with _acquire_scene mocked; return (artifact, fetched ids, storage)."""
    from cf_platform.core.artifact_manager import InMemoryArtifactStorage

    storage = InMemoryArtifactStorage()
    artifacts = {"verified_storyboard": await seed_storyboard(storage, storyboard)}
    if prior_manifest is not None:
        artifacts["asset_manifest"] = await seed_manifest(storage, prior_manifest)

    fetched: list[ManifestEntry] = []

    async def fake_acquire(entry, run_id, *args, **kwargs):
        """Mark the entry acquired the way a successful stock search does."""
        fetched.append(entry.model_copy())
        stem = entry.asset_slot or entry.scene_id
        entry.status, entry.source, entry.qa_passed = "acquired", "pexels", True
        entry.file_key = f"runs/{run_id}/images/{stem}.jpg"

    with patch(f"{_WORKER}._acquire_scene", side_effect=fake_acquire):
        worker = build_acquisition_worker(storage, pexels_api_key="k")
        state = StageState(
            run_id=RUN_ID, user_id="operator", inputs={"only_missing": only_missing}, artifacts=artifacts,
        )
        output = await worker(state)
    return output.artifact, fetched, storage


class TestWorker:
    def test_upload_scene_is_skipped_and_reported(self):
        storyboard = make_storyboard(make_words(), **{"2": {"asset_strategy": "upload"}})

        artifact, fetched, storage = asyncio.run(_run_worker(storyboard))

        assert [e.scene_id for e in fetched] == ["1", "3"]
        entries = artifact.manifest["entries"]
        assert entries[1]["status"] == "awaiting_upload" and entries[1]["file_key"] is None
        assert artifact.footage_summary["awaiting_upload"] == 1
        assert (artifact.acquired, artifact.failed) == (2, 0)  # awaiting is not a failure
        assert storage._objects[f"runs/{RUN_ID}/footage_summary.json"]["awaiting_upload"] == 1

    def test_uploaded_file_survives_a_full_reacquire(self):
        storyboard = make_storyboard(make_words(), **{"2": {"asset_strategy": "upload"}})
        prior = make_manifest(storyboard)
        prior.entries[1].source = "operator_upload"
        prior.entries[1].file_key = f"runs/{RUN_ID}/images/scene_02_op.jpg"

        artifact, fetched, _ = asyncio.run(_run_worker(storyboard, prior))

        assert [e.scene_id for e in fetched] == ["1", "3"]
        kept = artifact.manifest["entries"][1]
        assert (kept["status"], kept["source"], kept["file_key"]) == (
            "acquired", "operator_upload", f"runs/{RUN_ID}/images/scene_02_op.jpg",
        )
        assert "awaiting_upload" not in artifact.footage_summary

    def test_only_missing_fetches_only_scenes_without_an_asset(self):
        storyboard = make_storyboard(make_words())
        prior = make_manifest(storyboard)
        prior.entries[1] = manifest_entry_for_scene(storyboard.scenes[1])  # pending, e.g. a split's second half

        artifact, fetched, _ = asyncio.run(_run_worker(storyboard, prior, only_missing=True))

        assert [e.scene_id for e in fetched] == ["2"]
        assert [e["status"] for e in artifact.manifest["entries"]] == ["acquired"] * 3
        assert artifact.manifest["entries"][0]["file_key"] == f"runs/{RUN_ID}/images/1.jpg"

    def test_without_only_missing_everything_is_fetched_again(self):
        storyboard = make_storyboard(make_words())

        _, fetched, _ = asyncio.run(_run_worker(storyboard, make_manifest(storyboard)))

        assert [e.scene_id for e in fetched] == ["1", "2", "3"]

    def test_fetch_never_writes_over_a_kept_scenes_file(self):
        # After a merge + split the scene now called "2" still uses 3.jpg, and the
        # new scene "3" must not be saved under that name.
        storyboard = make_storyboard(make_words())
        prior = make_manifest(storyboard)
        prior.entries[1].file_key = f"runs/{RUN_ID}/images/3.jpg"
        prior.entries[2] = manifest_entry_for_scene(storyboard.scenes[2])

        artifact, fetched, _ = asyncio.run(_run_worker(storyboard, prior, only_missing=True))

        assert [(e.scene_id, e.asset_slot) for e in fetched] == [("3", "scene_w8")]
        keys = [e["file_key"] for e in artifact.manifest["entries"]]
        assert len(set(keys)) == 3
        assert keys[2] == f"runs/{RUN_ID}/images/scene_w8.jpg"

    def test_emptied_manifest_after_regeneration_is_ignored(self):
        from cf_platform.core.artifact_manager import InMemoryArtifactStorage

        async def _go():
            """Run the worker against a manifest key that holds the emptied placeholder."""
            storage = InMemoryArtifactStorage()
            storyboard = make_storyboard(make_words())
            sb_key = await seed_storyboard(storage, storyboard)
            await storage.put_json("stale", {"run_id": RUN_ID, "entries": []})
            with patch(f"{_WORKER}._acquire_scene", new_callable=AsyncMock) as acquire:
                worker = build_acquisition_worker(storage, pexels_api_key="k")
                await worker(StageState(
                    run_id=RUN_ID, user_id="operator", inputs={"only_missing": True},
                    artifacts={"verified_storyboard": sb_key, "asset_manifest": "stale"},
                ))
            return acquire.await_count

        assert asyncio.run(_go()) == 3


# ── Render gate ───────────────────────────────────────────────────────────────


class TestRenderGate:
    def test_all_scenes_have_files(self):
        storyboard = make_storyboard(make_words())
        assert missing_assets_message(storyboard, make_manifest(storyboard)) is None

    def test_upload_scene_without_a_file_blocks_with_a_clear_message(self):
        storyboard = make_storyboard(make_words(), **{"2": {"asset_strategy": "upload"}})
        manifest = make_manifest(storyboard)
        manifest.entries[1].status, manifest.entries[1].file_key = "awaiting_upload", None

        message = missing_assets_message(storyboard, manifest)

        assert "Scene(s) 2 are set to Upload and have no file yet" in message

    def test_scene_without_any_asset_blocks_too(self):
        storyboard = make_storyboard(make_words())
        manifest = make_manifest(storyboard)
        manifest.entries[2] = manifest_entry_for_scene(storyboard.scenes[2])

        assert "Scene(s) 3 have no asset" in missing_assets_message(storyboard, manifest)

    def test_render_endpoint_refuses_with_409(self):
        with p13_env(with_manifest=True) as env:
            env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "upload"})

            r = env.client.post("/platform/workers/render", json={"run_id": RUN_ID})

            assert r.status_code == 409
            assert "Upload" in r.json()["detail"]

    def test_render_worker_refuses_before_any_ffmpeg_work(self):
        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.workers.render_worker import build_render_worker

        async def _go():
            """Run the RenderWorker on a run whose upload scene has no file."""
            storage = InMemoryArtifactStorage()
            storyboard = make_storyboard(make_words(), **{"2": {"asset_strategy": "upload"}})
            manifest = make_manifest(storyboard)
            manifest.entries[1].status, manifest.entries[1].file_key = "awaiting_upload", None
            state = StageState(run_id=RUN_ID, user_id="operator", inputs={}, artifacts={
                "verified_storyboard": await seed_storyboard(storage, storyboard),
                "asset_manifest": await seed_manifest(storage, manifest),
            })
            await build_render_worker(storage)(state)

        with pytest.raises(RuntimeError, match="set to Upload and have no file yet"):
            asyncio.run(_go())


# ── Upload before acquisition ─────────────────────────────────────────────────


class TestUploadBeforeAcquisition:
    def _upload(self, env, scene: str, data: bytes = b"jpeg-bytes"):
        """POST a JPEG to the per-scene upload endpoint."""
        return env.client.post(
            f"/platform/studio/runs/{RUN_ID}/scenes/{scene}/upload",
            files={"file": ("pic.jpg", data, "image/jpeg")},
        )

    def test_upload_starts_a_manifest_from_the_storyboard(self):
        with p13_env() as env:
            env.client.patch(f"{_SCENE_URL}/2", json={"asset_strategy": "upload"})
            env.client.patch(f"{_SCENE_URL}/3", json={"asset_strategy": "upload"})

            r = self._upload(env, "2")

            assert r.status_code == 200, r.text
            entries = env.manifest_entries()
            assert [e["status"] for e in entries] == ["pending", "acquired", "awaiting_upload"]
            assert entries[1]["source"] == "operator_upload"
            assert entries[1]["file_key"] == f"runs/{RUN_ID}/images/scene_02_op.jpg"

    def test_upload_never_replaces_another_scenes_upload(self):
        with p13_env(with_manifest=True) as env:
            self._upload(env, "2", b"first")
            # Splitting scene 1 renumbers: the uploaded scene becomes "3", and the new "2" uploads too.
            env.client.post(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/1/split", json={"at_word": 2})
            self._upload(env, "2", b"second")

            entries = env.manifest_entries()
            assert entries[2]["file_key"] == f"runs/{RUN_ID}/images/scene_02_op.jpg"
            assert entries[1]["file_key"] != entries[2]["file_key"]
            assert env.storage._bytes[entries[2]["file_key"]] == b"first"
            assert env.storage._bytes[entries[1]["file_key"]] == b"second"


# ── No regression without asset_strategy ──────────────────────────────────────


class TestLegacyUnchanged:
    def test_manifest_entry_matches_the_pre_p13_constructor(self):
        scene = make_storyboard(make_words()).scenes[0]
        before = ManifestEntry(
            scene_id=scene.scene, clip_type=scene.clip_type, segment_type=scene.segment_type,
            primary_stk=scene.primary_stk, context_stk=scene.context_stk, concept_stk=scene.concept_stk,
            person_name=scene.person_name, person_title=scene.person_title, duration_s=scene.duration_s,
            historic=scene.historic, asset_tier=scene.asset_tier, semantic_context=scene.semantic_context,
        )
        assert manifest_entry_for_scene(scene) == before

    def test_worker_fetches_every_scene_in_order_with_no_slots(self):
        storyboard = make_storyboard(make_words())

        artifact, fetched, _ = asyncio.run(_run_worker(storyboard))

        assert [e.scene_id for e in fetched] == ["1", "2", "3"]
        assert all(e.asset_strategy is None and e.asset_slot is None and e.status == "pending" for e in fetched)
        assert [e["file_key"] for e in artifact.manifest["entries"]] == [
            f"runs/{RUN_ID}/images/{n}.jpg" for n in "123"
        ]

    def test_footage_summary_keys_unchanged(self):
        entries = make_manifest(make_storyboard(make_words())).entries
        assert set(_compute_footage_summary(entries)) == {
            "pexels", "pixabay", "wikimedia", "wikimedia_person", "failed", "qa_failed_scenes",
        }

    def test_render_script_is_byte_identical_for_a_pre_p13_storyboard(self):
        from cf_platform.workers.render_worker import _build_render_script
        from src.models import Storyboard

        storyboard = make_storyboard(make_words())
        manifest = make_manifest(storyboard)
        # A stored pre-P13 artifact has no asset_strategy key and its entries no P13 fields.
        old_json = storyboard.model_dump(by_alias=True, mode="json")
        for scene in old_json["scenes"]:
            del scene["asset_strategy"]
        old_storyboard = Storyboard.model_validate(old_json)

        def _script(sb) -> str:
            """Build the render script for one storyboard against the same manifest."""
            return _build_render_script(RUN_ID, sb, manifest, None, "neutral", True)

        assert _script(old_storyboard) == _script(storyboard)
        # Recording the strategy the scene already had changes nothing in the render.
        explicit = storyboard.model_copy(update={
            "scenes": [apply_asset_strategy(s, "stock_image") for s in storyboard.scenes],
        })
        assert _script(explicit) == _script(storyboard)
