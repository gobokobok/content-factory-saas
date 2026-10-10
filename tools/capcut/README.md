# CapCut export — laptop script

Turns the zip you download from Studio ("Download for CapCut") into a CapCut draft with
the whole edit in place: footage with scene timing, motion as keyframes, voiceover, music,
SFX at their scene offsets, on-screen text and editable captions.

Needs no credentials and no network: everything is in the zip. Decision: D100 / D103.

Tested with **CapCut 8.9.1 (macOS)** and **pycapcut 0.0.3**.

## One-time setup

```bash
cd tools/capcut
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.9+ is enough. `pycapcut` lives only here — it is not part of the platform.

## Every run

1. In Studio, open the run's **Video** stage and press **Download for CapCut**. The button
   opens once every scene has a file and the run has a voiceover.
2. Close CapCut (it only reads new drafts when it starts).
3. Run:

   ```bash
   cd tools/capcut && source .venv/bin/activate
   python export_capcut.py ~/Downloads/capcut_1a2b3c4d.zip
   ```

4. Open CapCut. The draft `CF_1a2b3c4d` is in your projects. Edit, then export the video.
5. Back in Studio, **Upload video from CapCut**. The run now continues to Metadata as after an
   FFmpeg render.

The media is unpacked to `~/Movies/ContentFactory/<run id>/` and the draft points at those
files, so keep that folder while you edit. Re-running the command for the same zip replaces
the draft (and any edits you made to it).

### Options

| Option | Default | Meaning |
|---|---|---|
| `--drafts-dir` | `~/Movies/CapCut/User Data/Projects/com.lveditor.draft` | CapCut's draft folder |
| `--media-dir` | `~/Movies/ContentFactory` | where the zip's media is unpacked |
| `--name` | `CF_<run id>` | draft name |
| `--both-files` | off | also keep `draft_content.json` (see below) |

## What ends up in the draft

| Track | Contents |
|---|---|
| `footage` | one clip per scene at its timeline position. Stills are scaled to cover the canvas and carry motion keyframes: ken burns 1%/s, zoom 2%/s, pan up to 12% of the width per second, with at least 10% of the width to travel across — a picture short of that is enlarged (the FFmpeg render's rates). Video clips are trimmed to the scene and muted, with no keyframes. |
| `voiceover` | the voiceover from 0:00 |
| `music` | the music at the run's volume (×0.4 with ducking), looped or played once as the run's setting says |
| `sfx` | each SFX at its scene offset (+0.7 s when the scene has on-screen text); overlapping hits get their own track |
| `on_screen_text` | the scene's text, upper case, from 0.3 s into the scene to its end |
| `captions` | editable text clips. **Punch:** one upper-case word per clip. **Standard:** one clip per rolling 5-word line. |

Canvas size follows the run: 1080×1920 for 9:16, 1920×1080 for 16:9.

Known differences from the FFmpeg render: Standard captions do not highlight the active word
(a CapCut text clip takes one style); on-screen text does not slide in; the blur-fill for person
portraits is not reproduced; fonts are CapCut's defaults. Adjust in CapCut.

## Which file does CapCut read?

pycapcut writes `draft_content.json` (CapCut 6.x's name). CapCut 8.9.1 works on `draft_info.json`:
in the spike's draft CapCut re-saved `draft_info.json` (and a `.bak`) while `draft_content.json`
stayed as written, and the drafts CapCut creates itself have no `draft_content.json`. The script
therefore renames the file and leaves only `draft_info.json`. If you run a CapCut that does not
list the draft, try `--both-files`.

## When CapCut updates and the draft no longer opens

CapCut has no official API; the draft format is undocumented and an update can change it.

1. Check whether pycapcut has a newer release: `pip install -U pycapcut`, and re-run the command.
   If it works, change the pin in `requirements.txt` and update the "Tested with" line here and
   in `draft_plan.py` (`TESTED_WITH`).
2. Try `--both-files`.
3. If CapCut still does not show or open the draft, you can finish the video the other way:
   the FFmpeg render in Studio is unaffected by anything here.
4. Do not edit `timeline.json`. If the script says it does not understand the timeline's schema
   version, `git pull` the project and download the zip again.
