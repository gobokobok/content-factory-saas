# Backlog — Active Stories

_Contains the last completed sprint (P13b), the previous one (P13 — moves to BACKLOG.md at the next sprint boundary), the outlines for P14–P17, and open unassigned stories. Everything older is in BACKLOG.md._
_Updated at each sprint boundary: move the completed sprint's block to BACKLOG.md._

---

## Platform Update outlines — Sprints P14–P17 (not yet detailed)

Detailed at each sprint boundary. Spec section numbers refer to the Pipeline & Platform Update specification (2026-10-03).

**EPIC 44 — Storyboard control (P13)** — done 2026-10-03: see the EPIC 44 section below. Open for P13b: whether split / merge and asset strategy need anything extra in the CapCut timeline file (new scene fields: `asset_strategy`; manifest: `asset_slot`, status `awaiting_upload`).

**EPIC 49 — CapCut export (P13b, D100)** — done 2026-10-04: stories P13b-S1..S4 in the EPIC 49 section below.

**EPIC 45 — AI Created style (P14, D096, spec §8, 11, 12).** Opens with the side-by-side provider test from D096. `ImageProvider` interface, kie.ai implementation, generated images stored in the run's R2 folder. New style option with a general visual prompt / mood in Settings. Visual Director prompt branch: for this style it writes a per-scene visual prompt from the scene's voiceover plus the global mood, instead of stock keywords. Per-scene "AI image" option with an editable prompt, usable in any style. Open: keeping a consistent look across scenes (style reference image vs. prompt only); per-run spend cap.

**EPIC 46 — Research (P15, D094, D097, spec §2–5).** Project research page. Trend research: existing Google Trends, Reddit and YouTube adapters (D050) plus Google News, over a chosen time window, producing ~10 topics each with a summary and the evidence for why it is trending. Competitor research: port from `content-researcher` (D097), project-level channel list, publications from the last 24/48 hours with likes per 1,000 views and outlier score, daily snapshot job. Results are ticked into the shortlist with their evidence. Open: orchestrator-with-specialists vs. parallel agents with a synthesis step (spec §26 D); **X.com** — ENV.md records it as excluded under the free-tier constraint, so including it needs a decision on a paid source.

