# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._

Format:

---

## [E4-S4] CLIP semantic reranking of Pexels results
**Completed:** 2026-05-25
**Sprint:** unassigned
**Handover:**
- `src/clip_reranker.py`: new module. `CLIPReranker(model)` — `rerank_videos(videos, query)` and `rerank_photos(photos, query)` score Pexels thumbnails against query text using CLIP cosine similarity (numpy only, no torch in application code). Module-level singleton via `load_model()` (lazy-loads `clip-ViT-B-32` via `sentence-transformers`) and `get_reranker() → Optional[CLIPReranker]`. Unscoreable items (missing/unfetchable thumbnails) placed after scored items. Raises `CLIPError` on encoding failure, which callers catch and fall back from.
- `src/pexels.py`: `_acquire_video` reranks video results by CLIP score before the `_pick_best_video_file` loop. `_acquire_photo` reranks photo results then picks via new `_pick_first_qualifying_photo` (first photo ≥ 1920×1080 in CLIP order); falls back to `_pick_best_photo` on `CLIPError` or when reranker is None (default).
- `src/pexels.py`: `_pick_first_qualifying_photo(photos) → Optional[dict]` — new module-level helper; existing `_pick_best_photo` (min excess area) retained for non-CLIP path.
- `src/main.py`: lifespan hook calls `clip_reranker.load_model()` when `CLIP_RERANK_ENABLED=True`.
- `src/config.py`: `CLIP_RERANK_ENABLED: bool = False` added.
- `src/exceptions.py`: `CLIPError` added.
- `requirements.txt`: `sentence-transformers>=3.0.0`, `Pillow>=10.0.0` added (D032).
- `ENV.md`: `CLIP_RERANK_ENABLED` documented.
- `tests/test_clip_reranker.py`: 17 new tests. 390 total passing. Zero regressions.
- Smoke test deferred: set `CLIP_RERANK_ENABLED=True` in Railway DEV, run full pipeline, confirm footage topics visually match VO better than Pexels-order baseline.
**Promoted to backlog:** none

---

## [E5-S3] Visual-semantic matching improvement
**Completed:** 2026-05-25
**Sprint:** 2
**Handover:**
- `docs/PROMPTS.md` v0.5: VISUAL PROMPTS RULE rewritten — PRIMARY = 3–4 concrete nouns only (no adjectives); FALLBACK = 1–2 words (core subject); AI_GENERATE = cinematic direction terms (shallow depth of field, golden hour lighting, cinematic, 9:16 vertical). Four housing-economics few-shot examples added. No code changes to acquisition pipeline — queries flow through unchanged.
- `src/storyboard.py`: `SYSTEM_PROMPT` updated to v0.5. Parser hardened: section split now uses `(?m)^\s*---\s*$` (line-anchor, handles any surrounding blank-line count); `_get_field` is now case-insensitive and tolerates leading `- ` bullets; both log diagnostic content on failure.
- `src/static/pipeline.html`: storyboard scene cards now show PRIMARY / FALLBACK / AI fields for visual QA.
- No new ENV vars. No new dependencies.
- Smoke test passed on DEV: `2026-05-25_mind-drain-video-temp` — concrete nouns in PRIMARY, cinematic direction in AI_GENERATE confirmed.
**Promoted to backlog:** none

---

