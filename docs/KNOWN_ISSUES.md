# Content Factory — Known Issues Log

Issues observed during smoke testing, with root cause and resolution status.

---

## KI-001 — Music starts ~5 seconds late instead of at t=0
**Observed:** 2026-05-23 (first end-to-end smoke test)
**Status:** Fixed in commit `fix: add asetpts=PTS-STARTPTS to VO and music inputs...`

### Symptom
Background music (and potentially voiceover) audibly begins several seconds into the
rendered video rather than at t=0, despite the video visuals starting immediately.

### Root cause
MP3 files cut from longer tracks frequently encode a non-zero `start_time` value in their
container metadata (e.g. `start_time=5.123`). Without an explicit PTS reset in the FFmpeg
filter chain, FFmpeg honours this offset and pads silence from `t=0` to `t=start_time`
before the audio begins — even though the audio data itself is intact from the start of
the file.

The original `_audio_section()` filter_complex applied `volume` directly to the raw input
streams:

```
[1:a]volume=1.0[vo];[2:a]volume=0.15[music]...
```

### Fix
`asetpts=PTS-STARTPTS` prepended to both VO and music inputs, stripping the container
start_time and forcing PTS to begin at 0:

```
[1:a]asetpts=PTS-STARTPTS,volume=1.0[vo];[2:a]asetpts=PTS-STARTPTS,volume=0.15[music]...
```

`adelay` was confirmed **not** applied to inputs 1 or 2 — it is only used for SFX inputs
(index 3+) where a deliberate scene-offset delay is intentional.

### Regression guard
`test_audio_inputs_reset_pts_to_prevent_start_time_offset` in `tests/test_ffmpeg_builder.py`
asserts the exact filter substrings are present.

---
