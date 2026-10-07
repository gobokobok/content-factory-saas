# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last two sprints (P14b, P14) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P14b] Uploaded voiceover — S1 run creation choice + language seed + upload + transcript as script, S2 transcript review with timing-safe edits, S3 storyboard / timeline / render / CapCut from the upload, S4 guards + end-to-end test, S5 stop logging API keys
**Completed:** 2026-10-07 (built 2026-10-05, commit `dbec47d`)
**Handover:**
- **A run has two entry modes and a language.** `run.inputs.voice_source` (`generated` default | `uploaded`) and `run.inputs.language` (ISO 639-1; default the project's `config.language`, else `en`) are set at creation on the project page; no migration. Uploaded runs show Settings → Upload → Transcript → Storyboard → Video → Metadata and skip Script, Voice and the narration controls.
- **The seam is `voice_alignment`.** `POST …/studio/runs/{id}/voice/upload` stores the audio at `runs/{id}/voiceover/uploaded.<ext>`, Deepgram transcribes it in the run's language (background job, `voice/status`), and the result is a `voice_alignment` (`alignment_method = uploaded_deepgram_nova2`) plus a `script` artifact with `source: uploaded_vo`. Timeline, render and CapCut read it through `mp3_r2_key` unchanged. Code: `cf_platform/interfaces/routes/studio_voice.py`, `cf_platform/workers/voice_upload.py`, `_deepgram_transcribe` in `voice_production.py`.
- **Timing-safe edits** (`cf_platform/workers/transcript_edit.py`, `PATCH …/transcript`): replace a word, one to several, several to one, same-count replacement; deletions, additions and other many-to-many are refused with the reason (422). Locked (409) once a storyboard exists. Words carry no punctuation.
- **Guards and re-upload:** no words / too short / too long / Deepgram failure end the job in `error`; a language that looks wrong is a **warning** (wrong script or low confidence) with Keep / Change (`PUT …/language`) — it cannot catch same-script mismatches. Re-upload asks for confirmation and discards the storyboard (marker `runs/{id}/storyboard/discarded.json`, honoured by `latest_artifact_key`, acquisition and render) and empties the manifest.
- **Render:** one addition in `render_worker.py` — stale audio files in the local `voiceover/` folder are removed so a re-upload in another format cannot be picked up by the script's glob. Golden suite unchanged.
- **Keys in logs (S5):** `src/log_redaction.py` redacts `key=` / `token=` / `api_key=` values in the final formatted text of all handlers (messages, args, tracebacks); `httpx` request logging stays at INFO.
- **ENV vars added:** `VOICE_UPLOAD_MAX_MB`, `VOICE_UPLOAD_MIN_S`, `VOICE_UPLOAD_MAX_S`, `VOICE_LOW_CONFIDENCE`, `DEEPGRAM_COST_PER_MIN_USD`. No new dependency. Decision logged: **D106**. Tests: 62 new across three files; 2645 passing, CI green on `dbec47d`.
- **Not verified on DEV:** the guards, the re-upload confirmation, language `ru` (including Deepgram's `language=ru` on Nova-2, only tested against a mocked request) and the `key=` log check. Operator actions still open: rotate the Pixabay key (DEV now, PROD at release) and re-check PROD logs at the next `/prod-check` — both in SPRINT.md open items.
**Smoke test:** PASSED — the operator made two real Shorts on DEV with the uploaded-voiceover flow (commit `dbec47d`, deploy confirmed) and found no issues. The scripted steps were not run one by one; the items under "Not verified on DEV" above were not exercised.
**Promoted to backlog:** none. Candidate: punctuation-aware transcript (store Deepgram's punctuated words) if scene breaks from an uploaded VO read worse than from a script.

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

---