**EPIC 47 — Publishing via n8n (P16, D098, spec §18–21).** `channels` table (tenant level: name, platform, n8n channel key), project default channel, per-run destinations with publish time. Endpoints `due` / `claim` / `result`; API key for n8n. n8n workflow for YouTube (upload early with YouTube's own scheduled-publish time), exported JSON committed to the repo. Publication status in Studio's Metadata stage, replacing the disabled "Upload to channel" button; fills `published_videos`. Instagram as a second destination if time allows. Depends on the Google API audit started in P12.

**EPIC 48 — Server-side Auto Advance (P17, spec §22).** The Studio toggle hands the run to the server-side pipeline (`full_pipeline.py`, HITL gates from P6-S3) so it continues with the browser closed. First task: confirm that pipeline writes the same artifacts in the same places as the stage-by-stage Studio flow, so an auto-advanced run opens cleanly for review. Define which stages may run unattended, where it stops on error or missing input, and add OpenAI direct as the image fallback (D096). Optional: one-way Telegram notifications (D093). **From the 2026-10-03 prod check:** the PROD service sleeps after 6–10 idle minutes (Railway app sleeping) and pipeline work runs as in-process background tasks, so a run with the browser closed would be stopped mid-flight — settle this first (keep the service awake while a run is active, or move the work off the web process).

**EPIC 50 — Word-anchored overlays and a curated SFX library (unplanned, proposed 2026-10-04).** Select a word in a scene to say where the on-screen text appears and where an SFX plays, instead of the fixed rules (text 0.3 s into the scene, SFX at scene start or +0.7 s — D076). Plus a small SFX library of good-quality sounds. Stories E50-S1..S3 in the EPIC 50 section below; not placed in a sprint.

**Parked by D099:** P11-S2 motion presets (EPIC 39), P11-S3 sub-scene asset timeline (EPIC 38), Format tracks, Analytics & attribution.

---

## EPIC 49 — CapCut export (Sprint P13b)

Third sprint of the Pipeline & Platform Update (D100). A second render path from a finalized storyboard: Studio hands over a zip, a script on the operator's laptop writes a CapCut desktop project, and the video rendered in CapCut is uploaded back into the run. Delivered as one sprint (`/start-story P13b-S1..S4`).

**Design rules for the whole epic**
- The FFmpeg render on Railway is Path 1 and stays as it is: same endpoint, same output, same render script for the same inputs.
- One neutral timeline describes a finalized run. Both render paths read it; neither path re-derives timing, motion or captions on its own.
- Assets are addressed by the manifest's `file_key`. A path is never rebuilt from a scene id — scene ids are renumbered by split / merge and files are not moved (P13 Handover, D102).
- `pycapcut` is used only by the laptop script, with its own requirements file. It is not added to `requirements.txt` or the Docker image (D100).
- CapCut has no official API and its draft format is undocumented (D100, Risks). The laptop script states which CapCut version it was tested with and fails with a clear message rather than writing a draft it cannot vouch for.
- Path 2 has no Auto Advance. Studio / REST only (D093). Plain HTML/JS.

---

## [P13b-S1] Neutral timeline artifact + render regression tests
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
One artifact — the timeline — describes everything a renderer needs for a finalized run: scenes with timing, the asset per scene, motion, on-screen text, caption words, voiceover, music and SFX. The FFmpeg script builder is rewired to read it. Before that rewiring, golden render-script tests pin today's output so the change is provably neutral.

### Acceptance Criteria
- [x] **Golden tests first.** Fixtures and expected render scripts for at least: still with each motion effect, stock video scene, operator-uploaded video on a still scene (D089), pan on a portrait still narrower than 9:16 (D091), 16:9, captions Standard and Punch, on-screen text, SFX and music present / absent. They are committed and green *before* the builder is changed
- [x] `Timeline` model (Pydantic) with a `schema_version`, covering per scene: scene id, start / end in ms, duration, asset `file_key` and kind (image / video), motion effect, on-screen text with its type and timing, SFX key and delay; and per run: aspect ratio and output size, caption style and caption words with timestamps, voiceover key and duration, music key and volume settings
- [x] `build_timeline(storyboard, manifest, voice_alignment, settings)` is a pure function (D040) and is the only place scene timing is resolved for rendering
- [x] The timeline is written as a versioned run artifact when a render is started and whenever it is requested by P13b-S2; `GET /platform/studio/runs/{run_id}/timeline` returns it, and 409 with `missing_assets_message` while any scene has no file
- [x] `_build_render_script` / `build_ffmpeg_script` take the timeline as their source for timing, assets, motion and overlays. **Every golden render script is byte-identical before and after**
- [x] **Word-index fix (noted in P13-S2):** the "live start_word boundaries" block resolves scene boundaries against the same normalised word list the StoryboardWorker indexes (`_normalize_deepgram_words`), not the raw alignment words. A test with a contraction-heavy script shows the scene cuts land on the storyboard's boundaries. If this changes a golden script, the difference is stated in the Handover
- [x] Tests: timeline from a storyboard with split / merged scenes and an `asset_slot`; `upload` scene without a file → 409; schema round-trip; the golden suite

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/render_worker.py` — `_build_render_script`, the "live start_word boundaries" block, `_build_captions_with_y_override`, `_collect_overlay_filters`, `missing_assets_message`, `_copy_music_to_run`, `_copy_all_scene_sfx_to_run`
- `src/ffmpeg_builder.py` — `build_ffmpeg_script`, `_scene_section`, `_motion_vf_prefix`, `_zoompan_filter`, `_audio_section`, `_local_path`
- `src/models.py` — `StoryboardScene`, `ManifestEntry` (`file_key`, `asset_slot`), `MOTION_EFFECTS`
- `cf_platform/interfaces/routes/workers.py` — render endpoint; `cf_platform/interfaces/routes/studio.py` — storyboard / manifest GET
- `tests/test_ffmpeg_builder.py`, `tests/cf_platform/p13_helpers.py`
- `DECISIONS.md` — D100, D102, D081, D087, D089, D091, D086


### Handover
- `cf_platform/workers/timeline.py`: `Timeline` model (`schema_version` 1) and `build_timeline(storyboard, manifest, voice_alignment, settings)`, the only place scene timing is resolved for rendering (D103). `render_worker` builds its script from the timeline (`build_render_script_from_timeline`); the timeline is written as run artifact `render/timeline@vN`. `GET /platform/studio/runs/{run_id}/timeline` returns it (409 with `missing_assets_message` while a scene has no file).
- Assets are addressed by manifest `file_key`, never by scene id (D102).
- 22 golden render scripts in `tests/golden/render/` (`test_p13b_s1_golden_render.py`, FFmpeg stubbed) were committed before the builder was rewired. Regenerate only on purpose: `UPDATE_GOLDEN=1 pytest tests/cf_platform/test_p13b_s1_golden_render.py` (docs/TESTING.md).
- Word-index fix: scene boundaries now resolve against the normalised word list (`_normalize_deepgram_words`). The contraction-heavy golden was pinned before the fix and changes on purpose; unchanged goldens stayed byte-identical.
- Known limits (D103): blur-fill for wikimedia portraits, Standard captions' per-word highlight, and the legacy `build_ffmpeg_script` still reads the storyboard directly.
- Files that mattered: `cf_platform/workers/timeline.py`, `cf_platform/workers/render_worker.py`, `src/ffmpeg_builder.py`, `tests/cf_platform/test_p13b_s1_golden_render.py`, `docs/ARCHITECTURE.md#0b`.

---

## [P13b-S2] "Download for CapCut" — zip of media and timeline
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 2
**Depends on:** P13b-S1

### Goal
From a run whose storyboard is finalized and whose assets are all in place, the operator downloads one zip holding the run's media and the timeline file.

### Acceptance Criteria
- [x] `GET /platform/studio/runs/{run_id}/export/capcut` returns a zip: `timeline.json` plus every file the timeline references (scene assets, voiceover, music, SFX), stored under the relative paths the timeline uses
- [x] The zip is streamed; it is not built in memory in one piece
- [x] 409 with the `missing_assets_message` text while any scene has no file; 409 when the run has no voice alignment
- [x] Studio: "Download for CapCut" next to the render action, enabled under the same conditions as rendering, using the blob-fetch download pattern (docs/UI_GUIDELINES.md, "File downloads")
- [x] The control states in one line that this path is rendered in CapCut on the laptop and the result is uploaded back
- [x] A TraceEvent records the export
- [x] Tests: zip contents match the timeline's references exactly; each 409; static-page test pins the control and the route it calls

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P13b-S1 Handover (timeline model and route)
- `cf_platform/workers/render_worker.py` — `_download_assets` (which files a render pulls)
- `cf_platform/interfaces/routes/studio.py` — video URL endpoints, scene upload (TraceEvent pattern)
- `src/static/studio-v2.html` — Render stage
- `docs/UI_GUIDELINES.md` — "File downloads"


### Handover
- `GET /platform/studio/runs/{run_id}/export/capcut` streams a zip of `timeline.json` plus every referenced file (`cf_platform/workers/capcut_export.py`, route in `studio.py`); 409 for missing assets or no voice alignment; a TraceEvent records the export. Studio: "Download for CapCut" next to Render (blob-fetch pattern).
- Files that mattered: `cf_platform/workers/capcut_export.py`, `cf_platform/interfaces/routes/studio.py`, `src/static/studio-v2.html` (Render stage), `tests/cf_platform/test_p13b_s2_export.py`.

---

## [P13b-S3] Laptop script and setup guide
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 3
**Depends on:** P13b-S1

### Goal
One command on the operator's laptop turns the downloaded zip into a CapCut project that opens with the whole edit in place. It replaces the spike, which read R2 directly and covered stills at 9:16 only.

### Acceptance Criteria
- [x] `tools/capcut/export_capcut.py <zip>` unpacks the zip and writes a CapCut draft from `timeline.json` alone — no R2 access, no credentials on the laptop
- [x] `tools/capcut/requirements.txt` holds `pycapcut` (pinned); nothing is added to the platform's requirements or image (D100)
- [x] Tracks: footage with scene timing, motion as keyframes (zoom in / out, Ken Burns, pan left / right), voiceover, on-screen text, captions as editable text clips in the run's caption style (Standard and Punch), **music, and SFX at their scene offsets**
- [x] **Video clips** are placed and trimmed to the scene duration, muted; no motion keyframes on video (D089)
- [x] **16:9** as well as 9:16: canvas size and cover scaling come from the timeline
- [x] The script checks the timeline's `schema_version` and reports the CapCut version it was tested with; on an unknown schema version it stops with a clear message
- [x] **Settle the spike's open point:** which of `draft_content.json` / `draft_info.json` CapCut 8.x reads. Record the finding in the Handover and write only what is needed (or both, with the reason)
- [x] `tools/capcut/README.md`: one-time setup (Python, virtual environment, requirements, where CapCut keeps drafts on macOS), the one command, and what to do when CapCut updates and the draft no longer opens
- [x] `tools/capcut_spike/` is removed once the new script covers it
- [x] Tests (run in CI without CapCut and without `pycapcut` installed in the platform image): the timeline → draft mapping is unit-tested on plain data — timing in microseconds, cover scale, keyframe values per motion effect, caption clip boundaries, SFX offsets
- [x] **Human touchpoint (with S2):** the operator downloads a zip from DEV, runs the command and opens the full edit in CapCut — one 9:16 run with a video clip, music and SFX, and one 16:9 run

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `tools/capcut_spike/export_capcut.py`, `tools/capcut_spike/r2.py`
- P13b-S1 Handover (timeline schema)
- `src/ffmpeg_builder.py` — `_motion_vf_prefix`, `_zoompan_filter` (`_ZOOM_RATE_PER_S`, `_PAN_TRAVEL_FRACTION_PER_S`), `_parse_sfx_delay_ms` — the values the CapCut keyframes should match
- `src/captions.py` — caption presets
- `DECISIONS.md` — D100, D081, D082, D087, D076


### Handover
- `tools/capcut/export_capcut.py <zip>` writes a CapCut draft from `timeline.json` alone; the pure timeline → draft mapping is in `tools/capcut/draft_plan.py` (unit-tested without CapCut or pycapcut, `tests/test_p13b_s3_capcut_plan.py`). `pycapcut` is pinned in `tools/capcut/requirements.txt` only (D100). `tools/capcut_spike/` removed.
- Tested with CapCut 8.9.1 (macOS) and pycapcut 0.0.3; unknown `schema_version` stops with a clear message.
- **Spike's open point settled:** CapCut 8.x reads `draft_info.json`. pycapcut writes `draft_content.json` (6.x name), so the script renames it; `--both-files` keeps both. Details in `tools/capcut/README.md`.
- Files that mattered: `tools/capcut/README.md`, `tools/capcut/draft_plan.py`, `src/ffmpeg_builder.py` (motion constants the keyframes mirror).

---

## [P13b-S4] Return path — upload the CapCut-rendered video into the run
**Epic:** E49 — CapCut export
**Sprint:** P13b
**Status:** done
**Completed:** 2026-10-04
**Priority:** high
**Points:** 2
**Depends on:** P13b-S2

### Goal
The video the operator rendered in CapCut becomes the run's final video, so the Metadata stage — and later publishing (P16) — continue as they do after an FFmpeg render.

### Acceptance Criteria
- [x] `POST /platform/studio/runs/{run_id}/output/upload` accepts an `.mp4`, validated for MIME type and size (limit from an ENV var, documented in ENV.md), and stores it as the run's final video
- [x] The run records which path produced its final video (`ffmpeg` or `capcut`) and when; the video endpoints return it
- [x] An uploaded video is not overwritten silently: starting an FFmpeg render on a run whose final video came from CapCut asks for confirmation in Studio, and the upload asks for confirmation when an FFmpeg render exists
- [x] The existing check that a stale `final.mp4` from a killed render is not mistaken for a finished job still holds
- [x] Studio Render stage: "Upload video from CapCut" control; after upload the stage shows the video with its source, and the Metadata stage is reachable exactly as after an FFmpeg render
- [x] A TraceEvent records the upload
- [x] Tests: upload accept / reject (type, size); source recorded and returned; overwrite rules in both directions; Metadata reachable after an upload; static-page test for the control
- [x] **Human touchpoint (closes the sprint):** the operator uploads the CapCut render into the run on DEV and generates metadata for it

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/interfaces/routes/studio.py` — the video URL / render status endpoints (stale `final.mp4` handling), scene upload (validation pattern), music upload
- `cf_platform/interfaces/routes/workers.py` — render endpoint, metadata endpoint
- `src/static/studio-v2.html` — Render and Metadata stages
- `tests/cf_platform/test_p10_s2_asset_override.py` (upload test pattern)
- `DECISIONS.md` — D100, D098


### Handover
- `POST /platform/studio/runs/{run_id}/output/upload` accepts an `.mp4` (MIME and size checked) and stores it as `output/final.mp4`; `output/final_source.json` records `ffmpeg` or `capcut` with a timestamp (`cf_platform/core/final_video.py`, `record_final_source`). Overwrite confirmation in both directions; the stale-`final.mp4` guard still holds. Studio Render stage: "Upload video from CapCut".
- New ENV var: `OUTPUT_UPLOAD_MAX_MB` (default 500; the file is read into memory). No new platform dependency.
- Files that mattered: `cf_platform/core/final_video.py`, `cf_platform/interfaces/routes/studio.py`, `tests/cf_platform/test_p13b_s4_output_upload.py`.

---

## EPIC 44 — Storyboard control (Sprint P13)

Second sprint of the Pipeline & Platform Update (D095, spec §10–15). The storyboard becomes a human gate: the operator can change each scene's asset strategy and the scene boundaries before any acquisition call is made. Delivered as one sprint (METHODOLOGY.md, 2026-10-03).

**Design rules for the whole epic**
- The storyboard records the *desired* asset strategy per scene; acquisition executes it (D095). Today the image/video choice is derived from scene duration (`_assign_asset_tier`) and cannot be changed by the operator.
- Scene boundaries are `start_word` / `end_word` indices (P9-S9). Timing is always recomputed from the Deepgram word timestamps — never typed in.
- **Voiceover text is read-only in this sprint** (operator decision, 2026-10-03). Changing words forces re-voicing and re-alignment; the operator goes back to the Script stage for that.
- **Splitting a scene that already has an asset** (operator decision, 2026-10-03): the first half keeps the asset, the second half is marked as needing acquisition.
- Every edit writes a new storyboard artifact version through the existing `_patch_storyboard` path, so `render_options` and cumulative timing stay coherent.
- With Auto Advance on, the gate is skipped (D095). Studio / REST only (D093). Plain HTML/JS, reusing `.cf-select`.

---

## [P13-S1] Per-scene asset strategy — model, patch, acquisition
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
Each scene carries an operator-editable asset strategy — stock image, stock video, or upload — that is set before acquisition and that acquisition obeys. Without an explicit choice, behaviour is exactly as today.

### Acceptance Criteria
- [x] `StoryboardScene` gains `asset_strategy: Literal["stock_image", "stock_video", "upload"] | None = None`; `None` means "derive from `asset_tier` as today". The vocabulary lives in one constant so P14 can add `ai_image`
- [x] `asset_strategy` is in `_PATCHABLE_FIELDS` and validated in `PATCH /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}`; an unknown value is rejected with 422
- [x] The storyboard GET returns, for every scene, the effective strategy (the explicit one, or the one derived from `asset_tier`) so the UI never has to re-derive it
- [x] AcquisitionWorker: `stock_image` forces the photo path and `stock_video` the video path, regardless of `asset_tier` / `clip_type`; the render script treats the scene accordingly (a still gets its motion effect, a video does not)
- [x] `upload` scenes are skipped by acquisition and reported as "awaiting upload" in the manifest and `footage_summary`; the existing per-scene upload endpoint fills them; render is refused with a clear message while any upload scene has no file
- [x] Changing a still scene to video (or back) resets `motion_effect` to the correct default via `normalize_motion_effect`
- [x] **Confirm at the start of the story:** whether the Studio stage-by-stage flow runs the Visual Director at all — it is only referenced from `full_pipeline.py`, not from the worker routes. Record the finding in the Handover; wiring it in is out of scope unless the strategy cannot work without it
- [x] **No regression:** a storyboard with no `asset_strategy` on any scene produces a byte-identical manifest request and render script before and after
- [x] Tests: patch accept/reject; each strategy's acquisition path; upload scene skipped and blocking render; legacy storyboard unchanged

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — `_assign_asset_tier`, `_asset_tier_to_clip_type`, `_patch_storyboard` / `_PATCHABLE_FIELDS`
- `cf_platform/workers/acquisition_worker.py` — the `asset_tier` / `clip_type` branch (two places), `visual_treatment` loading
- `cf_platform/interfaces/routes/studio.py` — scene PATCH, `reacquire`, `upload`
- `src/models.py` — `StoryboardScene`, `ManifestEntry`, `normalize_motion_effect`
- `cf_platform/models/visual_treatment.py` — `SceneVisualPlan.asset_class` / `preferred_source`
- `DECISIONS.md` — D095, D081, D089

### Handover
- **Visual Director finding:** the Studio stage-by-stage flow does not run it. `build_visual_director_worker` is referenced only from `cf_platform/orchestrator/full_pipeline.py`; `POST /platform/workers/acquisition` never passes a `visual_treatment`. The asset strategy does not need it, so it was left unwired.
- `src/models.py`: `AssetStrategy` Literal → `ASSET_STRATEGIES` (P14 adds `ai_image` there only), `effective_asset_strategy()`, `AWAITING_UPLOAD_STATUS`; `StoryboardScene.asset_strategy`; `ManifestEntry.asset_strategy` + `asset_slot`.
- `storyboard_worker.apply_asset_strategy(scene, strategy)` realigns `asset_tier` / `clip_type` / `motion_effect`: video → `("video","hard_cut",None)`; image → still tier (floored to `still_motion`) with `normalize_motion_effect`; upload → untouched (the upload endpoint re-derives from the file, D089).
- Scene PATCH accepts `asset_strategy` (422 on unknown). With a manifest present, `_sync_entry_with_strategy` releases an asset that no longer fits and the response lists `needs_acquisition` (D102). Storyboard GET adds `effective_asset_strategy` to every scene.
- Acquisition: `_wants_video(entry)` replaces both tier branches; `stock_video` goes straight to the stock video search even on Character / Event scenes. The worker skips `upload` scenes (`awaiting_upload` in the manifest and, only when non-zero, in `footage_summary`), keeps an uploaded file through a full re-acquire, and with `inputs["only_missing"]` keeps every acquired entry. `build_manifest_artifact` is the one place that counts acquired / failed.
- Render: `render_worker.missing_assets_message` — the endpoint returns 409 and the worker raises before any FFmpeg work. It checks for a file, not for `status == "acquired"` (a failed re-acquire keeps the old file).
- The upload endpoint now starts a manifest from the storyboard when the run has none (needed for uploading at the gate).
- Tests: `tests/cf_platform/test_p13_s1_asset_strategy.py` (57), helper `tests/cf_platform/p13_helpers.py`.
- **Files that mattered:** `acquisition_worker.py` (worker loop, `_acquire_scene`, `_acquire_single_scene`), `studio.py` (patch, upload), `workers.py` (acquisition + render endpoints), `src/ffmpeg_builder.py` (`_scene_section` needs one entry with a file per scene).

---

## [P13-S2] Split and merge scenes
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 4
**Depends on:** —

### Goal
The operator can split one scene into two at a word, and merge a scene with the next one. Boundaries move as word indices; durations and overlay timing are recomputed from the Deepgram timestamps.

### Acceptance Criteria
- [x] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/split {at_word}` — `at_word` becomes the first word of the new second scene; rejected with 422 unless `start_word < at_word <= end_word`
- [x] `POST /platform/studio/runs/{run_id}/storyboard/scenes/{scene_id}/merge` — merges the scene with the one after it; rejected with 409 on the last scene
- [x] After either operation the storyboard is still contiguous (first `start_word` = 0, last `end_word` = N−1, no gaps), scene ids are renumbered in order, and `voiceover_line`, `scene_start_ms` / `scene_end_ms`, `duration_s` and `asset_tier` are recomputed from the word timestamps by the same code the StoryboardWorker uses
- [x] Split: the first half keeps every field of the original scene; the second half copies the visual fields (search terms, segment type, asset strategy) and starts with no on-screen text and no SFX
- [x] Merge: the first scene's fields win; the second scene's on-screen text and SFX are dropped, and the response says so
- [x] `render_options` for all scenes are rebuilt through `_patch_storyboard`; a new storyboard artifact version is written
- [x] **Already-acquired assets (operator decision):** on split, the first half keeps the asset and the second half is marked as needing acquisition; on merge, the merged scene keeps the first scene's asset and the second scene's manifest entry is removed. The manifest stays aligned with the renumbered scenes, and a later "Acquire Assets" fetches only the scenes that need one
- [x] A split that would create a scene shorter than the minimum scene duration is rejected with a clear message
- [x] Voiceover text is not editable through these endpoints
- [x] Tests: split and merge happy paths; boundary validation; contiguity and timing after a sequence of splits and merges; manifest alignment with and without acquired assets

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — the scene-from-word-span builder (around `start_word` / `end_word` clamping), the long-scene splitter, the contiguity enforcement, `_patch_storyboard`
- `cf_platform/interfaces/routes/studio.py` — scene PATCH (how a new artifact version is written), manifest GET
- `cf_platform/workers/render_worker.py` — "live start_word boundaries" block
- `tests/cf_platform/test_p9_s9_timestamp_storyboard.py`, `tests/cf_platform/test_p10_s2_asset_override.py`
- `DECISIONS.md` — D095, D086

