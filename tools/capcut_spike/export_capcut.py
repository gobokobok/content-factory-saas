"""Spike: build a CapCut draft from one Content Factory run (storyboard + assets + VO + word timings)."""
import os
import shutil
import sys

import pycapcut as cc
from pycapcut import KeyframeProperty as KP
from pycapcut import trange
from r2 import BUCKET, get_json, latest, s3

RUN = sys.argv[1]
BUNDLE = os.path.expanduser(f"~/Movies/ContentFactory/{RUN[:8]}")
DRAFTS = os.path.expanduser("~/Movies/CapCut/User Data/Projects/com.lveditor.draft")
NAME = f"CF_{RUN[:8]}"
W, H = 1080, 1920
US = 1000  # ms -> microseconds

def fetch(key):
    """Download one R2 object into the bundle folder and return its local path."""
    dest = os.path.join(BUNDLE, key.split(f"runs/{RUN}/", 1)[1])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        s3.download_file(BUCKET, key, dest)
    return dest

sb = get_json(latest(RUN, "storyboard", "verified_storyboard"))
sb = sb.get("body", sb)["storyboard"]
man = get_json(latest(RUN, "acquisition", "asset_manifest"))
man = man.get("body", man)
entries = {str(e["scene_id"]): e for e in man.get("manifest", man)["entries"]}
va = get_json(latest(RUN, "voice", "voice_alignment"))
va = va.get("body", va)
words, total_ms = va["word_timestamps"], int(va["total_duration_s"] * 1000)
scenes = sb["scenes"]

script = cc.DraftFolder(DRAFTS).create_draft(NAME, W, H, fps=30, allow_replace=True)
for kind, name in [(cc.TrackType.video, "footage"), (cc.TrackType.audio, "voiceover"),
                   (cc.TrackType.text, "on_screen_text"), (cc.TrackType.text, "captions")]:
    script.add_track(kind, name)

report = []
for i, sc in enumerate(scenes):
    start = 0 if i == 0 else sc["scene_start_ms"]
    end = scenes[i + 1]["scene_start_ms"] if i + 1 < len(scenes) else total_ms
    dur = end - start
    path = fetch(entries[str(sc["scene"])]["file_key"])
    mat = cc.VideoMaterial(path)
    # CapCut fits media inside the canvas; scale up so it covers 9:16 like the FFmpeg render does.
    cover = max((W / H) / (mat.width / mat.height), (mat.width / mat.height) / (W / H))
    is_still = mat.material_type == "photo"
    src = None if is_still else trange(0, min(dur * US, mat.duration))
    seg = cc.VideoSegment(mat, trange(start * US, dur * US), source_timerange=src, volume=0.0,
                          clip_settings=cc.ClipSettings(scale_x=cover, scale_y=cover))
    fx = sc.get("motion_effect") if is_still else None
    fitted_w = min(1.0, (mat.width / mat.height) / (W / H))  # width fraction after CapCut's fit-inside
    overflow = max(0.0, cover * fitted_w - 1.0)  # lateral headroom per side, in half-canvas-width units
    if fx in ("zoom_in", "ken_burns"):
        seg.add_keyframe(KP.uniform_scale, 0, cover).add_keyframe(KP.uniform_scale, dur * US, cover * 1.15)
    elif fx == "zoom_out":
        seg.add_keyframe(KP.uniform_scale, 0, cover * 1.15).add_keyframe(KP.uniform_scale, dur * US, cover)
    elif fx in ("pan_right", "pan_left") and overflow > 0:
        a, b = (overflow, -overflow) if fx == "pan_right" else (-overflow, overflow)
        seg.add_keyframe(KP.position_x, 0, a).add_keyframe(KP.position_x, dur * US, b)
    script.add_segment(seg, "footage")
    if sc.get("on_screen_text"):
        script.add_segment(cc.TextSegment(
            sc["on_screen_text"], trange(start * US, dur * US),
            style=cc.TextStyle(size=11.0, bold=True, align=1, auto_wrapping=True, max_line_width=0.8),
            background=cc.TextBackground(color="#000000", alpha=0.75, round_radius=0.2),
            clip_settings=cc.ClipSettings(transform_y=0.4)), "on_screen_text")
    report.append((sc["scene"], os.path.basename(path), mat.material_type, f"{mat.width}x{mat.height}", dur, fx, bool(sc.get("on_screen_text"))))

vo = cc.AudioMaterial(fetch(va["mp3_r2_key"]))
script.add_segment(cc.AudioSegment(vo, trange(0, min(vo.duration, total_ms * US))), "voiceover")

# "Punch" captions: one upper-cased word at a time, each an editable text clip.
cursor = 0
for j, w in enumerate(words):
    w_start = max(w["start_ms"], cursor)
    w_end = max(words[j + 1]["start_ms"] if j + 1 < len(words) else w["end_ms"], w_start + 80)
    cursor = w_end
    script.add_segment(cc.TextSegment(
        w["word"].upper(), trange(w_start * US, (w_end - w_start) * US),
        style=cc.TextStyle(size=18.0, bold=True, align=1),
        border=cc.TextBorder(color=(0.0, 0.0, 0.0), width=40.0),
        clip_settings=cc.ClipSettings(transform_y=-0.25)), "captions")

script.save()
# CapCut 8.x names the project file draft_info.json; pyCapCut writes the older draft_content.json name.
shutil.copyfile(os.path.join(DRAFTS, NAME, "draft_content.json"), os.path.join(DRAFTS, NAME, "draft_info.json"))
print("draft:", os.path.join(DRAFTS, NAME))
print("bundle:", BUNDLE)
for r in report:
    print("  scene", *r)
print("captions:", len(words), "| total_ms:", total_ms)
