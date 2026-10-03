"""Tests for P13-S2: split and merge scenes.

Covers:
- split / merge happy paths through the REST endpoints
- boundary validation (422), merging the last scene (409), unknown scene (404)
- contiguity, renumbering and timing after a sequence of splits and merges
- what each half keeps: fields, on-screen text, SFX
- manifest alignment with and without acquired assets
- the minimum scene duration
- file names never collide after renumbering
"""

import pytest

from cf_platform.workers.acquisition_worker import asset_file_stem, assign_free_asset_slot
from cf_platform.workers.storyboard_edit import (
    LastSceneMergeError,
    StoryboardEditError,
    merge_scene,
    split_scene,
)
from src.models import ManifestEntry
from tests.cf_platform.p13_helpers import (
    N_WORDS,
    RUN_ID,
    make_manifest,
    make_storyboard,
    make_words,
    p13_env,
)

_BASE = f"/platform/studio/runs/{RUN_ID}/storyboard"


def _assert_contiguous(scenes: list[dict]) -> None:
    """Assert the scenes cover every word exactly once and are numbered in order."""
    assert scenes[0]["start_word"] == 0
    assert scenes[-1]["end_word"] == N_WORDS - 1
    for i, scene in enumerate(scenes):
        assert scene["scene"] == str(i + 1)
        if i:
            assert scene["start_word"] == scenes[i - 1]["end_word"] + 1


# ── Split ─────────────────────────────────────────────────────────────────────


class TestSplit:
    def test_split_makes_two_scenes_at_the_word(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})

            assert r.status_code == 200, r.text
            scenes = r.json()["storyboard"]["scenes"]
            assert [(s["scene"], s["start_word"], s["end_word"]) for s in scenes] == [
                ("1", 0, 3), ("2", 4, 5), ("3", 6, 7), ("4", 8, 11),
            ]
            assert r.json()["scene_count"] == 4
            assert env.scenes() == scenes  # the response is what a GET now returns

    def test_timing_is_recomputed_from_word_timestamps(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})

            first, second = r.json()["storyboard"]["scenes"][1:3]
            assert first["voiceover_line"] == "w4 w5"
            assert (first["scene_start_ms"], first["scene_end_ms"], first["duration_s"]) == (2000, 3000, 1.0)
            assert second["voiceover_line"] == "w6 w7"
            assert (second["scene_start_ms"], second["scene_end_ms"], second["duration_s"]) == (3000, 4000, 1.0)
            assert second["asset_tier"] == "still"  # same tier policy as the StoryboardWorker

    def test_first_half_keeps_fields_second_half_starts_clean(self):
        overrides = {"2": {
            "on_screen_text": "40%", "on_screen_text_type": "stat", "sfx": "whoosh",
            "motion_effect": "pan_left", "asset_strategy": "stock_image",
        }}
        with p13_env(**overrides) as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})

            first, second = r.json()["storyboard"]["scenes"][1:3]
            assert first["on_screen_text"] == "40%" and first["sfx"] == "whoosh"
            assert first["motion_effect"] == "pan_left"
            assert first["render_options"]["on_screen_text_overlay"]["text"] == "40%"
            # Visual fields are copied …
            assert second["primary_stk"] == "query 2" and second["segment_type"] == "B-roll"
            assert second["asset_strategy"] == "stock_image"
            # … on-screen text and SFX are not.
            assert second["on_screen_text"] is None and second["sfx"] == ""
            assert second["render_options"] is None

    def test_overlay_timing_of_later_scenes_follows_the_new_scenes(self):
        overrides = {"3": {"on_screen_text": "7%", "on_screen_text_type": "stat"}}
        with p13_env(**overrides) as env:
            r = env.client.post(f"{_BASE}/scenes/1/split", json={"at_word": 2})

            last = r.json()["storyboard"]["scenes"][-1]
            assert last["scene"] == "4"
            assert last["render_options"]["on_screen_text_overlay"]["enable_expr"] == "between(t,4.000,6.000)"

    @pytest.mark.parametrize("at_word", [4, 3, 8, 99, -1])
    def test_split_point_outside_the_scene_is_rejected(self, at_word):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": at_word})

            assert r.status_code == 422
            assert env.versions("storyboard", "verified_storyboard") == 1  # nothing written

    def test_split_shorter_than_minimum_is_rejected_with_a_clear_message(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 5})  # first half = 0.5s

            assert r.status_code == 422
            assert "shorter than the 1s minimum" in r.json()["detail"]

    def test_unknown_scene_is_404(self):
        with p13_env() as env:
            assert env.client.post(f"{_BASE}/scenes/9/split", json={"at_word": 6}).status_code == 404

    def test_no_voiceover_is_409(self):
        with p13_env(with_voice=False) as env:
            assert env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6}).status_code == 409

    def test_voiceover_text_cannot_be_sent(self):
        # The request models carry only word indices — there is no field for text.
        from cf_platform.interfaces.routes.studio import SceneSplitRequest

        assert set(SceneSplitRequest.model_fields) == {"at_word"}