### Handover
- **The recompute helper (reused by S4):** `cf_platform/workers/storyboard_edit.py` — `replace_boundaries(storyboard, words, start_words, manifest, min_scene_s)` returns a `BoundaryEdit` (storyboard, realigned manifest or `None`, `dropped`, `needs_acquisition`). `split_scene` and `merge_scene` only build the new start-word list. Pure functions; rule and rationale in D102.
- Timing comes from `_reify_scene`; kept scenes with an asset follow the file kind (`rederive_scene_visual_contract`), an untouched scene keeps every field, an explicit strategy is re-applied, everything else takes the duration-derived tier.
- Routes: `POST …/storyboard/scenes/{id}/split {at_word}` (422 outside `start < at_word <= end` or below the minimum), `POST …/scenes/{id}/merge` (409 on the last scene), 404 unknown scene, 409 when the run has no voice alignment. The response carries the new storyboard, `dropped`, `needs_acquisition` (`null` before acquisition) and a one-line `summary`.
- Words are loaded with `_normalize_deepgram_words` — the same list the StoryboardWorker indexes into.
- Manifest: rewritten only when the run has one; always one entry per scene in scene order. `asset_slot` keeps a newly acquired file from overwriting a kept one after renumbering (worker, pencil re-acquire); uploads get a hash suffix (D102).
- `STORYBOARD_MIN_SCENE_S` (default 1.0) in `PlatformSettings` and ENV.md; checked only on scenes whose span changed.
- A storyboard without word indices (generated without voice timestamps) cannot be edited — 422 with a message to regenerate.
- **Noticed, not changed:** `render_worker`'s "live start_word boundaries" block indexes the *raw* alignment words while scene indices refer to the *normalised* list (contraction tokens collapsed). Pre-existing; worth a look if scene cuts drift on scripts with many contractions.
- Tests: `tests/cf_platform/test_p13_s2_split_merge.py` (32).

