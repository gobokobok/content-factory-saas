"""Tests for P13-S4: replace all scene boundaries at once (the Script view).

Covers:
- PUT …/storyboard/boundaries happy path, by start_words and by script_text
- every validation failure
- unchanged scenes keep their fields and assets; new scenes inherit visual fields
- changed words are rejected
- dry_run reports what would change and writes nothing
"""

import pytest

from cf_platform.workers.storyboard_edit import StoryboardEditError, start_words_from_text
from tests.cf_platform.p13_helpers import RUN_ID, make_words, p13_env

_URL = f"/platform/studio/runs/{RUN_ID}/storyboard/boundaries"


def _text(*paragraphs: tuple[int, int]) -> str:
    """Build script-view text: one paragraph of "w{i}" words per (first, last) span."""
    return "\n\n".join(" ".join(f"w{i}" for i in range(a, b + 1)) for a, b in paragraphs)


class TestReplaceBoundaries:
    def test_start_words_replace_all_boundaries(self):
        with p13_env() as env:
            r = env.client.put(_URL, json={"start_words": [0, 3, 6, 9]})

            assert r.status_code == 200, r.text
            scenes = r.json()["storyboard"]["scenes"]
            assert [(s["scene"], s["start_word"], s["end_word"]) for s in scenes] == [
                ("1", 0, 2), ("2", 3, 5), ("3", 6, 8), ("4", 9, 11),
            ]
            assert all(s["duration_s"] == 1.5 for s in scenes)
            assert r.json()["summary"].startswith("3 scenes → 4")
            assert env.scenes() == scenes

    def test_script_text_gives_the_same_result_as_start_words(self):
        with p13_env() as by_words:
            expected = by_words.client.put(_URL, json={"start_words": [0, 3, 6, 9]}).json()["storyboard"]
        with p13_env() as by_text:
            r = by_text.client.put(_URL, json={"script_text": _text((0, 2), (3, 5), (6, 8), (9, 11))})

            assert r.status_code == 200, r.text
            assert r.json()["storyboard"] == expected

    def test_whitespace_and_extra_blank_lines_are_not_word_changes(self):
        words = make_words()
        text = "  w0 w1\nw2 w3 \n\n\n\n w4   w5 w6 w7\n \nw8 w9 w10 w11\n"

        assert start_words_from_text(words, text) == [0, 4, 8]

    def test_same_boundaries_change_nothing_but_still_validate(self):
        with p13_env(with_manifest=True) as env:
            before = env.scenes()
            r = env.client.put(_URL, json={"start_words": [0, 4, 8]})

            assert r.status_code == 200
            assert env.scenes() == before
            assert r.json()["needs_acquisition"] == []


class TestValidation:
    @pytest.mark.parametrize(
        ("start_words", "fragment"),
        [
            ([], "At least one scene"),
            ([1, 4, 8], "must start at word 0"),
            ([0, 8, 4], "strictly increasing"),
            ([0, 4, 4], "strictly increasing"),
            ([0, 4, 12], "outside the voiceover"),
            ([0, 4, 5], "shorter than the 1s minimum"),
        ],
    )
    def test_invalid_boundaries_are_rejected(self, start_words, fragment):
        with p13_env() as env:
            r = env.client.put(_URL, json={"start_words": start_words})

            assert r.status_code == 422
            assert fragment in r.json()["detail"]
            assert env.versions("storyboard", "verified_storyboard") == 1  # nothing written

    @pytest.mark.parametrize("body", [{}, {"start_words": [0, 6], "script_text": "w0"}])
    def test_exactly_one_of_start_words_or_script_text(self, body):
        with p13_env() as env:
            assert env.client.put(_URL, json=body).status_code == 422

    def test_no_voiceover_is_409(self):
        with p13_env(with_voice=False) as env:
            assert env.client.put(_URL, json={"start_words": [0, 6]}).status_code == 409