# ── Merge ─────────────────────────────────────────────────────────────────────


class TestMerge:
    def test_merge_joins_a_scene_with_the_next(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/1/merge")

            assert r.status_code == 200, r.text
            scenes = r.json()["storyboard"]["scenes"]
            assert [(s["scene"], s["start_word"], s["end_word"]) for s in scenes] == [("1", 0, 7), ("2", 8, 11)]
            assert scenes[0]["voiceover_line"] == "w0 w1 w2 w3 w4 w5 w6 w7"
            assert scenes[0]["duration_s"] == 4.0
            assert scenes[0]["asset_tier"] == "still_motion"  # 4s → recomputed tier

    def test_first_scene_wins_and_dropped_text_is_reported(self):
        overrides = {
            "1": {"on_screen_text": "Peak year", "on_screen_text_type": "date", "sfx": "ding"},
            "2": {"on_screen_text": "40%", "on_screen_text_type": "stat", "sfx": "whoosh"},
        }
        with p13_env(**overrides) as env:
            r = env.client.post(f"{_BASE}/scenes/1/merge")

            merged = r.json()["storyboard"]["scenes"][0]
            assert merged["on_screen_text"] == "Peak year" and merged["sfx"] == "ding"
            assert merged["primary_stk"] == "query 1"
            assert r.json()["dropped"] == [{"scene": "2", "on_screen_text": "40%", "sfx": "whoosh"}]
            assert "dropped" in r.json()["summary"]

    def test_nothing_dropped_when_second_scene_has_no_text_or_sfx(self):
        with p13_env(**{"2": {"sfx": "silence"}}) as env:
            assert env.client.post(f"{_BASE}/scenes/1/merge").json()["dropped"] == []

    def test_last_scene_cannot_be_merged(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/3/merge")

            assert r.status_code == 409
            assert env.versions("storyboard", "verified_storyboard") == 1

    def test_unknown_scene_is_404(self):
        with p13_env() as env:
            assert env.client.post(f"{_BASE}/scenes/9/merge").status_code == 404


# ── Sequences ─────────────────────────────────────────────────────────────────


class TestSequences:
    def test_storyboard_stays_contiguous_through_splits_and_merges(self):
        with p13_env() as env:
            for path, body in [
                ("scenes/1/split", {"at_word": 2}),
                ("scenes/4/split", {"at_word": 10}),
                ("scenes/2/merge", None),
                ("scenes/1/merge", None),
                ("scenes/1/split", {"at_word": 3}),
            ]:
                r = env.client.post(f"{_BASE}/{path}", json=body)
                assert r.status_code == 200, r.text
                scenes = r.json()["storyboard"]["scenes"]
                _assert_contiguous(scenes)
                for scene in scenes:
                    span = env.words[scene["start_word"] : scene["end_word"] + 1]
                    assert scene["voiceover_line"] == " ".join(w.word for w in span)
                    assert scene["scene_start_ms"] == span[0].start_ms
                    assert scene["scene_end_ms"] == span[-1].end_ms

            summary = env.storyboard()["summary"]
            assert summary["total_scenes"] == len(env.scenes())
            assert summary["total_duration_s"] == 6.0
            assert env.versions("storyboard", "verified_storyboard") == 6  # one new version per edit

    def test_split_then_merge_restores_the_original_scene(self):
        overrides = {"2": {"on_screen_text": "40%", "on_screen_text_type": "stat", "motion_effect": "zoom_in"}}
        with p13_env(**overrides) as env:
            before = env.scenes()
            env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})
            env.client.post(f"{_BASE}/scenes/2/merge")

            assert env.scenes() == before


# ── Manifest alignment ────────────────────────────────────────────────────────


