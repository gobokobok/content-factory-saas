"""Timeline model, builder and route (P13b-S1). The render-script goldens live in test_p13b_s1_golden_render.py."""

import asyncio
import re

import pytest

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.schemas import StageState
from cf_platform.interfaces.routes._helpers import prepare_run_timeline
from cf_platform.workers.render_worker import build_render_worker, missing_assets_message
from cf_platform.workers.timeline import (
    TIMELINE_SCHEMA_VERSION,
    MissingAssetsError,
    Timeline,
    TimelineArtifact,
    TimelineSettings,
    build_timeline,
    scene_words_from_timeline,
    scenes_with_timeline_durations,
)
from cf_platform.workers.voice_production import VoiceAlignmentArtifact
from src.models import MOTION_EFFECTS
from tests.cf_platform import test_p13b_s1_golden_render as g
from tests.cf_platform.p13_helpers import (
    RUN_ID,
    make_manifest,
    make_storyboard,
    make_words,
    p13_env,
    seed_manifest,
)

SETTINGS = TimelineSettings(format_track="portrait")


def _alignment(words) -> VoiceAlignmentArtifact:
    """A Deepgram-style alignment artifact over the given words."""
    return VoiceAlignmentArtifact(
        mp3_r2_key=f"runs/{RUN_ID}/voiceover/vo.mp3", word_timestamps=words,
        alignment_method="deepgram_nova2", total_duration_s=words[-1].end_ms / 1000,
    )


# ── build_timeline ────────────────────────────────────────────────────────────


def test_timeline_resolves_scene_timing_from_the_alignment():
    words = make_words()
    sb = make_storyboard(words)
    tl = build_timeline(sb, make_manifest(sb), _alignment(words), SETTINGS)
    assert [(s.start_ms, s.end_ms) for s in tl.scenes] == [(0, 2000), (2000, 4000), (4000, 6000)]
    assert tl.duration_ms == 6000
    assert tl.schema_version == TIMELINE_SCHEMA_VERSION
    assert (tl.width, tl.height, tl.aspect_ratio) == (1080, 1920, "9:16")
    assert tl.captions_source == "alignment"
    assert len(tl.caption_words) == 12
    assert [w.scene_index for w in tl.caption_words] == [1] * 4 + [2] * 4 + [3] * 4
    assert tl.voiceover_duration_s == 6.0


def test_timeline_without_alignment_uses_storyboard_durations_and_script_captions():
    sb = make_storyboard(make_words())
    tl = build_timeline(sb, make_manifest(sb), None, SETTINGS)
    assert tl.captions_source == "script"
    assert tl.caption_words == []
    assert tl.voiceover_duration_s is None
    assert [s.duration_s for s in tl.scenes] == [s.duration_s for s in sb.scenes]


def test_timeline_landscape_size():
    sb = make_storyboard(make_words())
    tl = build_timeline(sb, make_manifest(sb), None, TimelineSettings(format_track="landscape"))
    assert (tl.width, tl.height, tl.aspect_ratio) == (1920, 1080, "16:9")


def test_timeline_scene_carries_asset_motion_text_and_sfx():
    words = make_words()
    sb = make_storyboard(words, **{
        "1": {"motion_effect": "pan_left", "sfx": "whoosh"},
        "2": {"on_screen_text": "Up 40%", "on_screen_text_type": "stat", "sfx": "impact"},
    })
    mf = make_manifest(sb)
    mf.entries[2].file_key = f"runs/{RUN_ID}/video/3.mp4"
    tl = build_timeline(sb, mf, _alignment(words), SETTINGS)
    one, two, three = tl.scenes
    assert (one.asset_kind, one.asset_path, one.motion_effect) == ("image", "images/1.jpg", "pan_left")
    assert (one.sfx_key, one.sfx_path, one.sfx_delay_ms) == ("whoosh", "sfx/whoosh.mp3", 0)
    assert two.text.text == "Up 40%" and two.text.type == "stat"
    assert (two.text.start_ms, two.text.end_ms) == (2300, 4000)
    # SFX on a scene with text lands as the slide-in finishes: scene start + 0.7s.
    assert two.sfx_delay_ms == 2700
    # Footage: no motion effect (D089).
    assert (three.asset_kind, three.motion_effect) == ("video", None)


def test_timeline_follows_the_file_key_not_the_scene_id():
    """Split / merge renumber scenes; a kept file keeps its slot name (D102)."""
    words = make_words()
    sb = make_storyboard(words)
    mf = make_manifest(sb)
    mf.entries[1].file_key = f"runs/{RUN_ID}/images/scene_w4.jpg"
    mf.entries[1].asset_slot = "scene_w4"
    tl = build_timeline(sb, mf, _alignment(words), SETTINGS)
    assert tl.scenes[1].asset_key == f"runs/{RUN_ID}/images/scene_w4.jpg"
    assert tl.scenes[1].asset_path == "images/scene_w4.jpg"