## [E4-S5] Real-time captions from voiceover_line
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/captions.py`: `_CAPTIONS_ASS_HEADER` — new ASS header with `VoiceCaption` style (Open Sans Regular/Bold=0, 42pt, white + black outline, Alignment=2 bottom-center, MarginV=80). `build_captions_ass(scenes) -> str` — generates ASS from `voiceover_line` per scene; empty/whitespace-only lines produce no Dialogue event; text is displayed as-is (no quote stripping, no uppercasing). Timing accumulated from `duration_s` same as `build_ass`.
- `src/ffmpeg_builder.py`: `_write_voiceover_captions_ass(ass_content)` — heredoc with `'__VCAP_EOF__'` delimiter → `$WORK/voiceover_captions.ass`. `_burn_voiceover_captions()` — burns into `video_captioned.mp4` → `video_captioned2.mp4`. `build_ffmpeg_script` wires both new calls after `_burn_captions()` and before `_audio_section()`. `_audio_section` updated to read `video_captioned2.mp4` (was `video_captioned.mp4`).
- Render chain: `video_only.mp4` → on-screen overlay → `video_captioned.mp4` → voiceover captions → `video_captioned2.mp4` → audio mix → `final.mp4`.
- `tests/test_captions.py`: 17 new tests in `TestBuildCaptionsAss`. `_scene` helper gains optional `voiceover_line` param.
- `tests/test_ffmpeg_builder.py`: 2 existing tests updated (audio input reference + null-on-screen narrowed). 6 new tests in `TestCaptionsInScript` covering chain ordering, second-pass wiring, and no-uppercase assertion.
- 369 total tests passing (28 new). No new ENV vars. No new pip dependencies.
- Smoke test deferred.
**Promoted to backlog:** none

---

## [E4-S2] Captions and on-screen text overlay
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/captions.py`: `format_ass_time(seconds: float) -> str` — converts seconds to ASS `H:MM:SS.cc`. `build_ass(scenes: list[StoryboardScene]) -> str` — generates complete ASS file from storyboard scenes; accumulates `duration_s` offsets; skips scenes where `on_screen_text=None`; uppercases all text.
- `src/ffmpeg_builder.py`: `_write_captions_ass(ass_content)` embeds ASS content via quoted heredoc (`'__ASS_EOF__'`) — prevents bash from expanding `$`-vars or ASS override-tag braces inside the heredoc body. `_burn_captions()` runs `ffmpeg -vf "ass=$WORK/captions.ass"` producing `$WORK/video_captioned.mp4`. `_audio_section` now reads `video_captioned.mp4` (was `video_only.mp4`). `build_ffmpeg_script` calls both new builders between `_filter_complex_concat` and `_audio_section`.
- `Dockerfile`: `fonts-open-sans` added to the apt install layer so Open Sans is available to FFmpeg's libass inside the Railway container.
- 341 total tests passing (30 new). No new ENV vars. No new pip dependencies.
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed assets + voiceover; verify `captions.ass` heredoc in generated script and captions visible in rendered video.
**Promoted to backlog:** none

---

