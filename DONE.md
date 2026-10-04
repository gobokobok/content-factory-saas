# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last two sprints (P13b, P13) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P13b] CapCut export — S1 timeline artifact + golden render tests, S2 download zip, S3 laptop script, S4 return upload
**Completed:** 2026-10-04
**Handover:**
- **One Timeline feeds both render paths (D103).** `cf_platform/workers/timeline.py` — `build_timeline(...)` is the only place scene timing is resolved; FFmpeg on Railway reads it (`build_render_script_from_timeline`) and so does the CapCut export. Stored as run artifact `render/timeline@vN`, `schema_version` 1; `GET /platform/studio/runs/{id}/timeline`. Assets are addressed by `file_key`, never scene id (D102).
- **Render is pinned by 22 golden scripts** in `tests/golden/render/`; regenerate only on purpose with `UPDATE_GOLDEN=1` (docs/TESTING.md). The word-index fix (scene boundaries against the normalised word list) changed only the contraction-heavy golden, on purpose.
- **Export / return:** `GET …/export/capcut` streams a zip (`timeline.json` + media); `tools/capcut/export_capcut.py <zip>` writes the CapCut draft on the laptop (pycapcut pinned in `tools/capcut/requirements.txt` only, tested with CapCut 8.9.1). CapCut 8.x reads `draft_info.json`; the script renames pycapcut's `draft_content.json`. `POST …/output/upload` stores the CapCut render as `output/final.mp4` with `output/final_source.json` (`ffmpeg` / `capcut`); overwrite confirmation both ways.
- **Known limits (D103):** wikimedia-portrait blur-fill, Standard captions' per-word highlight, and the legacy `build_ffmpeg_script` are not in the timeline. Candidate for E50: word-anchored text and SFX reach the CapCut draft through the timeline for free.
- New ENV var: `OUTPUT_UPLOAD_MAX_MB` (default 500). No new platform dependency. Tests: 5 new files plus the golden suite; CI 2526 passed on `fa6a3f0`.
- Decision logged: **D103**.
- **Post-close (2026-10-04):** the SFX library was cut to five operator-chosen sounds — `whoosh`, `impact`, `cash_register`, `error`, `typing` (`cf_platform/core/sfx_library.py`). Sources and licences (Pixabay Content License) are in `assets/sfx_source/SOURCES.md`; the trimmed, loudness-matched files are uploaded to the DEV `sfx-library/`, not PROD. Scenes that still hold an old key (`checkmark`, `pop`, `notification`, `drumroll`) show "none" in the dropdown. The CapCut draft carries no SFX clips in the operator's smoke run (SFX are placed by hand; word-anchored placement is E50-S1).
**Smoke test:** PASSED — 2026-10-04 on Railway DEV, operator reported the CapCut path complete in chat (download, laptop command, CapCut edit, upload back). Individual steps were not itemised.
**Promoted to backlog:** none. EPIC 50 (E50-S1..S3, word-anchored overlays and SFX library) was proposed the same day, unplaced.

---

## [P13] Storyboard control — S1 asset strategy, S2 split / merge, S3 Storyboard stage controls + confirm gate, S4 script view
**Completed:** 2026-10-03
**Handover:**
- **The storyboard is the gate (D095).** Each scene carries `asset_strategy` (`stock_image` / `stock_video` / `upload`, or `None` = derive from `asset_tier` as before). The vocabulary is one Literal in `src/models.py` (`AssetStrategy` → `ASSET_STRATEGIES`) — P14 adds `ai_image` there. The storyboard GET returns `effective_asset_strategy` per scene.
- **Acquisition obeys it.** `stock_video` goes straight to the stock video search (even on Character / Event scenes); `upload` scenes are never fetched — they keep an uploaded file or are reported as `awaiting_upload` (manifest status, and `footage_summary` only when non-zero). `POST /platform/workers/acquisition {only_missing}` keeps every scene that already holds an asset. `build_manifest_artifact` is the one place that counts acquired / failed.
- **Boundary edits** live in `cf_platform/workers/storyboard_edit.py`: `replace_boundaries` (plus `split_scene`, `merge_scene`, `start_words_from_text`). One rule — unchanged start word keeps fields and asset; a new start word is cut from the scene that contained it; a vanished start word is merged away (D102). Routes: `POST …/storyboard/scenes/{id}/split {at_word}`, `POST …/scenes/{id}/merge`, `PUT …/storyboard/boundaries {start_words | script_text, dry_run}`. Each writes a new storyboard version and, when the run has a manifest, a realigned manifest version.
- **Scene ids are renumbered by edits; asset files are not moved.** `ManifestEntry.asset_slot` (and a hash suffix on uploads) keeps a new file from overwriting one another scene still uses. Anything that writes a scene asset must go through `_asset_stem(entry)` / `assign_free_asset_slot` — P13b's CapCut export should read `file_key`, never rebuild a path from the scene id.
- **Render** is refused up front (409 from the endpoint, `RuntimeError` in the worker) while any scene has no file: `render_worker.missing_assets_message`.
- **The upload endpoint starts a manifest** from the storyboard when the run has none, so a manifest can now exist before acquisition with `pending` entries.
- **Studio:** Asset dropdown (replaces the image / video badge), word-click split, `⤵` merge, row upload, "needs asset" marking, `acquirePlan()` deciding the button ("Confirm storyboard & acquire →" / "Acquire N missing scenes →" / "Re-acquire All"), Table / Script toggle. Demo mode mocks all of it.
- **Visual Director is not run by the Studio stage-by-stage flow** — only by `full_pipeline.py`. Relevant to P14 (its prompt branch) and P17.
- New ENV var: `STORYBOARD_MIN_SCENE_S` (default 1.0). No new dependencies. Tests: 134 new (`test_p13_s1_asset_strategy.py`, `test_p13_s2_split_merge.py`, `test_p13_s3_storyboard_stage.py`, `test_p13_s4_boundaries.py`, helper `p13_helpers.py`). 2435 passing.
- Decision logged: **D102**.
**Smoke test:** PASSED — 2026-10-03 on Railway DEV (`1e5ff4b`), operator ran all 17 steps: gate before acquisition, image ↔ video with Motion following, split with the minimum-length rejection, merge with the dropped-text confirmation, upload at the gate, render refused for an empty Upload scene, only-missing acquisition after a split with every other asset untouched, Script view apply and changed-word block, pencil re-acquire and upload, final render.
**Promoted to backlog:** none. Noted for later, not a story yet: `render_worker`'s live-boundary block indexes raw alignment words while scene indices refer to the normalised list.