def test_timeline_refuses_a_scene_without_a_file():
    sb = make_storyboard(make_words(), **{"2": {"asset_strategy": "upload"}})
    mf = make_manifest(sb)
    mf.entries[1].file_key = None
    mf.entries[1].status = "awaiting_upload"
    with pytest.raises(MissingAssetsError, match="Scene.*2.*Upload"):
        build_timeline(sb, mf, None, SETTINGS)
    assert missing_assets_message(sb, mf)


def test_timeline_round_trips_through_json():
    words = make_words()
    sb = make_storyboard(words, **{"1": {"sfx": "whoosh"}})
    tl = build_timeline(sb, make_manifest(sb), _alignment(words), SETTINGS.model_copy(update={
        "voiceover_key": f"runs/{RUN_ID}/voiceover/vo.mp3", "music_key": f"runs/{RUN_ID}/music/bed.mp3",
    }))
    again = Timeline.model_validate_json(tl.model_dump_json())
    assert again == tl
    assert tl.referenced_paths() == [
        "images/1.jpg", "images/2.jpg", "images/3.jpg", "voiceover/vo.mp3", "music/bed.mp3", "sfx/whoosh.mp3",
    ]
    assert tl.referenced_keys()[-1] == f"runs/{RUN_ID}/sfx/whoosh.mp3"


def test_timeline_scene_words_rebuild_matches_the_resolved_words():
    words = make_words()
    sb = make_storyboard(words)
    tl = build_timeline(sb, make_manifest(sb), _alignment(words), SETTINGS)
    per_scene = scene_words_from_timeline(tl)
    assert [len(x) for x in per_scene] == [4, 4, 4]
    assert per_scene[1][0].word == "w4" and per_scene[1][0].start_ms == 2000


def test_timeline_view_refuses_a_different_storyboard():
    words = make_words()
    sb = make_storyboard(words)
    tl = build_timeline(sb, make_manifest(sb), _alignment(words), SETTINGS)
    other = make_storyboard(words, starts=(0, 6))
    with pytest.raises(ValueError, match="does not match"):
        scenes_with_timeline_durations(other, tl)


# ── Word-index fix (noted in P13-S2) ─────────────────────────────────────────


def test_scene_cuts_land_on_the_storyboards_word_boundaries_with_contractions():
    """start_word indexes the normalised words; raw Deepgram words carry contraction splits."""
    sb, mf, raw = g._contraction_run()
    # Normalised starts: w0 240, c1 640, w2 1040, c3 1440, w4 1840 ... w7 3040
    tl = build_timeline(sb, mf, VoiceAlignmentArtifact(
        mp3_r2_key="", word_timestamps=raw, alignment_method="deepgram_nova2",
        total_duration_s=raw[-1].end_ms / 1000 + 0.3,
    ), SETTINGS)
    assert [s.start_ms for s in tl.scenes] == [0, 1600, 2800]  # cumulative from the first boundary
    assert [s.duration_s for s in tl.scenes] == [1.6, 1.2, 1.5]
    # scene 2 begins on the storyboard's word 4 ("w4" at 1840ms), not on the raw list's index 4
    first_of_scene_2 = next(w for w in tl.caption_words if w.scene_index == 2)
    assert (first_of_scene_2.word, first_of_scene_2.start_ms) == ("w4", 1840)
    first_of_scene_3 = next(w for w in tl.caption_words if w.scene_index == 3)
    assert (first_of_scene_3.word, first_of_scene_3.start_ms) == ("w7", 3040)


# ── Timeline and script agree ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sfx_offsets_in_the_timeline_are_the_ones_in_the_script():
    sb, mf, w = g._aligned(n_scenes=4, **{
        "1": {"sfx": "whoosh"}, "2": {"sfx": "impact", "text": "Big", "text_type": "stat"},
        "3": {"sfx": "silence"}, "4": {"sfx": "whoosh"},
    })
    script = await g.render_script(sb, mf, alignment=w, inputs=g.PORTRAIT)
    tl = build_timeline(sb, mf, VoiceAlignmentArtifact(
        mp3_r2_key="", word_timestamps=w, alignment_method="deepgram_nova2", total_duration_s=w[-1].end_ms / 1000 + 0.3,
    ), SETTINGS)
    in_script = [int(m) for m in re.findall(r"adelay=(\d+)\|", script)]
    assert in_script == [s.sfx_delay_ms for s in tl.scenes if s.sfx_key]


@pytest.mark.asyncio
async def test_motion_in_the_timeline_is_the_effect_the_script_renders():
    scenes = [g.scene(str(i + 1), motion=e) for i, e in enumerate(MOTION_EFFECTS)]
    scenes += [g.scene("7", motion="scale"), g.scene("8", motion=None)]
    tl = build_timeline(g.storyboard(scenes), g.manifest(scenes), None, SETTINGS)
    assert [s.motion_effect for s in tl.scenes] == [*MOTION_EFFECTS, "ken_burns", "ken_burns"]