## [E4-S3] Ken Burns zoompan effect on static images
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `_render_image_scene` pre-scale corrected from 2×(2160×3840) to 1×(1080×1920). The centering formula `iw/2-(iw/zoom/2)` used in `_zoompan_filter` requires `iw` (input width) to equal `ow` (s= output width). With 2× input, `iw=2160` and `ow=1080`, causing the formula to produce x=0 (left-edge crop) at z=1 instead of centered behavior.
- `_SCALED_W` and `_SCALED_H` constants removed from `ffmpeg_builder.py` — were only used by the broken 2× scale path.
- `_zoompan_filter()` unchanged. Frame count `d=duration_s*25`, output `s=1080x1920`, `fps=25`, zoom expressions all correct.
- `tests/test_ffmpeg_builder.py`: 3 new regression tests — `test_still_with_motion_prescales_to_output_dimensions`, `test_animated_prescales_to_output_dimensions`, `test_image_scene_vf_chain_order_is_scale_zoompan_setsar`. These guard against re-introduction of 2× scale.
- 311 total tests passing (3 new).
- No new ENV vars. No new dependencies.
- Smoke test deferred — POST `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed assets exists; verify image scenes show Ken Burns motion in the rendered video.
**Promoted to backlog:** none
## [E#-S#] Story title
**Completed:** YYYY-MM-DD
**Sprint:** N
**Handover:** [summary of what was built, key decisions, anything the next story needs to know]

---

## [E5-S2] Pacing calibration — sync scene durations to voiceover
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `get_audio_duration(path: Path) -> float` — runs `ffprobe -v quiet -print_format json -show_format`, parses `format.duration`, raises `FFmpegBuildError` on non-zero exit or unparseable output.
- `src/ffmpeg_builder.py`: `redistribute_scene_durations(scenes, audio_duration) -> list[StoryboardScene]` — pure function; uses word count of `voiceover_line` as weight (minimum 1 for empty lines); enforces minimum 0.5s per scene; returns new instances, originals unchanged.
- `src/ffmpeg_builder.py`: `_filter_complex_concat(n_scenes)` replaces `_concat_list` + `_concat_command`. Produces a single ffmpeg call: all `$WORK/scene_XX.mp4` as inputs → filter_complex `[i:v]setpts=PTS-STARTPTS[vi]` per clip → `concat=n=N:v=1:a=0[vout]` → re-encode to `$WORK/video_only.mp4`. Fixes non-monotonic DTS from the old concat demuxer.
- `src/routes/ffmpeg_script.py`: before calling `build_ffmpeg_script`, lists `runs/{run_id}/voiceover/` in R2, downloads the first `.mp3/.wav/.m4a` to a `TemporaryDirectory`, measures duration with ffprobe, redistributes scenes, passes updated storyboard to builder. If no voiceover or any error, logs a warning and continues with original durations.
- **Bug fix:** `n_scenes` in `build_ffmpeg_script` now derived from `len(manifest.entries)` not `storyboard.summary.total_scenes`. Stale summary values caused dangling `scene_XX.mp4` references → ffmpeg exit 254.
- **Bug fix:** `,setsar=1:1` appended to every `-vf` chain in `_render_video_scene` and `_render_image_scene`. Source images/videos carry varying SAR values (e.g. `6778880:6778343`) which caused `filter_complex` concat to fail with "Input link parameters do not match".
- No new ENV vars. No new pip dependencies (ffprobe ships with ffmpeg, already required by E5-S1).
- 308 total tests passing (28 new).
- Smoke test deferred: POST `/runs/{run_id}/ffmpeg-script` on DEV with a run that has completed storyboard + manifest + assets + uploaded voiceover; verify video cuts align with speech cadence.
**Promoted to backlog:** none

---

## [E6-S2] Operator UI — Run list and pipeline runner (+ E6-S3 inline)
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/static/pipeline.html`: complete rewrite — two-view SPA (list + detail), no frameworks. List view calls `GET /runs`, renders rows with colored status dot; click → detail. "+ New Run" panel has slug + VO script fields; on submit auto-triggers storyboard → manifest. Detail view shows 5 step rows: complete = [View]+[Rerun], pending/failed = [Run]. Storyboard [Run]/[Rerun] expands inline VO textarea. [View] fetches `GET /runs/{run_id}/artifact/{step}` and renders inline (storyboard → scene cards; manifest → table; ffmpeg_script → `<pre>`; render → `<video>`). Voiceover section (dashed row, between FFmpeg Script and Render): file picker → presigned PUT → direct R2 upload.
- `src/storage.py`: `R2Client.generate_presigned_put_url(key, expires_in=600) → str` added. Same exception pattern as `generate_presigned_url`.
- `src/models.py`: `VoiceoverUploadUrlRequest(filename: str)`, `VoiceoverUploadUrlResponse(upload_url: str, key: str)` added.
- `src/routes/runs.py`: `POST /runs/{run_id}/voiceover-upload-url` added. Key pattern: `runs/{run_id}/voiceover/{filename}`. Returns presigned PUT URL valid 10 min.
- `tests/test_runs.py`: `TestVoiceoverUploadUrl` — 4 tests. 286 total passing.
- No new ENV vars. No new pip dependencies.
- **Deployment prerequisite**: R2 bucket CORS must allow `PUT` from the Railway domain for browser direct-upload to work.
- E6-S3 (presigned upload URL) fully implemented inline — backend + UI both done.
**Promoted to backlog:** none

---

