"""Timeline -> CapCut draft mapping (P13b-S3), tested on plain data.

Runs in CI without CapCut and without pycapcut: tools/capcut/draft_plan.py is pure, and
export_capcut.py imports pycapcut only when it writes a draft.
"""

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "capcut"))

import draft_plan as dp  # noqa: E402
import export_capcut as ec  # noqa: E402
from draft_plan import MediaInfo, TimelineError, plan_draft  # noqa: E402

from cf_platform.workers.render_worker import _build_captions_with_y_override  # noqa: E402
from cf_platform.workers.timeline import TimelineSettings, build_timeline  # noqa: E402
from cf_platform.workers.voice_production import VoiceAlignmentArtifact  # noqa: E402
from src import ffmpeg_builder as fb  # noqa: E402
from tests.cf_platform import test_p13b_s1_golden_render as g  # noqa: E402

US = 1_000_000


def _timeline(fmt: str = "portrait", style: str = "punch", scenes=None, words=None, **settings) -> dict:
    """A real Timeline (built by the platform) as plain JSON data."""
    if scenes is None:
        scenes = [
            g.scene("1", motion="pan_right", sfx="whoosh", start_word=0, end_word=3, start_ms=240),
            g.scene("2", motion="zoom_in", text="Up 40% since 2020", text_type="stat", start_word=4, end_word=7, start_ms=1840),
            g.scene("3", motion="ken_burns", start_word=8, end_word=11, start_ms=3440),
        ]
    w = words or g.words(12)
    sb, mf = g.storyboard(scenes), g.manifest(scenes, exts={"3": ".mp4"})
    alignment = VoiceAlignmentArtifact(
        mp3_r2_key="runs/gold1/voiceover/vo.mp3", word_timestamps=w, alignment_method="deepgram_nova2",
        total_duration_s=w[-1].end_ms / 1000 + 0.3,
    )
    tl = build_timeline(sb, mf, alignment, TimelineSettings(
        format_track=fmt, caption_style=style, voiceover_key="runs/gold1/voiceover/vo.mp3",
        music_key="runs/gold1/music/bed.mp3", **settings,
    ))
    return json.loads(tl.model_dump_json())


def _media(timeline: dict, land=(1920, 1080), port=(1080, 1920)) -> dict[str, MediaInfo]:
    """Plausible measurements: scene 1 landscape, scene 2 portrait, scene 3 a 10s clip."""
    media = {
        "images/1.jpg": MediaInfo(*land), "images/2.jpg": MediaInfo(*port),
        "video/3.mp4": MediaInfo(1280, 720, 10 * US),
        "voiceover/vo.mp3": MediaInfo(duration_us=int(timeline["voiceover_duration_s"] * US)),
        "music/bed.mp3": MediaInfo(duration_us=3 * US),
        "sfx/whoosh.mp3": MediaInfo(duration_us=500_000),
    }
    return media


# ── Timing ────────────────────────────────────────────────────────────────────


def test_scene_timing_is_in_microseconds_from_the_timeline():
    tl = _timeline()
    plan = plan_draft(tl, _media(tl))
    assert [(c.start_us, c.duration_us) for c in plan.video] == [
        (s["start_ms"] * 1000, (s["end_ms"] - s["start_ms"]) * 1000) for s in tl["scenes"]
    ]
    assert (plan.width, plan.height, plan.fps) == (1080, 1920, 25)
    assert [c.scene_id for c in plan.video] == ["1", "2", "3"]


def test_canvas_and_cover_scale_follow_the_timeline_for_both_formats():
    for fmt, size in (("portrait", (1080, 1920)), ("landscape", (1920, 1080))):
        tl = _timeline(fmt)
        plan = plan_draft(tl, _media(tl))
        assert (plan.width, plan.height) == size
    assert dp.cover_scale(1920, 1080, 1080, 1920) == pytest.approx(3.1605, abs=1e-4)   # landscape still in 9:16
    assert dp.cover_scale(1080, 1920, 1080, 1920) == 1.0
    assert dp.cover_scale(1080, 1920, 1920, 1080) == pytest.approx(3.1605, abs=1e-4)   # portrait still in 16:9
    assert dp.cover_scale(1280, 720, 1920, 1080) == 1.0
    assert dp.cover_scale(0, 0, 1080, 1920) == 1.0


