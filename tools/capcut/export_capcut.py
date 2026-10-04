#!/usr/bin/env python3
"""Build a CapCut draft from a Content Factory export zip (P13b-S3, D100).

    python export_capcut.py ~/Downloads/capcut_1a2b3c4d.zip

Unpacks the zip next to your other media, reads `timeline.json`, and writes a draft to
CapCut's project folder: footage with scene timing and motion keyframes, voiceover,
music, SFX at their scene offsets, on-screen text and editable captions. Needs no
credentials and no network — everything is in the zip. See README.md for setup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

from draft_plan import (
    TESTED_WITH,
    DraftPlan,
    MediaInfo,
    TimelineError,
    assign_tracks,
    check_schema,
    plan_draft,
)

DEFAULT_DRAFTS_DIR = "~/Movies/CapCut/User Data/Projects/com.lveditor.draft"
DEFAULT_MEDIA_DIR = "~/Movies/ContentFactory"


def unpack(zip_path: Path, media_root: Path) -> dict:
    """Extract the zip into media_root/<run>/ and return the parsed timeline.json."""
    with zipfile.ZipFile(zip_path) as zf:
        try:
            timeline = json.loads(zf.read("timeline.json"))
        except KeyError:
            raise TimelineError(f"{zip_path.name} has no timeline.json — is it a Content Factory CapCut export?") from None
        check_schema(timeline)
        target = media_root / timeline["run_id"][:8]
        zf.extractall(target)
    return timeline


def measure(pc, run_dir: Path, timeline: dict) -> dict[str, MediaInfo]:
    """Measure every media file the timeline lists (size and length) with pycapcut."""
    info: dict[str, MediaInfo] = {}
    for scene in timeline["scenes"]:
        path = scene["asset_path"]
        if (run_dir / path).exists() and path not in info:
            material = pc.VideoMaterial(str(run_dir / path))
            info[path] = MediaInfo(material.width, material.height, material.duration)
    audio_paths = [timeline.get("voiceover_path"), timeline.get("music_path")]
    audio_paths += [s.get("sfx_path") for s in timeline["scenes"]]
    for path in audio_paths:
        if path and (run_dir / path).exists() and path not in info:
            info[path] = MediaInfo(duration_us=pc.AudioMaterial(str(run_dir / path)).duration)
    return info


def write_draft(pc, plan: DraftPlan, run_dir: Path, drafts_dir: Path, name: str, both_files: bool) -> Path:
    """Write the plan to a CapCut draft folder with pycapcut and return its path."""
    from pycapcut import KeyframeProperty as KP
    from pycapcut import trange

    keyframe_props = {"uniform_scale": KP.uniform_scale, "position_x": KP.position_x}
    script = pc.DraftFolder(str(drafts_dir)).create_draft(name, plan.width, plan.height, fps=plan.fps, allow_replace=True)

    footage = assign_tracks(plan.video, "footage")
    texts = {
        base: assign_tracks([t for t in plan.texts if t.track == base], base) for base in ("on_screen_text", "captions")
    }
    audio = {
        base: assign_tracks([a for a in plan.audio if a.track == base], base) for base in ("voiceover", "music", "sfx")
    }
    for names, kind in (
        (footage, pc.TrackType.video),
        *((t, pc.TrackType.text) for t in texts.values()),
        *((a, pc.TrackType.audio) for a in audio.values()),
    ):
        for track_name in names:
            script.add_track(kind, track_name)

    for track_name, clips in footage.items():
        for clip in clips:
            material = pc.VideoMaterial(str(run_dir / clip.path))
            source = trange(0, clip.source_duration_us) if clip.source_duration_us else None
            segment = pc.VideoSegment(
                material, trange(clip.start_us, clip.duration_us), source_timerange=source, volume=0.0,
                clip_settings=pc.ClipSettings(scale_x=clip.scale, scale_y=clip.scale),
            )
            for kf in clip.keyframes:
                segment.add_keyframe(keyframe_props[kf.prop], kf.time_us, kf.value)
            script.add_segment(segment, track_name)

    for by_track in texts.values():
        for track_name, clips in by_track.items():
            for clip in clips:
                script.add_segment(pc.TextSegment(
                    clip.text, trange(clip.start_us, clip.duration_us),
                    style=pc.TextStyle(
                        size=clip.size, bold=clip.bold, color=clip.color, align=1,
                        auto_wrapping=True, max_line_width=clip.max_line_width,
                    ),
                    border=pc.TextBorder(color=(0.0, 0.0, 0.0), width=40.0) if clip.border else None,
                    background=(
                        pc.TextBackground(color=clip.background[0], alpha=clip.background[1], round_radius=0.2)
                        if clip.background else None
                    ),
                    clip_settings=pc.ClipSettings(transform_y=clip.transform_y),
                ), track_name)

    for by_track in audio.values():
        for track_name, clips in by_track.items():
            for clip in clips:
                material = pc.AudioMaterial(str(run_dir / clip.path))
                script.add_segment(pc.AudioSegment(
                    material, trange(clip.start_us, clip.duration_us),
                    source_timerange=trange(0, clip.duration_us), volume=clip.volume,
                ), track_name)

    script.save()
    return finish_draft_files(drafts_dir / name, both_files)


def finish_draft_files(draft_dir: Path, both_files: bool) -> Path:
    """Leave the project file under the name CapCut 8.x reads.

    pyCapCut writes `draft_content.json` (the CapCut 6.x name). CapCut 8.9.1 reads and
    re-saves `draft_info.json`, and drafts CapCut creates itself carry only that file
    (see README, "Which file does CapCut read?"), so the file is renamed. With
    both_files=True the old name is kept too, as a fallback for other CapCut versions.
    """
    content, info = draft_dir / "draft_content.json", draft_dir / "draft_info.json"
    if content.exists():
        if both_files:
            shutil.copyfile(content, info)
        else:
            content.replace(info)
    return draft_dir


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description="Build a CapCut draft from a Content Factory export zip.")
    parser.add_argument("zip", type=Path, help="the capcut_*.zip downloaded from Studio")
    parser.add_argument("--drafts-dir", type=Path, default=Path(DEFAULT_DRAFTS_DIR).expanduser(),
                        help="CapCut's draft folder (default: %(default)s)")
    parser.add_argument("--media-dir", type=Path, default=Path(DEFAULT_MEDIA_DIR).expanduser(),
                        help="where the zip's media is unpacked; the draft points at these files (default: %(default)s)")
    parser.add_argument("--name", help="draft name (default: CF_<run id>)")
    parser.add_argument("--both-files", action="store_true",
                        help="also keep draft_content.json (for CapCut versions that read the old name)")
    args = parser.parse_args(argv)

    try:
        timeline = unpack(args.zip.expanduser(), args.media_dir)
    except (TimelineError, zipfile.BadZipFile, OSError) as exc:
        print(f"Cannot read the export: {exc}", file=sys.stderr)
        return 1

    try:
        import pycapcut as pc
    except ImportError:
        print("pycapcut is not installed. Run:  pip install -r requirements.txt  (see README.md)", file=sys.stderr)
        return 2

    if not args.drafts_dir.is_dir():
        print(
            f"CapCut's draft folder was not found: {args.drafts_dir}\n"
            "Open CapCut once so it creates it, or pass --drafts-dir with the right path.",
            file=sys.stderr,
        )
        return 1

    try:
        run_dir = args.media_dir / timeline["run_id"][:8]
        plan = plan_draft(timeline, measure(pc, run_dir, timeline))
        name = args.name or f"CF_{timeline['run_id'][:8]}"
        draft = write_draft(pc, plan, run_dir, args.drafts_dir, name, args.both_files)
    except TimelineError as exc:
        print(f"Cannot build the draft: {exc}", file=sys.stderr)
        return 1

    print(f"Draft:  {draft}")
    print(f"Media:  {run_dir}")
    print(f"Tested with {TESTED_WITH}. Open CapCut — the draft '{name}' is in your projects.")
    print(f"{len(plan.video)} scenes, {len(plan.texts)} text clips, {len(plan.audio)} audio clips")
    for warning in plan.warnings:
        print(f"  warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