## [E1-S4] Run list and artifact retrieval endpoints
**Completed:** 2026-05-24
**Sprint:** 2
**Handover:**
- `src/storage.py`: `R2Client.list_runs() → list[dict]` — scans `runs/` prefix, filters keys ending in `/run_log.json`, fetches each log, returns `[{run_id, created_at, steps: {step: status_str}}]` sorted by `created_at` descending. Empty bucket returns `[]`. `R2Client.generate_presigned_url(key, expires_in=3600) → str` — wraps boto3 `generate_presigned_url("get_object", Params={Bucket, Key}, ExpiresIn=expires_in)`.
- `src/models.py`: `RunSummary(run_id, created_at, steps: dict[str, str])`, `RunListResponse(runs: list[RunSummary])`, `ArtifactResponse(step, content_type, content=None, url=None)` added. `content` is `Optional[Any]` (JSON dict or text string depending on step).
- `src/routes/runs.py`: `GET /runs` → `RunListResponse` (500 on `StorageError`). `GET /runs/{run_id}/artifact/{step}` → `ArtifactResponse` (404 on `StorageError`, 422 for unrecognised step). `_STEP_ARTIFACT_KEYS` module-level dict maps step name → `(key_template, content_type)`. `_make_r2_client(settings)` helper DRYs up construction. The three JSON/text steps call `get_json`/`get_bytes`; the `render` step calls `generate_presigned_url`.
- Step → R2 key mapping: `storyboard` → `runs/{run_id}/storyboard.json`; `manifest` → `runs/{run_id}/asset_manifest.json`; `ffmpeg_script` → `runs/{run_id}/ffmpeg_script.sh`; `render` → `runs/{run_id}/output/final.mp4`.
- No new ENV vars. No new dependencies.
- 35 new tests (282 total passing). Smoke test deferred — GET /runs and GET /runs/{run_id}/artifact/{step} on DEV once a run with completed steps exists.
**Promoted to backlog:** none

---

## [E5-S1] FFmpeg execution and output upload
**Completed:** 2026-05-22
**Sprint:** unassigned
**Handover:**
- `src/renderer.py`: `render_run(run_id, manifest, storage, timeout_seconds) → dict` — full render orchestration. Always cleans up `/tmp/{run_id}/` in a `finally` block. Returns `{status, output_key, duration_seconds, exit_code}`. Raises `StorageError` on unexpected R2 failures (propagates to route as 500).
- Module-level helpers (importable and tested): `download_run_assets(run_id, manifest, storage)` — downloads all manifest `file_key` entries + `voiceover/`, `music/`, `sfx/` prefix files; `download_script(run_id, storage) → Path` — downloads `ffmpeg_script.sh`, makes executable; `execute_script(script_path, timeout_seconds) → CompletedProcess`; `upload_output(run_id, storage) → str` — uploads `/tmp/{run_id}/output/*` to R2, returns key for `final.mp4`, raises `RenderError` if absent; `cleanup(run_id)` — `shutil.rmtree` with `ignore_errors=True`; `_write_run_log_txt(run_id, content, storage)` — non-fatal, swallows `StorageError`.
- `src/routes/render.py`: `POST /runs/{run_id}/render` — reads `asset_manifest.json` from R2 (→ 404), calls `render_run`, updates run_log `complete`/`failed`. HTTP 200 for both outcomes; 500 on unexpected `StorageError`.
- `src/storage.py`: `R2Client.get_bytes(key) → bytes` and `R2Client.list_keys(prefix) → list[str]` added.
- `src/models.py`: `RenderResponse(status, output_key, duration_seconds, exit_code)` added.
- `src/exceptions.py`: `RenderError` added.
- `src/config.py`: `FFMPEG_TIMEOUT_SECONDS: int = 300` added (configurable via ENV).
- R2 key pattern: `runs/{run_id}/output/final.mp4`. Timeout (`subprocess.TimeoutExpired`) yields `exit_code=-1` and `status="failed"`.
- `tests/test_renderer.py`: 30 tests. 247 total passing.
- Smoke test deferred — POST to `/runs/{run_id}/render` on DEV once a run with completed storyboard + manifest + assets + ffmpeg_script exists; verify `final.mp4` in R2 console.
**Promoted to backlog:** none

---