# ── Motion ────────────────────────────────────────────────────────────────────


def test_motion_constants_match_the_ffmpeg_render():
    assert dp.KEN_BURNS_RATE_PER_S == fb._KEN_BURNS_RATE_PER_S
    assert dp.ZOOM_RATE_PER_S == fb._ZOOM_RATE_PER_S
    assert dp.PAN_TRAVEL_FRACTION_PER_S == fb._PAN_TRAVEL_FRACTION_PER_S
    assert dp.PAN_MIN_TRAVEL_FRACTION == fb._PAN_MIN_TRAVEL_FRACTION
    assert dp.DUCKING_FACTOR == fb._DUCKING_FACTOR


def _kf(effect: str, seconds: float, media=(1080, 1920), canvas=(1080, 1920)):
    """Keyframes for one effect on a still."""
    scale = dp.cover_scale(*media, *canvas)
    return dp.motion_keyframes(effect, int(seconds * US), scale, *media, *canvas), scale


def test_zoom_keyframes_use_the_per_second_rates():
    kfs, scale = _kf("zoom_in", 2.5)
    assert [(k.prop, k.time_us) for k in kfs] == [("uniform_scale", 0), ("uniform_scale", 2_500_000)]
    assert [k.value for k in kfs] == [pytest.approx(1.0), pytest.approx(1.05)]
    kfs, _ = _kf("zoom_out", 2.5)
    assert [k.value for k in kfs] == [pytest.approx(1.05), pytest.approx(1.0)]
    kfs, _ = _kf("ken_burns", 4)
    assert [k.value for k in kfs] == [pytest.approx(1.0), pytest.approx(1.04)]


def test_zoom_sits_on_top_of_the_cover_scale():
    kfs, scale = _kf("zoom_in", 2, media=(1920, 1080))
    assert scale == pytest.approx(3.1605, abs=1e-4)
    assert kfs[0].value == pytest.approx(scale) and kfs[1].value == pytest.approx(scale * 1.04)


def test_static_and_unknown_effects_have_no_keyframes():
    assert _kf("static", 3)[0] == []
    assert dp.motion_keyframes(None, 3 * US, 1.0, 1080, 1920, 1080, 1920) == []


def test_pan_travels_the_budget_centred_and_in_the_right_direction():
    # 1920x1080 landscape in 9:16: huge headroom, so the 12%-of-width/s budget binds.
    right, _ = _kf("pan_right", 2, media=(1920, 1080))
    left, _ = _kf("pan_left", 2, media=(1920, 1080))
    expected = 0.12 * 2  # travel / canvas_w, in half-canvas-width units
    assert [(k.prop, k.time_us) for k in right] == [("position_x", 0), ("position_x", 2 * US)]
    assert [k.value for k in right] == [pytest.approx(expected), pytest.approx(-expected)]
    assert [k.value for k in left] == [pytest.approx(-expected), pytest.approx(expected)]


def test_pan_is_limited_by_headroom_and_collapses_on_a_narrow_portrait():
    # 1200x1920 in 9:16: scaled width 1200, headroom 120px, budget for 5s would be 648px.
    kfs, _ = _kf("pan_right", 5, media=(1200, 1920))
    assert kfs[0].value == pytest.approx(120 / 1080)
    # D091's case: a portrait still narrower than 9:16 is enlarged to leave 10% to travel.
    kfs, _ = _kf("pan_right", 5, media=(1536, 2752))
    assert kfs[0].value == pytest.approx(0.1)


def test_a_picture_with_no_room_is_enlarged_so_a_pan_has_ten_percent_to_travel():
    # 2752x1536 in 1920x1080: the covered picture is 1935 px wide, 15 px to spare.
    z = dp.pan_zoom(2752, 1536, 1920, 1080)
    assert z == pytest.approx(1920 * 1.1 / (2752 * 1080 / 1536), rel=1e-6)
    kfs, _ = _kf("pan_right", 5, media=(2752, 1536), canvas=(1920, 1080))
    assert kfs[0].value == pytest.approx(0.1)          # 192 px / 1920
    # Enough room already (a wide picture, or this one in a 9:16 frame): not enlarged.
    assert dp.pan_zoom(4000, 1080, 1920, 1080) == 1.0
    assert dp.pan_zoom(2752, 1536, 1080, 1920) == 1.0
    assert dp.pan_zoom(0, 0, 1080, 1920) == 1.0