@pytest.mark.asyncio
async def test_worker_renders_the_same_script_from_a_stored_timeline():
    """The render endpoint stores the timeline and passes its key; the worker output is unchanged."""
    sb, mf, w = g._aligned()
    expected = await g.render_script(sb, mf, alignment=w, inputs=g.PORTRAIT)
    # Same run, but the timeline is built beforehand and handed over by key.
    from datetime import UTC, datetime
    from pathlib import Path
    from unittest.mock import AsyncMock, MagicMock, patch

    alignment = VoiceAlignmentArtifact(
        mp3_r2_key="", word_timestamps=w, alignment_method="deepgram_nova2",
        total_duration_s=w[-1].end_ms / 1000 + 0.3,
    )
    tl = build_timeline(sb, mf, alignment, TimelineSettings(format_track="portrait"))
    storage = InMemoryArtifactStorage()
    prefix = f"users/operator/runs/{g.RUN_ID}"
    from cf_platform.workers.acquisition_worker import AssetManifestArtifact
    from cf_platform.workers.storyboard_worker import VerifiedStoryboardArtifact

    await storage.put_json(f"{prefix}/storyboard/verified_storyboard@v1.json", g._envelope(
        "verified_storyboard", "storyboard", VerifiedStoryboardArtifact(
            prompt_version="v", scene_count=3, storyboard=sb.model_dump(by_alias=True, mode="json"),
            generated_at=datetime.now(UTC))))
    await storage.put_json(f"{prefix}/acquisition/asset_manifest@v1.json", g._envelope(
        "asset_manifest", "acquisition", AssetManifestArtifact(
            scene_count=3, acquired=3, failed=0, footage_summary={}, manifest=mf.model_dump(mode="json"),
            generated_at=datetime.now(UTC))))
    await storage.put_json(f"{prefix}/render/timeline@v1.json", g._envelope(
        "timeline", "render", TimelineArtifact(timeline=tl, generated_at=datetime.now(UTC))))
    for entry in mf.entries:
        await storage.put_bytes(entry.file_key, b"A")

    def fake_run(*_a, **_k):
        """Leave a final.mp4 behind."""
        out = Path(f"/tmp/{g.RUN_ID}/output/final.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"MP4")
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch("asyncio.to_thread", new=AsyncMock(side_effect=fake_run)):
        await build_render_worker(storage, ffmpeg_timeout_seconds=60)(StageState(
            run_id=g.RUN_ID, user_id="operator", inputs={"format_track": "portrait"},
            artifacts={
                "verified_storyboard": f"{prefix}/storyboard/verified_storyboard@v1.json",
                "asset_manifest": f"{prefix}/acquisition/asset_manifest@v1.json",
                "timeline": f"{prefix}/render/timeline@v1.json",
            },
        ))
    script = (await storage.get_bytes(f"runs/{g.RUN_ID}/render_script.sh")).decode()
    masked = g._GENERATED_AT.sub("# generated_at: <masked>", script)
    assert masked == g._GENERATED_AT.sub("# generated_at: <masked>", expected)


# ── Route ─────────────────────────────────────────────────────────────────────


def test_timeline_route_returns_the_timeline():
    with p13_env(with_manifest=True) as env:
        r = env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline?format_track=portrait")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == TIMELINE_SCHEMA_VERSION
    assert [s["scene_id"] for s in body["scenes"]] == ["1", "2", "3"]
    assert body["scenes"][0]["asset_path"] == "images/1.jpg"
    assert body["captions_source"] == "alignment"
    assert body["aspect_ratio"] == "9:16"


def test_timeline_route_is_409_while_a_scene_has_no_file():
    with p13_env(with_manifest=False, **{"2": {"asset_strategy": "upload"}}) as env:
        sb = make_storyboard(env.words, **{"2": {"asset_strategy": "upload"}})
        mf = make_manifest(sb)
        mf.entries[1].file_key = None
        mf.entries[1].status = "awaiting_upload"
        asyncio.run(seed_manifest(env.storage, mf))
        r = env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline")
    assert r.status_code == 409
    assert "Scene(s) 2" in r.json()["detail"] and "Upload" in r.json()["detail"]


def test_timeline_route_404_without_a_manifest_and_422_on_bad_options():
    with p13_env(with_manifest=False) as env:
        assert env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline").status_code == 404
        assert env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline?format_track=square").status_code == 422
        assert env.client.get(f"/platform/studio/runs/{RUN_ID}/timeline?caption_style=loud").status_code == 422


def test_prepare_run_timeline_stores_a_new_artifact_version_each_time():
    with p13_env(with_manifest=True) as env:
        _, key1 = asyncio.run(prepare_run_timeline(env.storage, RUN_ID, write=True))
        _, key2 = asyncio.run(prepare_run_timeline(env.storage, RUN_ID, write=True))
        _, none_key = asyncio.run(prepare_run_timeline(env.storage, RUN_ID))
    assert key1.endswith("/render/timeline@v1.json") and key2.endswith("/render/timeline@v2.json")
    assert none_key is None