## [E4-S1] FFmpeg script generator
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/ffmpeg_builder.py`: `build_ffmpeg_script(run_id, storyboard, manifest) → str` — pure function, no I/O. Raises `FFmpegBuildError` (with offending `scene_id`) if any manifest entry has `file_key=None`. Module-level helpers (importable, tested): `_local_path(run_id, file_key) → str` (R2 key → `/tmp/{run_id}/...`); `_zoompan_filter(clip_type, motion_effect, frames) → str`; `_parse_sfx_delay_ms(sfx_timing, duration_s, scene_offset_s) → int`.
- Generated script: `set -euo pipefail` → BASE/WORK vars → voiceover guard (`exit 1` if no `.mp3` in `$BASE/voiceover/`) → music check (anullsrc silence fallback via ffmpeg if absent, WARNING not error) → per-scene ffmpeg commands → concat list heredoc → concat command → audio assembly → done echo.
- Clip type handling: `hard_cut` → trim + `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920`; `still_with_motion` → `-loop 1 -framerate 25`, source scaled 2160×3840, zoompan 1.0→1.05 centered; `animated` → zoompan 1.0→1.1 zoom_in/zoom_out or 1.1x pan_left/pan_right, driven by `motion_effect` field (unknown → zoom_in fallback).
- Audio: voiceover at 1.0, music at 0.15, SFX via `adelay={ms}|{ms}` per scene; `sfx="silence"` scenes skipped entirely; `amix=inputs=N:duration=first:normalize=0`.
- `src/routes/ffmpeg_script.py`: `POST /runs/{run_id}/ffmpeg-script` — sync; reads storyboard + manifest from R2 (→ 404), builds script (→ 422 + run_log `failed`), uploads via `storage.upload_text` (→ 500), updates run_log `complete`. Returns `FFmpegScriptResponse`.
- `src/models.py`: `FFmpegScriptResponse(status, script_key)` added.
- `src/exceptions.py`: `FFmpegBuildError` added.
- `src/storage.py`: `R2Client.upload_text(key, content, content_type)` added — UTF-8 encode + delegate to `upload_bytes`.
- R2 key: `runs/{run_id}/ffmpeg_script.sh`. No new ENV vars. No new dependencies.
- `tests/test_ffmpeg_builder.py`: 59 tests — unit for `_local_path`, `_parse_sfx_delay_ms`, `_zoompan_filter`, `build_ffmpeg_script`; 7 route integration tests. 217 total passing.
- Smoke test deferred — POST to `/runs/{run_id}/ffmpeg-script` on DEV once a run with completed storyboard + manifest exists; inspect `ffmpeg_script.sh` in R2 console.
**Promoted to backlog:** none

---

## [E3-S3] Asset acquisition orchestrator
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/acquisition.py`: `MIN_ACQUIRED_FOR_COMPLETE = 1` at module level with explicit docstring — step is `complete` if ≥ 1 entry acquired after the loop, `failed` only when total acquired = 0. `acquire_scene(entry, run_id, pexels, replicate, storage) → bool` — single-entry fallback chain, mutates entry in-place; `PexelsError` treated same as `None` result (falls through to Replicate). `run_acquisition(run_id, manifest, pexels, replicate, storage) → dict` — full loop over manifest entries; skips `acquired` entries (idempotent); returns `{acquired: N, failed: N, sources: {pexels: N, replicate: N}}` where `acquired` is the total post-loop count including pre-existing acquired entries.
- `src/routes/assets.py`: `POST /runs/{run_id}/assets` — reads `runs/{run_id}/asset_manifest.json` from R2 (404 if missing), instantiates `PexelsClient` + `ReplicateClient` from settings, calls `run_acquisition`, uploads updated manifest back to same key, calls `update_run_log` with `complete`/`failed` + `output_url=manifest_key`. HTTP 200 for both complete and failed outcomes; 500 only on unexpected exception or R2 write failure.
- `src/models.py`: `AcquisitionResponse(status, acquired, failed, sources, manifest_key)` added.
- `src/main.py`: `assets_router` registered.
- R2 manifest key pattern: `runs/{run_id}/asset_manifest.json` (read and written back in-place with updated source/file_key/status fields).
- `tests/test_acquisition.py`: 18 tests — all passing. 158 total tests.
- No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

