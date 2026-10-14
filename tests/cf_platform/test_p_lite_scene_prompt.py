"""P-LITE smoke follow-up — the Visual Director writes one scene's image prompt (D117).

A scene made by splitting another has no prompt; re-creating the storyboard would
re-cut every scene. The director writes that one scene with its own rules.
"""

import asyncio
import json
from unittest.mock import patch

import pytest

from cf_platform.workers import scene_prompt_writer as spw
from cf_platform.workers.animation_storyboard_worker import _ANIMATION_SYSTEM_PROMPT
from src.models import ANIMATION_MODE, SCENE_FLAG_NEEDS_PROMPT, ContinuityEntry, SceneShot
from tests.cf_platform.p13_helpers import RUN_ID, make_storyboard, make_words, p13_env, seed_storyboard

ANSWER = json.dumps({
    "visual_concept": "Maya studies the price tag.",
    "shot": {"size": "Close-up", "angle": "high"},
    "entities": ["maya", "ghost"],
    "ai_prompt": "Close-up from a high angle: Maya holds a price tag between two fingers.",
})


def _animated(prompts=("Maya at the door", None, "A wide street")):
    """A three-scene Animation storyboard; scene 2 was just split off and has no prompt."""
    sb = make_storyboard(make_words())
    scenes = []
    for scene, prompt in zip(sb.scenes, prompts, strict=True):
        scenes.append(scene.model_copy(update={
            "ai_prompt": prompt, "entities": ["maya"] if prompt else [],
            "shot": SceneShot(size="wide", angle="eye-level"),
            "flags": [] if prompt else [SCENE_FLAG_NEEDS_PROMPT],
        }))
    return sb.model_copy(update={
        "visual_mode": ANIMATION_MODE, "scenes": scenes,
        "continuity": [ContinuityEntry(id="maya", kind="character", name="Maya", description="a woman with a red scarf")],
    })


class TestTheDirectorsRules:
    @pytest.mark.parametrize("title", spw._REUSED_SECTIONS)
    def test_each_reused_section_is_found_in_the_directors_prompt(self, title):
        section = spw.director_section(title)
        assert section.splitlines()[1] == title and section in _ANIMATION_SYSTEM_PROMPT

    def test_the_system_prompt_carries_the_image_prompt_rules_and_no_storyboard_only_rules(self):
        system = spw.scene_prompt_system()
        assert "Never include in ai_prompt" in system and "Reject generic imagery" in system
        assert "Consecutive scenes differ in at least two of" in system
        assert "Do not invent a new character" in system
        assert "INDEXED WORD LIST" not in system and "Coverage — critical" not in system
        assert "SOUND EFFECT" not in system

    def test_a_renamed_section_fails_loudly(self):
        with pytest.raises(ValueError):
            spw.director_section("9. SOMETHING ELSE")


class TestTheMessage:
    def test_it_names_the_bible_the_neighbours_and_the_target(self):
        msg = spw.build_scene_prompt_message(_animated(), "2", "flat ink", "landscape")
        assert "Horizontal 16:9" in msg and "flat ink" in msg
        assert 'id "maya" (character) — Maya: a woman with a red scarf' in msg
        assert "<-- THIS SCENE" in msg and "WRITE SCENE 2:" in msg
        assert "Scene before (1)" in msg and "prompt: Maya at the door" in msg
        assert "Scene after (3)" in msg and "A wide street" in msg

    def test_an_unknown_scene_is_refused(self):
        with pytest.raises(spw.ScenePromptError, match="not in the storyboard"):
            spw.build_scene_prompt_message(_animated(), "99", "", "portrait")


class TestParsing:
    def test_entities_outside_the_bible_are_dropped_and_the_shot_is_kept(self):
        out = spw.parse_scene_prompt(f"```json\n{ANSWER}\n```", _animated())
        assert out.entities == ["maya"] and out.shot_size == "close-up" and out.shot_angle == "high"
        assert out.ai_prompt.startswith("Close-up")

    @pytest.mark.parametrize("raw", ["not json", "{}", json.dumps({"ai_prompt": "  "})])
    def test_an_answer_without_a_prompt_is_an_error(self, raw):
        with pytest.raises(spw.ScenePromptError):
            spw.parse_scene_prompt(raw, _animated())

    def test_no_key_is_an_error_before_any_call(self):
        with pytest.raises(spw.ScenePromptError, match="ANTHROPIC_API_KEY"):
            asyncio.run(spw.write_scene_prompt(_animated(), "2", ""))


class TestTheRoute:
    URL = f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/2/write-prompt"

    def test_the_scene_gets_its_prompt_entities_and_shot_and_no_longer_needs_one(self):
        seen = {}

        async def fake(system, user, key):
            seen["user"], seen["key"] = user, key
            return ANSWER

        with p13_env() as env:
            env.settings.ANTHROPIC_API_KEY = "k"
            asyncio.run(seed_storyboard(env.storage, _animated()))
            asyncio.run(env.storage.put_json(f"runs/{RUN_ID}/settings.json", {"master_style": "flat ink", "aspect_ratio": "9:16"}))
            with patch.object(spw, "request_scene_prompt", fake):
                r = env.client.post(self.URL)
        assert r.status_code == 200, r.text
        scenes = r.json()["storyboard"]["scenes"]
        assert scenes[1]["ai_prompt"].startswith("Close-up") and scenes[1]["entities"] == ["maya"]
        assert scenes[1]["shot"] == {"size": "close-up", "angle": "high"}
        assert SCENE_FLAG_NEEDS_PROMPT not in scenes[1]["flags"]
        assert scenes[0]["ai_prompt"] == "Maya at the door", "other scenes are untouched"
        assert seen["key"] == "k" and "flat ink" in seen["user"] and "Vertical 9:16" in seen["user"]

    def test_a_failed_answer_is_a_502_and_changes_nothing(self):
        async def fake(system, user, key):
            return "sorry"

        with p13_env() as env:
            env.settings.ANTHROPIC_API_KEY = "k"
            asyncio.run(seed_storyboard(env.storage, _animated()))
            with patch.object(spw, "request_scene_prompt", fake):
                r = env.client.post(self.URL)
            after = env.client.get(f"/platform/studio/runs/{RUN_ID}/storyboard").json()
        assert r.status_code == 502 and "could not be read" in r.json()["detail"]
        assert after["storyboard"]["scenes"][1]["ai_prompt"] in (None, "")

    def test_unknown_scene_404_and_a_stock_storyboard_409(self):
        with p13_env() as env:
            env.settings.ANTHROPIC_API_KEY = "k"
            stock = env.client.post(self.URL)
            asyncio.run(seed_storyboard(env.storage, _animated()))
            missing = env.client.post(f"/platform/studio/runs/{RUN_ID}/storyboard/scenes/99/write-prompt")
        assert stock.status_code == 409 and missing.status_code == 404


class TestThePage:
    def test_the_opened_scene_and_the_image_dialog_offer_the_director(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "src" / "static"
        js = (root / "ui" / "creator.js").read_text(encoding="utf-8")
        page = (root / "creator.html").read_text(encoding="utf-8")
        assert "/write-prompt`" in js and "Write with the director" in js and "Rewrite with the director" in js
        assert 'id="m-write"' in page and "Creator.writePromptInModal()" in page
