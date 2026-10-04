#!/bin/bash
# ============================================================
# Content Factory — FFmpeg assembly script
# run_id:          gold1
# generated_at: <masked>
# scenes:          6
# total_duration:  20.5s
# ============================================================
set -euo pipefail

BASE="/tmp/gold1"
WORK="$BASE/work"
mkdir -p "$WORK" "$BASE/output"

# ── Voiceover ─────────────────────────────────────────────
VO=""
for _vo_f in "$BASE/voiceover/"*.mp3 "$BASE/voiceover/"*.wav "$BASE/voiceover/"*.m4a; do
  [ -f "$_vo_f" ] && { VO="$_vo_f"; break; }
done
if [ -z "$VO" ]; then
  echo "ERROR: no audio file (.mp3/.wav/.m4a) found in $BASE/voiceover/ — upload voiceover before rendering" >&2
  exit 1
fi
echo "Voiceover: $VO"

# ── Background music ───────────────────────────────────────
MUSIC=""
for _m_f in "$BASE/music/"*.mp3 "$BASE/music/"*.wav "$BASE/music/"*.m4a; do
  [ -f "$_m_f" ] && { MUSIC="$_m_f"; break; }
done
if [ -z "$MUSIC" ]; then
  echo "WARNING: no music found in $BASE/music/ — rendering without background music"
  MUSIC_ARGS=(-f lavfi -i anullsrc=r=44100:cl=stereo)
else
  MUSIC_ARGS=(-i "$MUSIC")
fi
echo "Music: ${MUSIC:-<none — using anullsrc silence>}"

# ── Pre-flight diagnostics ─────────────────────────────
echo "=== PRE-FLIGHT CHECK ==="
ffmpeg -version 2>&1 | head -1 || echo "ffmpeg not in PATH"
echo "VO=$VO"
test -f "$VO" && echo "VO: $(wc -c < "$VO") bytes" || echo "VO: NOT FOUND"
echo "MUSIC=$MUSIC"
test -f "$MUSIC" && echo "MUSIC: exists" || echo "MUSIC: NOT FOUND"
echo "video/:  $(ls "$BASE/video/"  2>/dev/null || echo "(empty or missing)")"
echo "images/: $(ls "$BASE/images/" 2>/dev/null || echo "(empty or missing)")"
echo "=== END PRE-FLIGHT ==="

# ── Per-scene processing (parallel, ≤4 concurrent) ──────────
_JOBS=(); _MAX=4

# Scene 01 — 1 — still_with_motion (ken_burns) — 2.5s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/1.jpg" \
  -t 2.48 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='1+0.01*on/25':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=62:s=1080x1920,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_01.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

# Scene 02 — 2 — still_with_motion (zoom_in) — 2.87s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/2.jpg" \
  -t 2.88 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='1+0.02*on/25':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=72:s=1080x1920,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_02.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

# Scene 03 — 3 — still_with_motion (zoom_out) — 3.24s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/3.jpg" \
  -t 3.24 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='1.0648-0.02*on/25':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=81:s=1080x1920,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_03.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

# Scene 04 — 4 — still_with_motion (pan_right) — 3.61s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/4.jpg" \
  -t 3.6 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:x='(iw-1080)/2-min(max(0\,iw-1080)\,466.6)/2+min(max(0\,iw-1080)\,466.6)*t/3.6000':y=0,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_04.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

# Scene 05 — 5 — still_with_motion (pan_left) — 3.98s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/5.jpg" \
  -t 4.0 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:x='(iw-1080)/2+min(max(0\,iw-1080)\,518.4)/2-min(max(0\,iw-1080)\,518.4)*t/4.0000':y=0,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_05.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

# Scene 06 — 6 — still_with_motion (static) — 4.35s
ffmpeg -y -filter_threads 2 -loop 1 -framerate 25 -i "/tmp/gold1/images/6.jpg" \
  -t 4.36 \
  -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='1.0':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=109:s=1080x1920,fps=25,setsar=1:1" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an -threads 2 \
  -video_track_timescale 25 \
  "$WORK/scene_06.mp4" &