## [E3-S2] Replicate/Flux AI image generation fallback
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/replicate_client.py`: `ReplicateClient(api_token, model, poll_interval_seconds=3, max_poll_attempts=60)`. Key method: `acquire_for_entry(entry, run_id, storage) → ReplicateAcquireResult`. Submits prediction via `client.predictions.create(model=model, input={"prompt": ai_generate_prompt})`, polls `prediction.reload()` until terminal status or timeout, downloads image bytes from `str(output[0])`, uploads to `runs/{run_id}/images/{scene_id}.webp`. Always `.webp` — extension never inferred from CDN URL.
- `src/models.py`: `ReplicateAcquireResult(scene_id, source="replicate", file_key, status="acquired")` added (symmetric with `PexelsAcquireResult`).
- `src/exceptions.py`: `ReplicateError` added — raised on create failure, poll failure, `failed`/`canceled` prediction status, timeout, empty output, and download failure.
- All config vars pre-existing: `REPLICATE_API_TOKEN`, `REPLICATE_FLUX_MODEL`, `REPLICATE_POLL_INTERVAL_SECONDS`, `REPLICATE_MAX_POLL_ATTEMPTS`.
- No new dependencies (`replicate>=1.0.0` already in `requirements.txt` per D007).
- 140 total tests passing (19 new). End-to-end smoke test deferred to E3-S3 (requires orchestrator route).
**Promoted to backlog:** none

---

## [E3-S1] Pexels stock footage integration
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/pexels.py`: `PexelsClient(api_key, per_page=5)` — synchronous `requests`-based client. Key method: `acquire_for_entry(entry, run_id, storage) → Optional[PexelsAcquireResult]`. Tries `primary_query` then `fallback_query`. `hard_cut` → Videos API → `runs/{run_id}/video/{scene_id}.mp4`; `still_with_motion`/`animated` → Photos API → `runs/{run_id}/images/{scene_id}.jpeg`. Returns `None` when both queries miss (E3-S3 chains to Replicate). Raises `PexelsError` on non-retryable API error.
- Module-level helpers: `_pick_best_video_file(video)` — highest height ≤ 1080px, tie-broken by width; `_pick_best_photo(photos)` — requires ≥ 1920×1080, minimum excess area.
- `src/models.py`: `ManifestEntry` gains `source: Optional[str]` and `file_key: Optional[str]`. `PexelsAcquireResult(scene_id, source="pexels", file_key, status="acquired")` added.
- `src/storage.py`: `R2Client.upload_bytes(key, data, content_type)` added.
- `src/exceptions.py`: `PexelsError` added.
- Rate limiting: exponential backoff on 429 — up to 3 retries (1s, 2s, 4s).
- No new ENV vars (uses existing `PEXELS_API_KEY`, `PEXELS_PER_PAGE`). No new dependencies.
- 121 total tests passing (26 new). End-to-end smoke test deferred to E3-S3 (requires orchestrator route).
**Promoted to backlog:** none

---