def test_a_pan_clip_carries_the_enlargement_zooms_do_not():
    tl = _timeline()
    tl["width"], tl["height"], tl["aspect_ratio"] = 1920, 1080, "16:9"
    tl["scenes"][0]["motion_effect"] = "pan_right"
    tl["scenes"][1]["motion_effect"] = "zoom_in"
    media = _media(tl)
    for sc in tl["scenes"][:2]:
        media[sc["asset_path"]] = dp.MediaInfo(width=2752, height=1536)
    video = plan_draft(tl, media).video
    cover = dp.cover_scale(2752, 1536, 1920, 1080)
    assert video[0].scale == pytest.approx(cover * dp.pan_zoom(2752, 1536, 1920, 1080))
    assert video[1].scale == pytest.approx(cover)


def test_footage_is_trimmed_muted_and_never_gets_motion_keyframes():
    tl = _timeline()
    tl["scenes"][2]["motion_effect"] = "zoom_in"          # even a stored effect is ignored for footage (D089)
    clip = plan_draft(tl, _media(tl)).video[2]
    assert clip.kind == "video" and clip.muted
    assert clip.keyframes == []
    assert clip.source_duration_us == clip.duration_us      # trimmed to the scene, source is 10s


def test_footage_shorter_than_its_scene_is_not_stretched_and_warns():
    tl = _timeline()
    media = _media(tl)
    media["video/3.mp4"] = MediaInfo(1280, 720, 1 * US)
    plan = plan_draft(tl, media)
    clip = plan.video[2]
    assert clip.duration_us == clip.source_duration_us == 1 * US
    assert any("Scene 3" in w and "footage" in w for w in plan.warnings)


# ── Text and captions ─────────────────────────────────────────────────────────


def test_on_screen_text_is_upper_case_and_timed_from_the_timeline():
    tl = _timeline()
    plan = plan_draft(tl, _media(tl))
    ost = [t for t in plan.texts if t.track == "on_screen_text"]
    assert len(ost) == 1 and ost[0].text == "UP 40% SINCE 2020"
    text = tl["scenes"][1]["text"]
    assert (ost[0].start_us, ost[0].duration_us) == (text["start_ms"] * 1000, (text["end_ms"] - text["start_ms"]) * 1000)
    assert ost[0].background == ("#FFFFFF", 0.55) and ost[0].color == (0.0, 0.0, 0.0)


def _ass_events(tl: dict, words, scenes) -> list[tuple[float, float, str]]:
    """The platform's own caption events (start s, end s, text) for the same words and scenes."""
    from cf_platform.workers.timeline import Timeline, scene_words_from_timeline

    per_scene = scene_words_from_timeline(Timeline.model_validate(tl))
    ass = _build_captions_with_y_override(
        per_scene, scenes, "TikTok", aspect_ratio=tl["aspect_ratio"], caption_style=tl["caption_style"],
    )
    events = []
    for line in ass.splitlines():
        m = re.match(r"Dialogue: 0,(\d+):(\d\d):(\d\d)\.(\d\d),(\d+):(\d\d):(\d\d)\.(\d\d),VoiceCaption,,0,0,\d+,,(.*)", line)
        if m:
            h1, m1, s1, c1, h2, m2, s2, c2, text = m.groups()
            events.append((int(h1) * 3600 + int(m1) * 60 + int(s1) + int(c1) / 100,
                           int(h2) * 3600 + int(m2) * 60 + int(s2) + int(c2) / 100, text))
    return events


def test_punch_captions_are_one_upper_case_word_per_clip_timed_like_the_ass_captions():
    tl = _timeline(style="punch")
    plan = plan_draft(tl, _media(tl))
    clips = [t for t in plan.texts if t.track == "captions"]
    assert [c.text for c in clips] == [f"W{i}" for i in range(12)]
    scenes = [g.scene("1"), g.scene("2"), g.scene("3")]
    for clip, (start, end, text) in zip(clips, _ass_events(tl, None, scenes), strict=True):
        assert clip.text == text
        assert clip.start_us / US == pytest.approx(start, abs=0.006)
        assert (clip.start_us + clip.duration_us) / US == pytest.approx(end, abs=0.006)


