# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last two sprints (P14, P13b) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P14] AI images per scene — S1 provider interface + tenant-level keys, S2 Settings page + project style, S3 Generate in the edit-image dialog, S4 spend cap
**Completed:** 2026-10-05
**Handover:**
- **Generation is manual and per scene (D104).** `POST /platform/studio/runs/{id}/scenes/{n}/generate {prompt}` (`cf_platform/interfaces/routes/studio_ai.py`) generates, stores `runs/{id}/images/scene_NN_ai_<hash>.png`, records the spend, then makes the scene an `ai_image` scene (storyboard version + manifest version). Nothing generates during acquisition. The order is deliberate: validate and cap-check, generate, record spend, only then write storyboard and manifest.
- **`ai_image` is a strategy, not a style.** `src/models.py`: `AssetStrategy` gains `ai_image`; `OPERATOR_SUPPLIED_STRATEGIES = ("upload", "ai_image")` is what acquisition, split / merge and the render guard test; `OPERATOR_SOURCES` / `AI_GENERATED_SOURCE = "ai_generated"` mark the file. `StoryboardScene.ai_prompt` and `ManifestEntry.ai_prompt` hold the operator's prompt. An empty AI scene reuses status `awaiting_upload`; `timeline.missing_assets_message` words it separately ("set to AI image"). Changing a scene's strategy releases an asset that no longer fits (an AI image does not fit a stock scene, and the reverse).
- **Providers:** `cf_platform/core/image_provider.py` — `ImageProvider` protocol, `KieImageProvider` (createTask, poll recordInfo, download; the key is not sent to the file host) and `OpenAIImageProvider`; `build_image_provider`. Plain httpx.
- **Tenant settings:** table `tenant_settings` (migration `0003`), `core/tenant_settings.py` (resolve: tenant setting, then Railway ENV), `core/secret_box.py` (Fernet), `core/postgres_tenant_settings.py`. `GET/PUT /platform/tenant/settings/image` never returns a key, only `key_hint`. Page `/settings` (`src/static/settings.html`), linked from the project pages. Changing `SETTINGS_ENCRYPTION_KEY` makes saved keys unreadable: resolution raises `SecretBoxError` (409) and the operator saves the key again.
- **Style:** optional `project.config.ai_image_style`, prepended at generation time (the stored `ai_prompt` is the operator's own words). Aspect ratio comes from the run's `settings.json`, else `IMAGE_DEFAULT_ASPECT_RATIO`.
- **Spend:** ledger `runs/{id}/ai_spend.json` (`core/ai_images.py`), appended per paid generation; `GET …/ai-spend`; the storyboard header shows `N · $spent / $cap AI images`. Cost per image is the configured estimate `IMAGE_COST_USD`, not read from the provider.
- **Studio:** the ✎ dialog has a third section (prompt textarea, Generate, spend line); the ✎ button is enabled before acquisition; an empty AI scene shows a dashed Generate button in its row; `acquirePlan` ignores `ai_generated` files when deciding "Re-acquire All". Demo mode mocks all of it.
- **New ENV vars** (ENV.md): `SETTINGS_ENCRYPTION_KEY`, `IMAGE_PROVIDER`, `KIE_API_KEY`, `OPENAI_API_KEY`, `KIE_IMAGE_MODEL`, `OPENAI_IMAGE_MODEL`, `IMAGE_QUALITY`, `IMAGE_RESOLUTION`, `IMAGE_DEFAULT_ASPECT_RATIO`, `IMAGE_TIMEOUT_S`, `IMAGE_POLL_INTERVAL_S`, `IMAGE_COST_USD`, `IMAGE_RUN_SPEND_CAP_USD`. **New dependency:** `cryptography` (Fernet; already present transitively). Decision logged: **D104**.
- **Post-close fix (2026-10-05, `fix(P14-S3)`):** the Postgres pools (`cf_platform/core/db.py`) now test a connection before handing it out. A DEV Postgres restart left dead connections in the pool and the first Generate returned a bare 500 (`AdminShutdown`); this applies to every database route. Generate also answers 503 with a message when the settings database is unreachable.
- **Known limits:** the kie.ai path is covered by mocked tests only — the smoke test used an OpenAI key; the spend cap was verified by automated tests, not on DEV; a replaced AI image stays in R2 (orphan files are not deleted); re-acquire on an AI scene fetches stock while the scene stays `ai_image`; no "Suggest prompt" (the prompt is prefilled from the voiceover). Tests: three new files plus edits; 2583 passing.
**Smoke test:** PASSED — 2026-10-05 on Railway DEV, operator ran steps 1–8: OpenAI key saved in Settings, edit-image dialog with prefilled prompt and cost line, first image, regenerate, empty AI scene with its Generate button, stock acquisition leaving AI scenes alone, render with AI images. The cap step was not run (covered by automated tests).
**Promoted to backlog:** none. Open item carried: API keys appear in DEV logs (SPRINT.md, open items).

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