## [E6-S1] End-to-end pipeline UI (Runs + Storyboard + Manifest)
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/static/pipeline.html`: self-contained HTML page (inline CSS/JS, no frameworks). Slug validated before enabling submit; VO script textarea required. Sequentially calls `POST /runs` → `POST /runs/{run_id}/storyboard` → `POST /runs/{run_id}/manifest`. Per-step status dots: `○` pending / `◌` running / `●` complete / `✕` failed. Storyboard step shows 30–60s loading message. Manifest step displays scene count + clip type breakdown dict. Any failed step stops the chain, surfaces error detail, re-enables submit.
- `src/main.py`: `GET /` now serves `pipeline.html` (was `create-run.html`). `create-run.html` preserved in `/static` as reference.
- No new ENV vars. No new dependencies. 95 tests passing.
- Smoke test passed on Railway DEV: slug `messy-house-messy-head`, 10 scenes, all steps complete (still_with_motion: 4, animated: 3, hard_cut: 3).
**Promoted to backlog:** none

---

## [E2-S1] Asset manifest generation
**Completed:** 2026-05-22
**Sprint:** 2
**Handover:**
- `src/manifest.py`: `build_manifest(run_id, storyboard_data) → AssetManifest` — pure transformation, no API calls. Maps `visual_prompts.primary_stk → primary_query`, `fallback_stk → fallback_query`, `ai_generate → ai_generate_prompt`. Raises `ManifestError` on invalid storyboard. `clip_type_breakdown(manifest) → dict[str, int]` helper for summary stats.
- `src/routes/manifest.py`: `POST /runs/{run_id}/manifest` — reads `runs/{run_id}/storyboard.json` from R2 (→404 on missing), builds manifest (→422 + run_log `failed` on bad storyboard), uploads `runs/{run_id}/asset_manifest.json`, updates run_log `asset_manifest: complete`. Returns `{status, manifest_key, scene_count, clip_type_breakdown}`.
- `src/models.py`: `ManifestEntry`, `AssetManifest`, `ManifestResponse` added. E3 asset acquisition reads `AssetManifest.entries` — each entry has `primary_query`, `fallback_query`, `ai_generate_prompt`, `clip_type`, and `status: "pending"`.
- `src/exceptions.py`: `ManifestError` added.
- `src/main.py`: manifest router registered via `app.include_router(manifest_router.router)`.
- R2 key pattern: `runs/{run_id}/asset_manifest.json`.
- `tests/test_manifest.py`: 27 tests, all passing. 95 total.
- No new ENV vars. No new dependencies.
**Promoted to backlog:** none

---

## [E6-S0] Minimal run creation UI
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/static/create-run.html`: self-contained HTML form (inline CSS/JS). Slug validated with `/^[a-z][a-z0-9-]*[a-z0-9]$/` before enabling Submit. POSTs to `/runs`, displays `run_id` + `storage_prefix` on 201, surfaces error detail on non-201, catches network errors.
- `src/main.py`: `GET /` serves `create-run.html` via `FileResponse`. `_STATIC_DIR = Path(__file__).parent / "static"` — future pages/assets go here.
- No `StaticFiles` mount — skipped to avoid `aiofiles` dependency (page has no external assets). Add `StaticFiles` + `aiofiles` when E6-S1 introduces `app.js` / `style.css`.
- No new ENV vars. No new dependencies. 68 tests passing.
**Promoted to backlog:** none

---