class TestChangedWords:
    @pytest.mark.parametrize(
        "text",
        [
            _text((0, 5), (6, 10)),                       # a word removed
            _text((0, 5), (6, 11)) + " extra",            # a word added
            _text((0, 5), (6, 11)).replace("w3", "W3"),   # a word altered
            _text((6, 11), (0, 5)),                       # words reordered
            "",
        ],
    )
    def test_text_that_differs_by_more_than_breaks_is_rejected(self, text):
        with p13_env() as env:
            r = env.client.put(_URL, json={"script_text": text})

            assert r.status_code == 422
            assert "Script stage" in r.json()["detail"] and "re-voicing" in r.json()["detail"]
            assert env.versions("storyboard", "verified_storyboard") == 1

    def test_pure_function_raises(self):
        with pytest.raises(StoryboardEditError):
            start_words_from_text(make_words(), "completely different words")


class TestWhatScenesKeep:
    def test_unchanged_start_keeps_fields_and_asset(self):
        overrides = {
            "1": {"on_screen_text": "Peak year", "on_screen_text_type": "date", "sfx": "ding", "motion_effect": "zoom_out"},
            "3": {"on_screen_text": "7%", "on_screen_text_type": "stat"},
        }
        with p13_env(with_manifest=True, **overrides) as env:
            # Scene 1 grows by two words, the old scene 2 is cut at a new word, scene 3 is untouched.
            r = env.client.put(_URL, json={"start_words": [0, 6, 8]})

            scenes = r.json()["storyboard"]["scenes"]
            assert scenes[0]["on_screen_text"] == "Peak year" and scenes[0]["sfx"] == "ding"
            assert scenes[0]["motion_effect"] == "zoom_out"
            assert scenes[0]["end_word"] == 5 and scenes[0]["duration_s"] == 3.0
            assert scenes[2]["on_screen_text"] == "7%"

            entries = env.manifest_entries()
            assert entries[0]["file_key"] == f"runs/{RUN_ID}/images/1.jpg"
            assert entries[2]["file_key"] == f"runs/{RUN_ID}/images/3.jpg"

    def test_new_scene_inherits_from_the_scene_it_was_cut_from(self):
        overrides = {"2": {"on_screen_text": "40%", "on_screen_text_type": "stat", "sfx": "whoosh"}}
        with p13_env(with_manifest=True, **overrides) as env:
            r = env.client.put(_URL, json={"start_words": [0, 6, 8]})

            cut = r.json()["storyboard"]["scenes"][1]
            assert cut["primary_stk"] == "query 2"          # words 6–7 belonged to the old scene 2
            assert cut["on_screen_text"] is None and cut["sfx"] == ""
            assert r.json()["needs_acquisition"] == ["2"]
            assert env.manifest_entries()[1]["status"] == "pending"
            # The old scene 2 no longer starts anywhere: its text and SFX are reported as dropped.
            assert r.json()["dropped"] == [{"scene": "2", "on_screen_text": "40%", "sfx": "whoosh"}]

    def test_character_cut_does_not_repeat_the_name_overlay(self):
        overrides = {"2": {"segment_type": "Character", "person_name": "Jane Jacobs"}}
        with p13_env(**overrides) as env:
            r = env.client.put(_URL, json={"start_words": [0, 4, 6, 8]})

            first, cut = r.json()["storyboard"]["scenes"][1:3]
            assert first["on_screen_text"] == "Jane Jacobs"
            assert cut["segment_type"] == "Character"
            assert cut["person_name"] is None and cut["on_screen_text"] is None


class TestDryRun:
    def test_dry_run_reports_and_writes_nothing(self):
        with p13_env(with_manifest=True) as env:
            r = env.client.put(_URL, json={"start_words": [0, 2, 4, 6, 8], "dry_run": True})

            assert r.status_code == 200
            body = r.json()
            assert body["dry_run"] is True
            assert body["summary"] == "3 scenes → 5; 2 scenes need acquisition"
            assert body["needs_acquisition"] == ["2", "4"]
            assert "storyboard" not in body and "artifact_key" not in body
            assert env.versions("storyboard", "verified_storyboard") == 1
            assert env.versions("acquisition", "asset_manifest") == 1

    def test_dry_run_before_acquisition_does_not_mention_acquisition(self):
        with p13_env() as env:
            r = env.client.put(_URL, json={"start_words": [0, 6], "dry_run": True})

            assert r.json()["summary"] == "3 scenes → 2"
            assert r.json()["needs_acquisition"] is None

    def test_dry_run_still_validates(self):
        with p13_env() as env:
            assert env.client.put(_URL, json={"start_words": [0, 4, 5], "dry_run": True}).status_code == 422