def test_standard_captions_are_rolling_five_word_lines():
    tl = _timeline(style="standard")
    clips = [t for t in plan_draft(tl, _media(tl)).texts if t.track == "captions"]
    # scenes of 4 words → one 4-word line per scene, running to the next line's start
    assert [c.text for c in clips] == ["w0 w1 w2 w3", "w4 w5 w6 w7", "w8 w9 w10 w11"]
    first_words = [240, 1840, 3440]
    assert [c.start_us for c in clips] == [m * 1000 for m in first_words]
    assert clips[0].duration_us == (1840 - 240) * 1000


def test_standard_chunks_split_a_long_scene_at_five_words():
    w = g.words(12)
    scenes = [g.scene("1", start_word=0, end_word=11, start_ms=240)]
    tl = _timeline(scenes=scenes, words=w, style="standard")
    clips = [t for t in plan_draft(tl, {**_media(tl), "images/1.jpg": MediaInfo(1080, 1920)}).texts if t.track == "captions"]
    assert [c.text for c in clips] == ["w0 w1 w2 w3 w4", "w5 w6 w7 w8 w9", "w10 w11"]
    assert clips[0].duration_us == (w[5].start_ms - w[0].start_ms) * 1000


def test_numbers_in_captions_use_the_spelled_out_display_text():
    words = g.words(4)
    words[1] = words[1].model_copy(update={"word": "100000"})
    scenes = [g.scene("1", start_word=0, end_word=3, start_ms=240)]
    tl = _timeline(scenes=scenes, words=words, style="punch")
    clips = [t for t in plan_draft(tl, {**_media(tl), "images/1.jpg": MediaInfo(1080, 1920)}).texts if t.track == "captions"]
    assert clips[1].text == "ONE HUNDRED THOUSAND"


def test_no_caption_clips_when_captions_are_off_or_not_word_synced():
    tl = _timeline()
    tl["captions_enabled"] = False
    assert [t for t in plan_draft(tl, _media(tl)).texts if t.track == "captions"] == []
    tl = _timeline()
    tl["captions_source"] = "script"
    assert [t for t in plan_draft(tl, _media(tl)).texts if t.track == "captions"] == []


# ── Audio ─────────────────────────────────────────────────────────────────────


def test_sfx_sits_at_its_scene_offset_with_the_timelines_delay():
    tl = _timeline()
    media = _media(tl)
    scenes = [
        g.scene("1", sfx="whoosh", start_word=0, end_word=3, start_ms=240),
        g.scene("2", sfx="whoosh", text="Big", text_type="stat", start_word=4, end_word=7, start_ms=1840),
        g.scene("3", start_word=8, end_word=11, start_ms=3440),
    ]
    tl = _timeline(scenes=scenes)
    sfx = [a for a in plan_draft(tl, media).audio if a.track == "sfx"]
    assert [a.start_us for a in sfx] == [0, 1_600_000 + 700_000]   # scene 2 starts 1.6s in; text → +0.7s
    assert [a.start_us for a in sfx] == [s["sfx_delay_ms"] * 1000 for s in tl["scenes"] if s["sfx_key"]]


def test_missing_optional_audio_is_skipped_with_a_warning():
    tl = _timeline()
    media = _media(tl)
    del media["sfx/whoosh.mp3"], media["music/bed.mp3"]
    plan = plan_draft(tl, media)
    assert [a.track for a in plan.audio] == ["voiceover"]
    assert len(plan.warnings) == 2


def test_a_missing_voiceover_or_scene_file_stops_the_export():
    tl = _timeline()
    media = _media(tl)
    del media["voiceover/vo.mp3"]
    with pytest.raises(TimelineError, match="voiceover"):
        plan_draft(tl, media)
    media = _media(tl)
    del media["images/2.jpg"]
    with pytest.raises(TimelineError, match="Scene 2"):
        plan_draft(tl, media)


