# Done — Completed Stories

_Entries added here when a story reaches Definition of Done._
_This file holds the last two sprints (P-UX3, P14b) plus every older entry whose smoke test is still DEFERRED (currently none) — an open deferral stays here until the operator clears it by name. Everything else is in DONE_ARCHIVE.md._

---

## [P-UX3] UI/UX redesign — S1 audit, S2 information architecture, S3 prototype, S4 decision (and the build, folded in)
**Completed:** 2026-10-11 (designed 2026-10-07, built 2026-10-08 in `83e333c` / `2e0bd93`, renderer fixes `58f361e` and `a199b76` after the smoke test)
**Handover:**
- **One shell on every page** (`src/static/ui/shell.js`, `shell.css`, `app.js`, `app.css`): foldable left panel (Projects; the open project's Overview / Ideas / Runs / Settings; Libraries; Settings), breadcrumbs on the page background, phone drawer. A run starts folded. Project pages are `/project?id=&tab=overview|ideas|runs|settings`; `/library?kind=`; `/settings?tab=integrations|defaults`. The prototype stays at `/prototype/`.
- **A run starts from one or several ideas or from a title alone** (`POST /platform/projects/{id}/runs`, `item_ids` optional, `title`, `brief`, `aspect_ratio`); ideas are editable (`PATCH …/shortlist/{item_id}`). Run rows carry voice source, language, format, derived progress (`cf_platform/core/run_progress.py`).
- **One five-step pipeline per run** (Script → Voice → Storyboard → Video → Metadata): the Script step chooses generate / paste / from a voiceover; `PUT /platform/studio/runs/{id}/voice-source` answers 409 `needs_confirmation` before an uploaded recording is replaced (the storyboard is discarded through the P14b marker). Run settings are a drawer. Storyboard scenes are cards: on-screen text inline, SFX, motion, split on a word, merge, pencil on the asset.
- **Tenant Integrations and Defaults** (`cf_platform/core/integrations.py`, migration `0004_tenant_defaults.sql`): a key saved in Settings wins over the Railway variable and reaches every route through `get_effective_platform_settings`; defaults for language, format, captions and the AI-image cap, inherited tenant → project → run (a run copies at creation).
- **Libraries** (`cf_platform/core/library.py`, `GET /platform/library/{kind}`): videos, audio, footage, AI generations, music & SFX, read from the run folders — nothing is indexed; asset ID = prefix + 6 hex of the key's hash; download through a blob.
- **Renderer (D107):** pans are drawn at 4× (quarter-pixel steps) and always have 10 % of the frame width to travel, in the FFmpeg render and the CapCut export; ken burns / zoom in / zoom out are enlarged 4× before `zoompan` so they no longer tremble. Pan scenes cost about twice, zoom scenes about four times the CPU of before, and about 200 MB per scene.
- **ENV vars added:** none. Migration `0004`. No new dependency. Decisions: **D105, D107**. Tests: 2738 passing, CI green on `a199b76`.
- **Not built (D105):** library "use in a scene", music chosen from the library, per-service default models, Research / Publishing panel entries, saved keys for Freesound / ElevenLabs / Replicate.
- **Not verified:** the operator has not re-rendered since the zoom fix (`a199b76`) — the shake was measured fixed on the operator's own images, not seen by them; saved keys were covered by unit tests, and the Integrations step of the smoke list was closed by the operator without notes — a full acquisition run with a saved key was not observed; which pages still feel crowded was never named.
**Smoke test:** PASSED — the operator walked the ten-step list on DEV on 2026-10-10 (one real 16:9 run, five scenes with their own uploads) and found two renderer defects, both fixed (D107); the remaining items were closed by them. The zoom fix is the one thing not re-checked by the operator.
**Promoted to backlog:** none. Candidates: a pan that is clearly visible on every still without a minimum zoom (decided against); "which pages feel crowded" when the operator next names them.

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


---
