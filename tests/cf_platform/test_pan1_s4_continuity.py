"""Tests for P-AN1-S4: the editable continuity bible, scene patches and split / merge in Animation mode."""

import asyncio

import pytest

from cf_platform.workers.continuity_edit import (
    ContinuityEditError,
    ContinuityEntryInUseError,
    ContinuityEntryNotFoundError,
    add_entry,
    edit_entry,
    remove_entry,
    scenes_using,
    set_scene_entities,
)
from cf_platform.workers.storyboard_edit import merge_scene, split_scene
from src.models import AI_GENERATED_SOURCE, AssetManifest
from tests.cf_platform.p13_helpers import RUN_ID, make_manifest, make_storyboard, make_words
from tests.cf_platform.pan1_helpers import animation_env, animation_storyboard

_SB = f"/platform/studio/runs/{RUN_ID}/storyboard"
WORDS = make_words()


def _storyboard(**overrides):
    """An Animation storyboard of three scenes; scene 1 uses the learner."""
    return animation_storyboard(make_storyboard(WORDS), **overrides)


def _manifest(storyboard, with_images_for: tuple[str, ...]) -> AssetManifest:
    """A manifest in which the named scenes hold a generated image."""
    manifest = make_manifest(storyboard, acquired=False)
    for entry in manifest.entries:
        if entry.scene_id in with_images_for:
            entry.status, entry.source, entry.file_key = "acquired", AI_GENERATED_SOURCE, f"img/{entry.scene_id}.png"
    return manifest


class TestEditEntry:
    def test_a_new_description_flags_only_scenes_that_use_it_and_have_an_image(self):
        sb = _storyboard(**{"2": {"entities": ["learner"]}, "3": {"entities": ["teal_book"]}})
        edited, stale = edit_entry(sb, _manifest(sb, ("1", "3")), "learner", description="a student in a red coat")
        assert stale == ["1"]  # scene 2 uses it but has no image; scene 3 has one but does not use it
        assert edited.scenes[0].flags == ["image_out_of_date"] and edited.scenes[1].flags == []
        assert edited.continuity[0].description == "a student in a red coat"
        assert sb.continuity[0].description != "a student in a red coat"  # the input is not mutated

    def test_the_same_text_or_a_kind_change_flags_nothing(self):
        sb = _storyboard()
        manifest = _manifest(sb, ("1",))
        _, stale = edit_entry(sb, manifest, "learner", description=sb.continuity[0].description, kind="prop")
        assert stale == []

    def test_a_scene_is_not_flagged_twice(self):
        sb = _storyboard(**{"1": {"flags": ["image_out_of_date"]}})
        edited, _ = edit_entry(sb, _manifest(sb, ("1",)), "learner", description="new")
        assert edited.scenes[0].flags == ["image_out_of_date"]

    def test_empty_name_or_description_bad_kind_and_unknown_id_are_refused(self):
        sb = _storyboard()
        for kwargs in ({"name": " "}, {"description": ""}, {"kind": "vehicle"}):
            with pytest.raises(ContinuityEditError):
                edit_entry(sb, None, "learner", **kwargs)
        with pytest.raises(ContinuityEntryNotFoundError):
            edit_entry(sb, None, "ghost", description="x")


class TestAddRemove:
    def test_add_derives_a_unique_id_from_the_name(self):
        sb, entry = add_entry(_storyboard(), kind="prop", name="The Learner", description="a second one")
        assert entry.id == "the_learner"
        sb, again = add_entry(sb, kind="prop", name="The learner!", description="a third")
        assert again.id == "the_learner_2" and len(sb.continuity) == 4

    def test_add_needs_a_name_a_description_and_a_known_kind(self):
        for kwargs in ({"kind": "prop", "name": "", "description": "x"}, {"kind": "prop", "name": "x", "description": " "},
                       {"kind": "vehicle", "name": "x", "description": "x"}):
            with pytest.raises(ContinuityEditError):
                add_entry(_storyboard(), **kwargs)

    def test_an_unused_entry_can_be_removed_a_used_one_cannot(self):
        sb = _storyboard()
        assert scenes_using(sb, "learner") == ["1"] and scenes_using(sb, "teal_book") == []
        assert [e.id for e in remove_entry(sb, "teal_book").continuity] == ["learner"]
        with pytest.raises(ContinuityEntryInUseError, match="Scene 1"):
            remove_entry(sb, "learner")
        with pytest.raises(ContinuityEntryNotFoundError):
            remove_entry(sb, "ghost")


class TestSceneEntities:
    def test_setting_entities_flags_a_scene_that_has_an_image(self):
        sb = _storyboard()
        edited, stale = set_scene_entities(sb, _manifest(sb, ("2",)), "2", ["teal_book", "teal_book"])
        assert stale and edited.scenes[1].entities == ["teal_book"] and edited.scenes[1].flags == ["image_out_of_date"]

    def test_no_change_or_no_image_flags_nothing_and_unknown_ids_are_refused(self):
        sb = _storyboard()
        assert set_scene_entities(sb, _manifest(sb, ("1",)), "1", ["learner"])[1] is False
        assert set_scene_entities(sb, None, "2", ["learner"])[1] is False
        with pytest.raises(ContinuityEntryNotFoundError):
            set_scene_entities(sb, None, "2", ["ghost"])