def test_music_volume_ducking_and_fit_mode():
    tl = _timeline()
    tl["music_volume"], tl["music_ducking"], tl["music_playback_mode"] = 20, False, "fit"
    music = [a for a in plan_draft(tl, _media(tl)).audio if a.track == "music"]
    assert [(a.start_us, a.duration_us, a.volume) for a in music] == [(0, 3 * US, pytest.approx(0.2))]
    tl["music_ducking"] = True
    music = [a for a in plan_draft(tl, _media(tl)).audio if a.track == "music"]
    assert music[0].volume == pytest.approx(0.2 * 0.4)


def test_music_loop_mode_repeats_until_the_voiceover_ends():
    tl = _timeline()
    tl["music_playback_mode"] = "loop"
    vo = int(tl["voiceover_duration_s"] * US)
    music = [a for a in plan_draft(tl, _media(tl)).audio if a.track == "music"]
    assert music[0].start_us == 0 and music[1].start_us == 3 * US
    assert sum(a.duration_us for a in music) == vo
    assert all(a.start_us + a.duration_us <= vo for a in music)


def test_overlapping_clips_get_their_own_tracks():
    a = dp.AudioClipPlan("sfx", "a", 0, 500, 1.0)
    b = dp.AudioClipPlan("sfx", "b", 300, 500, 1.0)
    c = dp.AudioClipPlan("sfx", "c", 600, 100, 1.0)
    tracks = dp.assign_tracks([b, c, a], "sfx")
    assert list(tracks) == ["sfx", "sfx 2"]
    assert [x.path for x in tracks["sfx"]] == ["a", "c"] and [x.path for x in tracks["sfx 2"]] == ["b"]


# ── Schema version and the zip ───────────────────────────────────────────────


def test_unknown_schema_version_stops_with_a_clear_message():
    tl = _timeline()
    tl["schema_version"] = 99
    with pytest.raises(TimelineError, match="schema version 99.*understands 1"):
        plan_draft(tl, _media(tl))
    assert "CapCut 8.9.1" in dp.TESTED_WITH


def _zip(timeline: dict, files: dict[str, bytes] | None = None) -> bytes:
    """A zip holding timeline.json and the given files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("timeline.json", json.dumps(timeline))
        for name, data in (files or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_unpack_extracts_the_media_next_to_the_run_and_returns_the_timeline(tmp_path):
    tl = _timeline()
    z = tmp_path / "x.zip"
    z.write_bytes(_zip(tl, {"images/1.jpg": b"J"}))
    out = ec.unpack(z, tmp_path / "media")
    assert out["run_id"] == "gold1"
    assert (tmp_path / "media" / "gold1" / "images" / "1.jpg").read_bytes() == b"J"


def test_unpack_refuses_a_zip_without_a_timeline_or_with_an_unknown_schema(tmp_path):
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").writestr("other.txt", "x")
    (tmp_path / "a.zip").write_bytes(buf.getvalue())
    with pytest.raises(TimelineError, match="no timeline.json"):
        ec.unpack(tmp_path / "a.zip", tmp_path / "m")
    tl = _timeline()
    tl["schema_version"] = 7
    (tmp_path / "b.zip").write_bytes(_zip(tl))
    with pytest.raises(TimelineError, match="schema version 7"):
        ec.unpack(tmp_path / "b.zip", tmp_path / "m")


def test_main_reports_an_unknown_schema_without_needing_pycapcut(tmp_path, capsys):
    tl = _timeline()
    tl["schema_version"] = 7
    (tmp_path / "b.zip").write_bytes(_zip(tl))
    assert ec.main([str(tmp_path / "b.zip"), "--media-dir", str(tmp_path / "m")]) == 1
    assert "schema version 7" in capsys.readouterr().err


def test_draft_files_keep_only_the_name_capcut_8_reads(tmp_path):
    (tmp_path / "draft_content.json").write_text("{}")
    ec.finish_draft_files(tmp_path, both_files=False)
    assert (tmp_path / "draft_info.json").exists() and not (tmp_path / "draft_content.json").exists()
    (tmp_path / "draft_content.json").write_text("{}")
    ec.finish_draft_files(tmp_path, both_files=True)
    assert (tmp_path / "draft_info.json").exists() and (tmp_path / "draft_content.json").exists()