## [E1-S3] Storyboard generation
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/storyboard.py`: `generate_storyboard(script, settings) → Storyboard` (async). Internally: `_call_claude_api` uses `AsyncAnthropic` with prompt caching (`cache_control: ephemeral`) on the v0.4 system prompt. `_parse_storyboard_response` splits Claude text output on `---` into GLOBAL / SCENE blocks / SUMMARY, then delegates to `_parse_global`, `_parse_scene`, `_parse_summary`.
- `src/routes/storyboard.py`: `POST /runs/{run_id}/storyboard`. On success: uploads `storyboard.json` to `runs/{run_id}/storyboard.json` and calls `update_run_log(..., "complete", output_url=key)`. On failure: calls `update_run_log(..., "failed", error=str(exc))` then returns HTTP 500.
- `src/models.py`: `Storyboard` model — the `global` field is aliased (`Field(alias="global")`); always serialise with `model_dump(by_alias=True, mode="json")`. `StoryboardScene.clip_type` validated as `Literal["hard_cut", "still_with_motion", "animated"]`.
- `src/exceptions.py`: `StoryboardAPIError` (Claude failures), `StoryboardParseError` (parse failures).
- `src/storage.py`: `update_run_log` now accepts optional `error: str` to persist failure messages to `run_log.json`.
- `tests/test_storyboard.py`: 21 tests (parser unit + route integration). Route mock pattern: `patch("src.routes.storyboard.generate_storyboard", new_callable=AsyncMock)`.
- Response field is `storyboard_key` (R2 key path), not `storyboard_url` — Drive was removed in E1-S2b.
- 68 total tests passing.
**Promoted to backlog:** none

---

## [E1-S2b] Migrate storage from Google Drive to Cloudflare R2
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/storage.py`: `R2Client(account_id, access_key_id, secret_access_key, bucket_name)`. Methods: `create_run_folder(run_id) → prefix`, `upload_json(key, data)`, `get_json(key) → dict`, `update_run_log(run_id, step, status, output_url=None)`. R2 is flat — all "folders" are key prefixes; no folder creation needed.
- `src/exceptions.py`: `StorageError` — the single domain exception for all storage failures. Catch in routes, raise from storage.py.
- `src/models.py`: `RunCreateResponse.storage_prefix` replaces `drive_folder_id`. `StepLog.output_url: Optional[str]` added.
- `src/config.py`: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` — all required.
- `src/routes/runs.py`: run_id built as `{today}_{slug}` in route; passed to `R2Client.create_run_folder(run_id)`.
- `tests/test_storage.py` (18 tests) + `tests/test_runs.py` (13 tests) + `tests/test_health.py` updated. 47 total passing.
- Key pattern for E1-S3: `storage.upload_json(f"runs/{run_id}/storyboard.json", data)` then `storage.update_run_log(run_id, "storyboard", "complete")`.
- Railway DEV bucket: `content-factory-dev`. Account ID token type: **Account API Token** (not User API Token).
**Promoted to backlog:** none

---

## [E1-S2] Google Drive integration
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/exceptions.py`: `DriveError` — base exception for all Drive failures. Catch in route handlers; never let it propagate as an untyped 500.
- `src/models.py`: `StepStatus` enum (`pending`/`complete`/`failed`), `StepLog`, `RunLog` (run_log.json schema), `RunCreateRequest` (slug validator), `RunCreateResponse`. `PIPELINE_STEPS` tuple is the canonical step order for all stories that write to run_log.json.
- `src/drive.py`: `DriveClient(service_account_json_b64)` — init from base64 SA JSON string. Key methods: `create_run_folder(slug, root_folder_id) → (run_id, folder_id)` (idempotent, reuses existing folders by name); `upload_json(data, filename, folder_id) → file_id`. Module-level `_build_run_log(run_id)` available for tests.
- `src/routes/runs.py`: `POST /runs` router — validates slug, instantiates `DriveClient`, returns 201 `{run_id, drive_folder_id}` or 500 on `DriveError`. Import pattern for future routes: `from src.routes import runs as runs_router`.
- `src/main.py`: `runs_router` registered. Follow same pattern for all future routers.
- `tests/test_drive.py` (17 tests) + `tests/test_runs.py` (13 tests): Drive API fully mocked via `unittest.mock.patch`. Test fixture pattern: patch `src.drive.service_account.Credentials.from_service_account_info` and `src.drive.build`.
- 43 total tests passing.
**Promoted to backlog:** none

---

## [E1-S1] Railway service skeleton
**Completed:** 2026-05-22
**Sprint:** 1
**Handover:**
- `src/config.py`: `Settings` (pydantic-settings) — validates all 7 required ENV vars at startup. Import with `from src.config import get_settings`. Inject into routes via `Depends(get_settings)`.
- `src/main.py`: FastAPI app entry point. Lifespan hook crashes fast on bad ENV with a clear error log. `GET /health` live. Register all future routers here via `app.include_router()`.
- `tests/test_health.py`: 13 passing tests. Settings injection pattern: `app.dependency_overrides[get_settings] = lambda: settings`. ENV isolation in tests: `monkeypatch.delenv(key, raising=False)`.
- Railway DEV deployed and verified: `https://content-factory-dev-production.up.railway.app/health` → `{"status":"ok","environment":"dev"}`.
- All 8 ENV vars live in Railway Variables tab (including `LOG_LEVEL=INFO`).
- `railway.toml` (DEV) and `railway.prod.toml` (PROD) already correct — no changes needed.
**Promoted to backlog:** none
