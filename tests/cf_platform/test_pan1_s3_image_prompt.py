"""Tests for P-AN1-S3: the image prompt assembled in code (D108)."""

from cf_platform.core.ai_images import (
    ASPECT_PHRASES,
    FIXED_LINE_FULL_BLEED,
    FIXED_LINE_NO_TEXT,
    FIXED_LINE_OVERLAY,
    build_animation_prompt,
    build_prompt,
    entity_lines,
)
from tests.cf_platform.p13_helpers import RUN_ID
from tests.cf_platform.pan1_helpers import BIBLE, MASTER_STYLE, FakeProvider, animation_env

_GEN = f"/platform/studio/runs/{RUN_ID}/scenes"
FIXED = f"{FIXED_LINE_NO_TEXT} {FIXED_LINE_FULL_BLEED}"


class TestAssembly:
    def test_the_parts_come_in_the_fixed_order(self):
        text = build_animation_prompt(
            "the learner reads", entities=["learner", "teal_book"], continuity=BIBLE,
            has_overlay=True, master_style="INK STYLE", aspect_ratio="16:9",
        )
        assert text.split("\n\n") == [
            "the learner reads",
            "The learner: a student with a black bob and round glasses",
            "The teal book: a thick teal cloth-bound book",
            f"{FIXED} {FIXED_LINE_OVERLAY}",
            "INK STYLE",
            "Horizontal 16:9.",
        ]

    def test_bible_descriptions_are_verbatim_and_follow_the_scene_order(self):
        lines = entity_lines(["teal_book", "learner"], BIBLE)
        assert lines[0].endswith(BIBLE[1]["description"]) and lines[1].endswith(BIBLE[0]["description"])

    def test_every_part_but_the_fixed_lines_is_optional(self):
        assert build_animation_prompt(None) == FIXED
        assert build_animation_prompt("  a desk ") == f"a desk\n\n{FIXED}"
        assert build_animation_prompt("a desk", master_style="  ", aspect_ratio="4:3") == f"a desk\n\n{FIXED}"
        assert build_animation_prompt("a desk", aspect_ratio="9:16").endswith("\n\nVertical 9:16.")

    def test_the_calm_lower_part_line_is_only_there_with_on_screen_text(self):
        assert FIXED_LINE_OVERLAY not in build_animation_prompt("a desk", has_overlay=False)
        assert FIXED_LINE_OVERLAY in build_animation_prompt("a desk", has_overlay=True)
        assert "not a dark band" in FIXED_LINE_OVERLAY

    def test_the_fixed_lines_forbid_text_borders_and_letterboxing(self):
        assert "text" in FIXED_LINE_NO_TEXT and "numerals" in FIXED_LINE_NO_TEXT
        for word in ("Full-bleed", "borders", "letterbox", "panel frame"):
            assert word in FIXED_LINE_FULL_BLEED

    def test_an_unknown_entity_id_is_ignored_with_a_warning(self, caplog):
        with caplog.at_level("WARNING"):
            text = build_animation_prompt("a desk", entities=["ghost", "learner"], continuity=BIBLE)
        assert "ghost" in caplog.text and "ghost" not in text and "The learner:" in text

    def test_bible_entries_may_be_models_or_dicts_and_an_empty_description_adds_nothing(self):
        from src.models import ContinuityEntry

        models = [ContinuityEntry(**BIBLE[0]), ContinuityEntry(id="x", name="x", description="")]
        assert entity_lines(["learner", "x"], models) == ["The learner: a student with a black bob and round glasses"]

    def test_aspect_phrases(self):
        assert ASPECT_PHRASES["9:16"] == "Vertical 9:16." and ASPECT_PHRASES["16:9"] == "Horizontal 16:9."

    def test_the_stock_mode_prompt_is_unchanged(self):
        assert build_prompt("STYLE", " a street ") == "STYLE\n\na street"
        assert build_prompt(None, "a street") == "a street"


class TestRoutes:
    def test_generate_in_an_animation_run_sends_the_assembled_text_and_stores_only_the_scene_prompt(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            r = env.client.post(f"{_GEN}/1/generate", json={"prompt": "the learner reads"})
            assert r.status_code == 200, r.text
            sent, aspect = FakeProvider.calls[0]
            assert aspect == "9:16"
            assert sent.split("\n\n") == [
                "the learner reads", "The learner: a student with a black bob and round glasses",
                FIXED, MASTER_STYLE, "Vertical 9:16.",
            ]
            scene = next(s for s in env.scenes() if s["scene"] == "1")
            assert scene["ai_prompt"] == "the learner reads"  # scene-specific only

    def test_a_scene_with_on_screen_text_gets_the_overlay_line(self, monkeypatch):
        with animation_env(monkeypatch, **{"2": {"on_screen_text": "40%", "on_screen_text_type": "stat"}}) as env:
            env.client.post(f"{_GEN}/2/generate", json={"prompt": "a chart"})
            assert FIXED_LINE_OVERLAY in FakeProvider.calls[0][0]
            env.client.post(f"{_GEN}/3/generate", json={"prompt": "a desk"})
            assert FIXED_LINE_OVERLAY not in FakeProvider.calls[1][0]

    def test_the_run_style_wins_and_the_aspect_follows_the_run(self, monkeypatch):
        with animation_env(monkeypatch, settings={"master_style": "RUN STYLE", "aspect_ratio": "16:9"}) as env:
            env.client.post(f"{_GEN}/2/generate", json={"prompt": "a desk"})
            sent, aspect = FakeProvider.calls[0]
            assert "RUN STYLE" in sent and sent.endswith("Horizontal 16:9.") and aspect == "16:9"

    def test_the_preview_is_the_text_generate_would_send_and_costs_nothing(self, monkeypatch):
        with animation_env(monkeypatch) as env:
            r = env.client.post(f"{_GEN}/1/prompt-preview", json={})
            assert r.status_code == 200, r.text
            preview = r.json()
            assert preview["visual_mode"] == "ai_animation"
            assert preview["text"].startswith("prompt 1\n\nThe learner:")
            assert FakeProvider.calls == []
            edited = env.client.post(f"{_GEN}/1/prompt-preview", json={"prompt": "edited"}).json()["text"]
            assert edited.startswith("edited\n\n")
            env.client.post(f"{_GEN}/1/generate", json={"prompt": "edited"})
            assert FakeProvider.calls[0][0] == edited
            assert env.client.post(f"{_GEN}/9/prompt-preview", json={}).status_code == 404

    def test_a_stock_storyboard_keeps_the_p14_behaviour(self, monkeypatch):
        """Mode comes from the storyboard itself: a stock storyboard is never assembled."""
        import asyncio

        from tests.cf_platform.p13_helpers import make_storyboard, seed_storyboard

        with animation_env(monkeypatch) as env:
            asyncio.run(seed_storyboard(env.storage, make_storyboard(env.words)))
            env.client.post(f"{_GEN}/2/generate", json={"prompt": "a quiet street"})
            assert FakeProvider.calls == [("a quiet street", "9:16")]
            assert env.client.post(f"{_GEN}/2/prompt-preview", json={}).json()["text"] == "a quiet street"