class TestManifestAlignment:
    def test_no_manifest_before_acquisition(self):
        with p13_env() as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})

            assert r.json()["needs_acquisition"] is None
            assert "manifest_key" not in r.json()
            assert env.versions("acquisition", "asset_manifest") == 0

    def test_split_first_half_keeps_asset_second_needs_one(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.post(f"{_BASE}/scenes/2/split", json={"at_word": 6})

            assert r.json()["needs_acquisition"] == ["3"]
            entries = env.manifest_entries()
            assert [e["scene_id"] for e in entries] == ["1", "2", "3", "4"]
            assert [e["status"] for e in entries] == ["acquired", "acquired", "pending", "acquired"]
            # Assets stay with their scene even though the ids moved.
            assert entries[1]["file_key"] == f"runs/{RUN_ID}/images/2.jpg"
            assert entries[2]["file_key"] is None
            assert entries[3]["file_key"] == f"runs/{RUN_ID}/images/3.jpg"
            assert entries[2]["primary_stk"] == "query 2"
            assert entries[1]["duration_s"] == 1.0  # entry follows the scene's new length

    def test_merge_keeps_first_asset_and_removes_second_entry(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.post(f"{_BASE}/scenes/1/merge")

            assert r.json()["needs_acquisition"] == []
            entries = env.manifest_entries()
            assert [(e["scene_id"], e["file_key"]) for e in entries] == [
                ("1", f"runs/{RUN_ID}/images/1.jpg"),
                ("2", f"runs/{RUN_ID}/images/3.jpg"),
            ]

    def test_manifest_always_has_one_entry_per_scene_in_order(self):
        with p13_env(with_manifest=True) as env:
            for path, body in [
                ("scenes/3/split", {"at_word": 10}),
                ("scenes/1/merge", None),
                ("scenes/1/split", {"at_word": 4}),
            ]:
                assert env.client.post(f"{_BASE}/{path}", json=body).status_code == 200
                assert [e["scene_id"] for e in env.manifest_entries()] == [s["scene"] for s in env.scenes()]

    def test_kept_video_asset_keeps_the_scene_rendering_as_video(self):
        words = make_words()
        storyboard = make_storyboard(words)
        manifest = make_manifest(storyboard, ext=".mp4")

        edit = split_scene(storyboard, words, "2", 6, manifest, min_scene_s=1.0)

        first, second = edit.storyboard.scenes[1:3]
        assert (first.asset_tier, first.clip_type, first.motion_effect) == ("video", "hard_cut", None)
        assert second.asset_tier == "still"  # no asset yet → duration-derived

    def test_split_of_upload_scene_awaits_upload(self):
        words = make_words()
        storyboard = make_storyboard(words, **{"2": {"asset_strategy": "upload"}})
        manifest = make_manifest(storyboard)

        edit = split_scene(storyboard, words, "2", 6, manifest)

        assert edit.manifest.entries[2].status == "awaiting_upload"


# ── File names after renumbering ──────────────────────────────────────────────


class TestAssetSlots:
    def test_slot_assigned_only_when_the_default_name_is_taken(self):
        free = ManifestEntry(scene_id="4", clip_type="still_with_motion")
        assign_free_asset_slot(free, {"1", "2"}, start_word=8)
        assert free.asset_slot is None

        taken = ManifestEntry(scene_id="3", clip_type="still_with_motion")
        assign_free_asset_slot(taken, {"1", "2", "3"}, start_word=6)
        assert taken.asset_slot == "scene_w6"

    def test_slot_never_lands_on_a_taken_name(self):
        entry = ManifestEntry(scene_id="3", clip_type="still_with_motion")
        assign_free_asset_slot(entry, {"3", "scene_w6"}, start_word=6)
        assert entry.asset_slot not in {"3", "scene_w6"}

    def test_stem_of_an_asset_key(self):
        assert asset_file_stem("runs/r/images/3.jpg") == "3"
        assert asset_file_stem("runs/r/video/scene_05_op.mp4") == "scene_05_op"
        assert asset_file_stem(None) is None


# ── Pure-function errors ──────────────────────────────────────────────────────


class TestEditErrors:
    def test_storyboard_without_word_indices_cannot_be_edited(self):
        words = make_words()
        storyboard = make_storyboard(words)
        legacy = storyboard.model_copy(update={
            "scenes": [s.model_copy(update={"start_word": None, "end_word": None}) for s in storyboard.scenes],
        })

        with pytest.raises(StoryboardEditError, match="no word boundaries"):
            split_scene(legacy, words, "2", 6)

    def test_merge_last_scene_raises(self):
        words = make_words()
        with pytest.raises(LastSceneMergeError):
            merge_scene(make_storyboard(words), words, "3")

    def test_unchanged_short_scene_does_not_block_an_edit_elsewhere(self):
        # Scene 1 is 0.5s — below the minimum — but it is not the scene being edited.
        words = make_words()
        storyboard = make_storyboard(words, starts=(0, 1, 6))

        edit = split_scene(storyboard, words, "3", 9, min_scene_s=1.0)

        assert edit.scenes_after == 4