---

## [P13-S3] Storyboard stage — strategy dropdown, split / merge controls, confirm gate
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** high
**Points:** 3
**Depends on:** P13-S1, P13-S2

### Goal
The Storyboard table in Studio exposes the new controls, and acquisition starts only when the operator confirms the storyboard.

### Acceptance Criteria
- [x] New "Asset" column: a `.cf-select--sm` dropdown per scene with Stock image / Stock video / Upload, showing the effective strategy; changing it calls the scene PATCH and re-renders the row (the Motion cell follows: dropdown for stills, `—` for video)
- [x] An "Upload" scene shows an upload control in its row before acquisition, using the existing per-scene upload endpoint
- [x] Split: clicking a word in a scene's voiceover text offers "Split here"; Merge: each row except the last has "Merge with next". Both re-render the table from the response
- [x] A merge that drops on-screen text or SFX asks for confirmation first
- [x] The acquire button reads "Confirm storyboard & acquire"; nothing is acquired before it is pressed when Auto Advance is off. With Auto Advance on, acquisition starts without the gate (D095)
- [x] After acquisition, scenes that need an asset (a split's second half, an unfilled upload) are visibly marked, and the button acquires only those
- [x] Row height and table width stay as they are at 1280px; no console errors
- [x] Tests: static-page test pins the new controls and the routes they call
- [x] **Human touchpoint:** on DEV, the operator changes a scene from image to video, splits one scene and merges two, confirms and acquires, then swaps one scene's asset with the pencil — the last step clears the **P10-S2** deferred smoke test

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `src/static/studio-v2.html` — `renderStoryboard`, `patchScene`, `acquireAssets`, the auto-advance block in `renderStageTrack`
- `docs/UI_GUIDELINES.md#principles`, `docs/UI_GUIDELINES.md#step-status-display`
- `tests/cf_platform/test_p12_s2_pages.py` (pattern for static-page tests), `tests/cf_platform/test_pux2_s3_motion.py`

### Handover
- `src/static/studio-v2.html` only. The read-only image / video badge column is now the **Asset** dropdown (`.cf-select--sm` + `.cf-select--asset`); `onAssetChange` patches and reloads the table.
- Split: every voiceover word after the first is a `.vo-word`; clicking opens the `#split-pop` popover ("Split here" / Cancel, closes on scroll and Escape). Merge: `⤵` under the pencil on every row but the last; `confirm()` first when the next scene has on-screen text or SFX.
- `acquirePlan()` is the single source for the button: "Confirm storyboard & acquire →" until a stock asset exists, "Acquire N missing scene(s) →" (`only_missing: true`), else "Re-acquire All". Auto Advance still calls `acquireAssets` directly after storyboard generation, and no longer starts the render while an Upload scene awaits a file.
- An Upload scene without a file shows an Upload control in its Preview cell (works before acquisition); other scenes without an asset show "needs asset" once a manifest exists; the summary shows "N need an asset".
- `_applyManifestToTable` now rebuilds `state.manifestEntries` instead of merging (ids are renumbered by edits).
- **Width at 1280px:** table 987px before and after, row heights identical (measured in the demo fixture). Asset and Motion selects are sized to their longest label to pay for the dropdown.
- Demo mode (`?demo=1`) mocks strategy patch, split, merge and boundaries so the controls can be tried without a backend.
- Verified in the browser preview (demo mode): split, acquire-missing, image → video (Motion becomes `—`), Upload control, merge with confirmation, no console errors beyond the demo's missing SFX library. **DEV smoke test PASSED 2026-10-03** (operator, all 17 steps, `1e5ff4b`) — including real acquisition, row upload, only-missing acquisition after a split, and the pencil swap that clears the P10-S2 deferral.
- Tests: `tests/cf_platform/test_p13_s3_storyboard_stage.py` (20, shared with S4's UI).

---

## [P13-S4] Script view — edit scene boundaries as text
**Epic:** E44 — Storyboard control
**Sprint:** P13
**Status:** done
**Completed:** 2026-10-03
**Priority:** med
**Points:** 3
**Depends on:** P13-S2

### Goal
A second view of the Storyboard stage shows the whole voiceover as text, with a blank line between scenes. The operator moves the blank lines to move the boundaries and applies the result in one step.

### Acceptance Criteria
- [x] Toggle in the Storyboard stage: Table / Script. Script view shows each scene's words as a paragraph, paragraphs separated by one blank line
- [x] `PUT /platform/studio/runs/{run_id}/storyboard/boundaries {start_words: [...]}` replaces all scene boundaries at once; validated (starts at 0, strictly increasing, within range, minimum scene duration) and applied through the same recompute path as split / merge
- [x] A scene whose `start_word` is unchanged keeps its fields and its asset; a new scene inherits the visual fields of the scene it was cut from; assets follow the same rule as P13-S2
- [x] **Words cannot be changed.** If the text differs from the voiceover by anything other than paragraph breaks, Apply is disabled and the message says to change the text in the Script stage (it forces re-voicing)
- [x] Apply shows what will change ("12 scenes → 14; 3 scenes need acquisition") before writing
- [x] Tests: boundary replace happy path; each validation failure; unchanged scenes keep fields and assets; changed-words rejection

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P13-S2 Handover (the recompute helper this story reuses)
- `src/static/studio-v2.html` — `renderStoryboard`
- `cf_platform/interfaces/routes/studio.py` — storyboard GET, voice GET (word list)

### Handover
- `PUT …/storyboard/boundaries` takes exactly one of `start_words` or `script_text`, plus `dry_run`. `script_text` is the Script view's text: `start_words_from_text` requires the words to equal the voiceover's in order (only paragraph breaks may differ), else 422 pointing to the Script stage.
- Same `replace_boundaries` path as split / merge, so the keep / inherit / drop rules and manifest handling are identical (D102).
- UI: Table / Script toggle in the Storyboard summary row (`state.sbView`). Script view is a textarea with one paragraph per scene; `onScriptViewInput` disables Apply when the words differ or nothing moved. Apply sends a dry run, shows its `summary` ("12 scenes → 14; 3 scenes need acquisition") in a confirm, then writes.
- The Script view shows the normalised words (no punctuation) — those are the words the boundaries index.
- Tests: `tests/cf_platform/test_p13_s4_boundaries.py` (25).

---

## EPIC 50 — Word-anchored overlays and a curated SFX library (backlog)

**Why:** the on-screen text and the SFX of a scene follow fixed rules today: text appears 0.3 s after the scene starts, and an SFX plays at the scene start (or 0.7 s in when the scene has text — D076). The operator wants to point at the word where each should land. The same anchors then reach the CapCut draft for free, because the Timeline (D103) already carries the text window and the SFX offset. SFX positions in CapCut were never going to be hand-placed by script; this makes them right at the source. The library half is a separate problem: the Freesound auto-seed was rejected by the operator (D078), so good sounds need to be chosen by ear.

**Suggested order:** E50-S3 (library) can start any time and is independent. E50-S1 → E50-S2 follow. Needs a sprint slot; none proposed. Natural neighbours: before or after P14 (both touch the Storyboard stage).

---

## [E50-S1] Word anchors for on-screen text and SFX — model, timeline, render
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 5
**Depends on:** P13b (Timeline, D103)

### Goal
A scene can say *at which word* its on-screen text appears and *at which word* its SFX plays. Scenes without an anchor behave exactly as today.

### Acceptance Criteria
- [ ] `StoryboardScene` gains optional `on_screen_text_word` and `sfx_word`: indices into the **normalised** voiceover words (the list `start_word` / `end_word` index — `_normalize_deepgram_words`), each required to lie inside the scene's `start_word..end_word`
- [ ] `build_timeline` resolves an anchor to a time from that word's start (`TimelineText.start_ms`, `TimelineScene.sfx_delay_ms`); text still lasts to the scene end. No anchor → today's rule, so the existing golden render scripts stay byte-identical
- [ ] The FFmpeg overlay window and SFX `adelay` read the anchored values from the Timeline; the SFX auto-offset rule (D076) applies only to unanchored scenes
- [ ] The CapCut export needs no change: a test shows an anchored text clip and SFX clip land at the word's time in the draft plan
- [ ] `PATCH …/storyboard/scenes/{id}` accepts both anchors (and `null` to clear); 422 when the word is outside the scene
- [ ] Anchors survive and follow edits (D102): split / merge / Script-view boundary changes keep an anchor whose word is still in the scene, clear one whose word left it, and report what was cleared; a regenerated voiceover clears all anchors (word indices no longer mean the same words)
- [ ] The word-index fix from P13b-S1 is relied on, not repeated: a test with contractions puts the anchor on the intended word
- [ ] Tests: anchor resolution with and without alignment; golden scripts unchanged for unanchored scenes; one new golden for an anchored scene; the edit-survival rules

### Decision (2026-10-04)
On-screen text anchors to a word's **start** only and stays until the end of the scene. An end word (text disappearing early) is not part of this story; it could be added later as an optional `on_screen_text_end_word`.

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/timeline.py` — `assemble_timeline` (text window, SFX offset), `resolve_scene_timing`
- `src/ffmpeg_builder.py` — `_sfx_delay_within_scene_s`, `_audio_section`; `cf_platform/workers/render_worker.py` — `_collect_overlay_filters`
- `src/models.py` — `StoryboardScene`; `cf_platform/workers/storyboard_edit.py` — `replace_boundaries`
- `cf_platform/interfaces/routes/studio.py` — `ScenePatchRequest`, `studio_patch_scene`
- `tests/cf_platform/test_p13b_s1_golden_render.py`, `tools/capcut/draft_plan.py`
- `DECISIONS.md` — D076, D074, D075, D102, D103

---

## [E50-S2] Studio — click a word to set on-screen text or SFX there
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 3
**Depends on:** E50-S1

### Goal
In the Storyboard stage, the operator clicks a word of a scene and chooses *On-screen text here* or *SFX here*; the choice is shown on the word and can be changed or removed.

### Acceptance Criteria
- [ ] Clicking a word opens the small popover already used for split (D102 UI), now with three actions: Split here · On-screen text here · SFX here. Split stays where it is
- [ ] *On-screen text here* asks for the text (prefilled with the scene's current text) and the type, then PATCHes text + anchor; *SFX here* shows the SFX dropdown (with audition, see E50-S3) and PATCHes key + anchor
- [ ] Anchored words are marked in the scene's words (a small T / ♪ marker with a tooltip); clicking a marked word offers *Move*, *Edit*, *Remove*
- [ ] The scene row's existing text and SFX cells keep working; changing them there keeps the anchor, clearing them clears it
- [ ] An edit that clears an anchor (E50-S1) says so in the same message the split / merge / boundaries edits already show
- [ ] Demo mode mocks it; works at phone width
- [ ] Static-page tests pin the popover actions and the routes they call

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator anchors a text and an SFX in two scenes, renders with FFmpeg, and downloads for CapCut; both land on the chosen words

### Files to read
- `src/static/studio-v2.html` — Storyboard stage: word-click split (`confirmSplit`, `split-pop`), `buildSceneRow`, SFX cell
- `tests/cf_platform/test_p13_s3_storyboard_stage.py` (static-page test pattern)
- `docs/UI_GUIDELINES.md`

---

## [E50-S3] A curated SFX library of good sounds
**Epic:** E50 — Word-anchored overlays and a curated SFX library
**Sprint:** unassigned
**Status:** backlog
**Priority:** medium
**Points:** 5
**Depends on:** —

### Goal
The SFX dropdown offers a small set of sounds that sound right for punchy Shorts, each checked by ear and licensed for use, and the operator can hear one before choosing it.

### Acceptance Criteria
- [ ] A decision (`/decide`) on the source: operator-picked files from a licensed pack or site (CC0 / royalty-free, licence recorded per file) rather than an automated Freesound query — D078 showed ranking by downloads and ratings does not find good sounds. Free-tier rule (CLAUDE.md) checked for any paid pack
- [ ] The manifest (`cf_platform/core/sfx_library.py`) grows beyond the first 8 keys to the sounds the operator actually uses (target 15–25: hits, whooshes, risers, UI sounds, money, alerts), each with `display_name`, `prompt_hint` for the AI suggestion, **source and licence**
- [ ] Files are normalised to one loudness and trimmed (short, no tail noise, no silence at the start) by a script before upload, so every sound sits at the same level against the voiceover and music
- [ ] Upload goes through the existing manual path (`scripts/upload_sfx.py`, D078); `seed_sfx_library.py` and the Freesound search queries are removed from the manifest if unused
- [ ] Studio: an audition button (▶) beside the SFX dropdown plays the sound; presigned URL, no download
- [ ] The AI suggestion prompt keeps working from the manifest (D076); with a larger vocabulary, a check that the prompt stays within its size budget and that "silence" is still the common answer
- [ ] Tests: manifest entries all have licence + source; every key has a backing file in a seeded storage; audition route returns a URL only for present keys

### Open question
Where to find the sounds — the operator picks. Candidates to evaluate: Pixabay audio (free licence), a one-off paid pack, CapCut's own library downloaded by hand (check its licence terms before bundling in a product).

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator opens the dropdown on DEV, auditions each sound, and renders a run with two of them

### Files to read
- `cf_platform/core/sfx_library.py`, `scripts/upload_sfx.py`, `scripts/seed_sfx_library.py`
- `cf_platform/workers/render_worker.py` — `list_available_sfx`, `_copy_all_scene_sfx_to_run`
- `cf_platform/interfaces/routes/studio.py` — `studio_get_sfx_library`
- `DECISIONS.md` — D076, D078

---

## Unassigned backlog

Open stories that belong to no sprint in the current roadmap (D099).

---

## [P8-S7] LLM-vision media scorer — emotion, mood, relevance
**Epic:** E35 — Footage Quality
**Sprint:** unassigned — deferred from P8 to P10, never picked up; not in the D099 roadmap
**Status:** backlog
**Priority:** low
**Points:** 3
**Depends on:** P8-S4

> **Groomed 2026-10-03:** priority med → low. Since this was written, P10-S3 (semantic enrichment + Entity Resolver) and P11-S1 (Visual Director) took over asset relevance, P13 puts the asset choice in the operator's hands, and P14 generates images outright. Revisit only if stock relevance is still a complaint after P14.

### Goal
Replace the metadata-only (resolution) ranking used in P8-S1 with a multimodal LLM evaluation that scores each candidate asset against the scene's `visual_description` on axes that can't be inferred from resolution alone: emotional tone, visual mood, subject relevance, and production quality. One Haiku vision call per candidate evaluated. Returns a numeric score (0.0–1.0); the acquisition loop picks the highest-scoring candidate that also passes the P8-S4 resolution + duration gate.

### Scorer axes (prompt → structured JSON)
| Axis | Weight | Description |
|------|--------|-------------|
| `relevance` | 0.4 | Does the image depict the described subject? |
| `emotional_tone` | 0.3 | Does the mood/feel match the scene intent? |
| `visual_quality` | 0.2 | Professional composition, lighting, not amateur/stock-cliché |
| `diversity` | 0.1 | Penalise if visually similar to already-selected scenes in this run |

### Module contract (`src/media_scorer.py`)
```python
async def score_candidate(
    image_url: str,
    scene_description: str,
    selected_scene_descriptions: list[str],
    anthropic_api_key: str,
    model: str = "claude-haiku-4-5",
) -> MediaScore

# MediaScore: relevance, emotional_tone, visual_quality, diversity, total, passed (total >= 0.60)
```

### Integration point
Plug into `acquire_scene` after resolution gate (P8-S4 hook point): for each resolution-passing candidate, call `score_candidate`; take the highest-scoring one. If none pass the `0.60` threshold, fall back to best-resolution candidate (never leave scene empty).

### Acceptance Criteria
- [ ] `src/media_scorer.py`: `score_candidate` — downloads image, sends to Claude vision, returns `MediaScore`
- [ ] Integrated into acquisition loop after P8-S4 resolution gate; highest-scoring candidate wins
- [ ] `MEDIA_SCORER_ENABLED: bool = False` in `src/config.py` + `ENV.md` (off by default — Haiku vision call adds ~$0.003/scene)
- [ ] `asset_manifest.json`: `qa_vision_score` + `qa_vision_axes` fields per scene when scorer enabled
- [ ] Scorer disabled → resolution-ranked winner selected (P8-S1 behaviour preserved)
- [ ] Tests: happy path (mocked Claude vision); low score → skip to next candidate; scorer disabled → skipped; diversity penalty applied

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