class TestSplitMerge:
    def test_the_second_half_of_a_split_keeps_the_entities_has_no_prompt_and_is_flagged(self):
        sb = _storyboard()
        edit = split_scene(sb, WORDS, "1", 2)
        first, second = edit.storyboard.scenes[0], edit.storyboard.scenes[1]
        assert first.ai_prompt == "prompt 1" and first.flags == []
        assert second.ai_prompt is None and second.flags == ["needs_prompt"]
        assert second.entities == ["learner"] and second.asset_strategy == "ai_image"
        assert second.visual_concept == ""  # the concept belonged to the scene it was cut from

    def test_a_merge_keeps_the_first_scenes_prompt_and_flags_a_scene_that_became_too_long(self):
        long_words = make_words(12, 1000)  # each scene 4 s; merged 8 s
        sb = animation_storyboard(make_storyboard(long_words))
        edit = merge_scene(sb, long_words, "1")
        merged = edit.storyboard.scenes[0]
        assert merged.ai_prompt == "prompt 1" and merged.entities == ["learner"]
        assert merged.duration_s == 8.0 and merged.flags == ["too_long"]
        assert len(edit.storyboard.scenes) == 2

    def test_a_stock_storyboard_split_gets_no_animation_flags(self):
        edit = split_scene(make_storyboard(WORDS), WORDS, "1", 2)
        assert all(s.flags == [] and s.entities == [] for s in edit.storyboard.scenes)


class TestRoutes:
    def test_editing_a_description_returns_the_scenes_it_put_out_of_date(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1", "2")) as env:
            r = env.client.patch(f"{_SB}/continuity/learner", json={"description": "a student in a red coat"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["newly_out_of_date"] == ["1"] and body["out_of_date"] == ["1"]
            assert body["storyboard"]["continuity"][0]["description"] == "a student in a red coat"
            assert env.scenes()[0]["flags"] == ["image_out_of_date"]
            assert env.scenes()[0]["effective_asset_strategy"] == "ai_image"

    def test_add_then_remove_an_entry(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            r = env.client.post(f"{_SB}/continuity", json={"kind": "setting", "name": "The Hall", "description": "a sunlit hall"})
            assert r.status_code == 200 and r.json()["entry_id"] == "the_hall"
            assert [e["id"] for e in env.storyboard()["continuity"]] == ["learner", "teal_book", "the_hall"]
            assert env.client.delete(f"{_SB}/continuity/the_hall").status_code == 200
            assert len(env.storyboard()["continuity"]) == 2

    def test_errors_map_to_404_409_and_422(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            assert env.client.patch(f"{_SB}/continuity/ghost", json={"description": "x"}).status_code == 404
            r = env.client.delete(f"{_SB}/continuity/learner")
            assert r.status_code == 409 and "Scene 1" in r.json()["detail"]
            assert env.client.post(f"{_SB}/continuity", json={"kind": "prop", "name": "x", "description": " "}).status_code == 422

    def test_a_stock_storyboard_has_no_bible(self, monkeypatch):
        from tests.cf_platform.p13_helpers import seed_storyboard

        with animation_env(monkeypatch) as env:
            asyncio.run(seed_storyboard(env.storage, make_storyboard(env.words)))
            assert env.client.post(f"{_SB}/continuity", json={"kind": "prop", "name": "x", "description": "y"}).status_code == 409
            assert env.client.patch(f"{_SB}/scenes/1", json={"entities": []}).status_code == 409

    def test_patching_a_scenes_entities(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("2",)) as env:
            r = env.client.patch(f"{_SB}/scenes/2", json={"entities": ["teal_book"]})
            assert r.status_code == 200, r.text
            scene = env.scenes()[1]
            assert scene["entities"] == ["teal_book"] and scene["flags"] == ["image_out_of_date"]
            assert env.client.patch(f"{_SB}/scenes/2", json={"entities": ["ghost"]}).status_code == 404

    def test_editing_a_prompt_flags_an_existing_image_and_emptying_it_asks_for_one(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1",)) as env:
            env.client.patch(f"{_SB}/scenes/1", json={"ai_prompt": "a different frame"})
            assert env.scenes()[0]["flags"] == ["image_out_of_date"]
            env.client.patch(f"{_SB}/scenes/2", json={"ai_prompt": "new words"})
            assert env.scenes()[1]["flags"] == []  # no image yet, nothing is out of date
            env.client.patch(f"{_SB}/scenes/2", json={"ai_prompt": "  "})
            assert env.scenes()[1]["flags"] == ["needs_prompt"] and env.scenes()[1]["ai_prompt"] is None
            env.client.patch(f"{_SB}/scenes/2", json={"ai_prompt": "back again"})
            assert env.scenes()[1]["flags"] == []

    def test_a_patch_that_does_not_touch_the_prompt_leaves_the_flags(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1",)) as env:
            env.client.patch(f"{_SB}/scenes/1", json={"motion_effect": "static"})
            assert env.scenes()[0]["flags"] == [] and env.scenes()[0]["motion_effect"] == "static"

    def test_generating_a_scene_clears_its_out_of_date_flag(self, monkeypatch):
        with animation_env(monkeypatch, with_images_for=("1",)) as env:
            env.client.patch(f"{_SB}/continuity/learner", json={"description": "a student in a red coat"})
            assert env.scenes()[0]["flags"] == ["image_out_of_date"]
            r = env.client.post(f"/platform/studio/runs/{RUN_ID}/scenes/1/generate", json={"prompt": "prompt 1"})
            assert r.status_code == 200, r.text
            assert env.scenes()[0]["flags"] == []

    def test_split_through_the_api_flags_the_new_scene(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            r = env.client.post(f"{_SB}/scenes/1/split", json={"at_word": 2})
            assert r.status_code == 200, r.text
            scenes = env.scenes()
            assert len(scenes) == 4 and scenes[1]["flags"] == ["needs_prompt"] and scenes[0]["ai_prompt"] == "prompt 1"