_JOBS+=($!)
if [ ${#_JOBS[@]} -ge $_MAX ]; then
  for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
  _JOBS=()
fi

for _pid in "${_JOBS[@]}"; do wait "$_pid" || exit 1; done
unset _JOBS _MAX

# ── Concatenate scenes (concat demuxer + re-encode) ────────────────
rm -f "$WORK/filelist.txt"
echo "file '$WORK/scene_01.mp4'" >> "$WORK/filelist.txt"
echo "file '$WORK/scene_02.mp4'" >> "$WORK/filelist.txt"
echo "file '$WORK/scene_03.mp4'" >> "$WORK/filelist.txt"
echo "file '$WORK/scene_04.mp4'" >> "$WORK/filelist.txt"
echo "file '$WORK/scene_05.mp4'" >> "$WORK/filelist.txt"
echo "file '$WORK/scene_06.mp4'" >> "$WORK/filelist.txt"
ffmpeg -y \
  -f concat -safe 0 \
  -i "$WORK/filelist.txt" \
  -r 25 \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \
  "$WORK/video_only.mp4"

# ── Pad video to match voiceover duration ───────────────────
_VID_DUR=$(ffprobe -v quiet -print_format json -show_format "$WORK/video_only.mp4" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['format']['duration'])" 2>/dev/null || echo 0)
_VO_DUR=$(ffprobe -v quiet -print_format json -show_format "$VO" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['format']['duration'])" 2>/dev/null || echo 0)
_PAD=$(python3 -c "v=float('$_VID_DUR'); a=float('$_VO_DUR'); print(max(0.0, a - v))")
echo "Pad: video=${_VID_DUR}s  vo=${_VO_DUR}s  pad=${_PAD}s"
if python3 -c "import sys; sys.exit(0 if float('$_PAD') > 0.1 else 1)"; then
  ffmpeg -y -i "$WORK/video_only.mp4" \
    -vf "tpad=stop=-1:stop_mode=clone:stop_duration=$_PAD" \
    -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p \
    "$WORK/video_padded.mp4"
else
  cp "$WORK/video_only.mp4" "$WORK/video_padded.mp4"
fi

# ── Write voiceover_captions.ass ──────────────────────────
cat << '__VCAP_EOF__' > "$WORK/voiceover_captions.ass"
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: VoiceCaption,Titillium Web SemiBold,80,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,110,110,576,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.50,VoiceCaption,,0,0,0,,line for scene one
Dialogue: 0,0:00:02.50,0:00:05.37,VoiceCaption,,0,0,0,,line for scene two
Dialogue: 0,0:00:05.37,0:00:08.61,VoiceCaption,,0,0,0,,line for scene three
Dialogue: 0,0:00:08.61,0:00:12.22,VoiceCaption,,0,0,0,,line for scene four
Dialogue: 0,0:00:12.22,0:00:16.20,VoiceCaption,,0,0,0,,line for scene five
Dialogue: 0,0:00:16.20,0:00:20.55,VoiceCaption,,0,0,0,,line for scene six
__VCAP_EOF__

# ── Post-process: captions + grade + overlays (single pass) ─
ffmpeg -y \
  -i "$WORK/video_padded.mp4" \
  -vf "ass=$WORK/voiceover_captions.ass" \
  -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p -an \
  "$WORK/video_postproc.mp4"

# ── Audio assembly ─────────────────────────────────────────
# SFX inputs are conditional — only include files present at render time
_sfx_inputs=()
_sfx_filters=""
_sfx_labels=""
_sfx_n=3
_n_audio=2

# Trim video to VO duration so accumulated scene-duration drift never extends the output
VO_DURATION=$(ffprobe -v quiet -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$VO")
ffmpeg -y \
  -t "$VO_DURATION" \
  -i "$WORK/video_postproc.mp4" \
  -i "$VO" \
  "${MUSIC_ARGS[@]}" \
  "${_sfx_inputs[@]}" \
  -filter_complex "[1:a]asetpts=PTS-STARTPTS,volume=1.0[vo];[2:a]asetpts=PTS-STARTPTS,volume=0.150[music]${_sfx_filters};[vo][music]${_sfx_labels}amix=inputs=${_n_audio}:duration=first:normalize=0[aout]" \
  -map 0:v -map "[aout]" \
  -c:v copy -c:a aac -b:a 192k \
  "$BASE/output/final.mp4"

echo "Done: /tmp/gold1/output/final.mp4"
