# Backlog — Active Stories

_Contains the current and next sprints (P14b, P-UX3), the outlines for P15–P17, and open unassigned stories. Everything completed is in BACKLOG.md._
_Updated at each sprint boundary: move the completed sprint's block to BACKLOG.md._

---

## Platform Update outlines — Sprints P14b–P17

Detailed at each sprint boundary. Spec section numbers refer to the Pipeline & Platform Update specification (2026-10-03).

**EPIC 44 — Storyboard control (P13)** — done 2026-10-03: stories and handovers moved to BACKLOG.md. Open for P13b: whether split / merge and asset strategy need anything extra in the CapCut timeline file (new scene fields: `asset_strategy`; manifest: `asset_slot`, status `awaiting_upload`).

**EPIC 49 — CapCut export (P13b, D100)** — done 2026-10-04: stories P13b-S1..S4 in the EPIC 49 section below.

**EPIC 45 — AI images per scene (P14, D096, D104) — DONE 2026-10-05, stories P14-S1..S4 (handover in DONE.md); re-scoped at `/start-story` 2026-10-04.** Manual per-scene generation from the storyboard edit-image dialog (prompt field + Generate); no style generates images automatically. `ImageProvider` interface with kie.ai (default) and OpenAI clients, selected by tenant settings. Provider, model and API key live at tenant level (`tenant_settings`, migration 0003, Fernet-encrypted with `SETTINGS_ENCRYPTION_KEY`; Railway keys are the fallback) and are edited at `/settings`. Optional project-level `ai_image_style` prepended to every prompt. Per-run spend cap (`IMAGE_RUN_SPEND_CAP_USD`, default 2.00) with a cost readout. Files that mattered: `cf_platform/interfaces/routes/studio_ai.py`, `cf_platform/core/{image_provider,tenant_settings,secret_box,ai_images}.py`, `src/models.py` (strategy vocabulary), `cf_platform/workers/{acquisition_worker,timeline,storyboard_edit}.py` (operator-supplied scenes), `src/static/studio-v2.html` (pencil modal, `acquirePlan`), `ENV.md`. Not built (candidate follow-up): a "Suggest prompt" button that asks the Visual Director / Claude for a scene prompt, and the provider side-by-side test (skipped by the operator).

**EPIC 51 — Uploaded voiceover (P14b, new 2026-10-05)** and **EPIC 52 — UI/UX redesign (P-UX3 and the build sprint(s), new 2026-10-05)** go ahead of P15; their stories are below.

**EPIC 55 — Animation mode (Sprint P-AN1, new 2026-10-11, immediately after P-UX3 closes, ahead of EPIC 53)** — AI-image videos from a Visual Director storyboard with a master style and a continuity bible; stories P-AN1-S1..S6 in the EPIC 55 section below.

**EPIC 53 — Multi-language: Russian (new 2026-10-05, after P-AN1, before P15)** — see the section below.

**EPIC 46 — Research (P15, D094, D097, spec §2–5).** Project research page. Trend research: existing Google Trends, Reddit and YouTube adapters (D050) plus Google News, over a chosen time window, producing ~10 topics each with a summary and the evidence for why it is trending. Competitor research: port from `content-researcher` (D097), project-level channel list, publications from the last 24/48 hours with likes per 1,000 views and outlier score, daily snapshot job. Results are ticked into the shortlist with their evidence. Research must take the project's language and region into account (Russian projects need Russian-language trend and competitor sources — the reason EPIC 53 comes first). Open: orchestrator-with-specialists vs. parallel agents with a synthesis step (spec §26 D); **X.com** — ENV.md records it as excluded under the free-tier constraint, so including it needs a decision on a paid source.

**EPIC 47 — Publishing via n8n (P16, D098, spec §18–21).** `channels` table (tenant level: name, platform, n8n channel key), project default channel, per-run destinations with publish time. Endpoints `due` / `claim` / `result`; API key for n8n. n8n workflow for YouTube (upload early with YouTube's own scheduled-publish time), exported JSON committed to the repo. Publication status in Studio's Metadata stage, replacing the disabled "Upload to channel" button; fills `published_videos`. Instagram as a second destination if time allows. Depends on the Google API audit started in P12.

**EPIC 48 — Server-side Auto Advance (P17, spec §22).** The Studio toggle hands the run to the server-side pipeline (`full_pipeline.py`, HITL gates from P6-S3) so it continues with the browser closed. First task: confirm that pipeline writes the same artifacts in the same places as the stage-by-stage Studio flow, so an auto-advanced run opens cleanly for review. Define which stages may run unattended, where it stops on error or missing input, and add OpenAI direct as the image fallback (D096). Optional: one-way Telegram notifications (D093). **From the 2026-10-03 prod check:** the PROD service sleeps after 6–10 idle minutes (Railway app sleeping) and pipeline work runs as in-process background tasks, so a run with the browser closed would be stopped mid-flight — settle this first (keep the service awake while a run is active, or move the work off the web process).

**EPIC 50 — Word-anchored overlays and a curated SFX library (unplanned, proposed 2026-10-04).** Select a word in a scene to say where the on-screen text appears and where an SFX plays, instead of the fixed rules (text 0.3 s into the scene, SFX at scene start or +0.7 s — D076). Plus a small SFX library of good-quality sounds. Stories E50-S1..S3 in the EPIC 50 section below; not placed in a sprint.

**Parked by D099:** P11-S2 motion presets (EPIC 39), P11-S3 sub-scene asset timeline (EPIC 38), Format tracks, Analytics & attribution.

---

## EPIC 51 — Uploaded voiceover (Sprint P14b)

Operator request at the Sprint P14 review (2026-10-05). A second way into a run: upload a finished voiceover instead of writing a script and generating one. The existing `voice_alignment` artifact (`mp3_r2_key`, `word_timestamps`, `alignment_method`) is the seam — an uploaded VO writes the same artifact, so the storyboard worker, timeline, FFmpeg render and CapCut export read it exactly as they read a generated voice. Delivered as one sprint.

**Timing-safe edit rule (decision, 2026-10-05).** Word timings come from Deepgram and everything downstream (storyboard `start_word`/`end_word`, captions, timeline) keys off them. So transcript edits keep every word tied to audio: replace a word (it keeps its time slot); turn one word into several or several into one (the new words share the combined slot, split evenly); deleting a spoken word and adding an unspoken one are refused (text that must appear without being said is the scene's on-screen text). Scene boundaries move only through the Storyboard controls.

---

## [P14b-S1] Run creation choice, VO upload, Deepgram transcript as the script
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** —

### Goal
When the operator creates a run, they choose "Script → generated voice" or "Upload voiceover". For an upload, the audio is stored, Deepgram transcribes and aligns it, and the transcript becomes the run's script.

### Acceptance Criteria
- [x] Run creation (from a shortlist idea, and from the project page) offers the two entry modes; the mode is stored on the run (`voice_source`: `generated` | `uploaded`) and the default stays `generated`, so every existing run and flow is unchanged
- [x] `POST /platform/studio/runs/{run_id}/voice/upload` accepts mp3, wav and m4a, validated for MIME type, extension and size (limit from an ENV var documented in ENV.md); the file is stored under the run's voice prefix; 409 if the run already has a storyboard (re-upload rules are P14b-S4)
- [x] Deepgram transcription runs as a background job (the same pattern and polling as voice generation, `voice/status`), reusing `_align_audio` / `_normalize_word`; it writes a `voice_alignment` artifact with `alignment_method` marking it as an uploaded VO
- [x] The transcript text is stored as the run's script artifact with `source: uploaded_vo`, so `GET …/script` returns it and nothing else reads a different place
- [x] **Language seed (D106, operator 2026-10-05):** the run gets a `language` field (ISO 639-1, `en` default; `ru` accepted as a value but nothing Russian-specific is built in this sprint), set at run creation next to the entry mode, defaulting to the project's `config.language` and otherwise `en`. It is a per-run choice — a project that already has English runs is not locked to English. The upload's Deepgram call passes it as the transcription language
- [x] The Script and Voice stages are not shown for an uploaded run; Studio shows Upload → Transcript → Storyboard → …
- [x] A TraceEvent records the upload and the transcription (duration, word count, Deepgram cost if known)
- [x] Tests: each validation failure; happy path with Deepgram mocked; default mode unchanged; artifact shape equals a generated run's `voice_alignment`

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/voice_production.py` — `VoiceAlignmentArtifact`, `_align_audio`, `_normalize_word`, `build_voice_production_worker`
- `cf_platform/interfaces/routes/studio.py` — `studio_get_voice`, `studio_get_voice_status`, `studio_get_script`, the scene upload routes (validation pattern)
- `cf_platform/interfaces/routes/projects.py` — `create_run_from_shortlist`
- `src/static/studio-v2.html` — run creation and stage list; `src/static/project.html`
- `ENV.md`, `DECISIONS.md` — D104 (settings pattern), D093

### Handover
- **Run entry mode and language** live in `run.inputs` (`voice_source`: `generated` | `uploaded`, `language`: ISO 639-1) — no migration. `POST /platform/projects/{id}/runs` takes both; `language` defaults to the project's `config.language`, else `en`. `GET …/studio/runs/{id}/context` returns them; `PUT …/studio/runs/{id}/language` changes the language.
- **Upload:** `POST …/studio/runs/{id}/voice/upload` (`cf_platform/interfaces/routes/studio_voice.py`). Validation in `cf_platform/workers/voice_upload.py` (extension, MIME, size, file header). Stored at `runs/{id}/voiceover/uploaded.<ext>`. Transcription is a background job on the existing `voice/status` polling; `_deepgram_transcribe` (new, in `voice_production.py`) sends the run's `language`; `_align_audio` now delegates to it.
- **Artifacts:** `voice_alignment` with `alignment_method = uploaded_deepgram_nova2` (same shape as a generated run's), and a `script` artifact with `source: uploaded_vo` (`ScriptArtifact.source`, new optional field). Words are collapsed like the storyboard reads them, so editor indices are storyboard indices.
- **TraceEvents:** `voice_upload` (operator) and `transcribe` (cost from `DEEPGRAM_COST_PER_MIN_USD`).
- **UI:** `project.html` language + entry-mode pickers; `studio-v2.html` swaps the stage list (`applyVoiceSource`): Settings → Upload → Transcript → Storyboard → Video → Metadata; narration and subject controls removed for uploaded runs.
- **ENV vars added:** `VOICE_UPLOAD_MAX_MB`, `VOICE_UPLOAD_MIN_S`, `VOICE_UPLOAD_MAX_S`, `VOICE_LOW_CONFIDENCE`, `DEEPGRAM_COST_PER_MIN_USD`.
- **Files that mattered:** `cf_platform/interfaces/routes/studio_voice.py`, `cf_platform/workers/voice_upload.py`, `cf_platform/workers/voice_production.py` (`_deepgram_transcribe`), `cf_platform/interfaces/routes/projects.py`, `src/static/studio-v2.html` (`applyVoiceSource`, `loadUploadedVoice`), `ENV.md`.
---

## [P14b-S2] Transcript review stage with timing-safe word edits
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** P14b-S1

### Goal
Before the storyboard is built, the operator reads the transcript against the audio and corrects misheard words without being able to break the timing.

### Acceptance Criteria
- [x] A Transcript stage plays the uploaded audio and shows the words; clicking a word seeks the audio to it
- [x] `PATCH /platform/studio/runs/{run_id}/transcript` applies the edit rule: replace one word; replace one with several or several with one (new words share the combined slot, split evenly, monotonic); the whole edit is validated and rejected as a unit (422 with the reason) if it deletes a spoken word or adds an unspoken one
- [x] A "Rebuild from text" check: the operator may paste corrected text; it is accepted only if it maps onto the existing words under the same rule, and the message says which words changed
- [x] The edited words are written back to the `voice_alignment` artifact as a new version and the script artifact is regenerated from them; word indices (`start_word`/`end_word`) therefore stay valid because the word count only changes through the shared-slot rule
- [x] Edits are refused once a storyboard exists (409, with the pointer to re-do the transcript step and the P14b-S4 warning about the storyboard it would invalidate)
- [x] The Studio explains the rule in one sentence next to the editor and, for a refused edit, says what to do instead (on-screen text for unspoken words)
- [x] Tests: replace; one-to-many and many-to-one slot arithmetic (monotonic, sums to the original slot); delete and add refused; punctuation and contractions; script artifact follows the words; audio untouched

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P14b-S1 Handover
- `cf_platform/workers/storyboard_worker.py` — how `start_word`/`end_word` index `_normalize_deepgram_words`; coverage check
- `cf_platform/workers/storyboard_edit.py`, `cf_platform/workers/timeline.py` — word list consumers
- `src/static/studio-v2.html` — Script / Storyboard word rendering (`renderStoryboard`)
- `docs/RUNBOOK.md` — the misheard-caption finding ("pedals are wheel")

### Handover
- **Edit rule** is pure code in `cf_platform/workers/transcript_edit.py`: `apply_word_edits`, `edits_from_text`, `describe_edits`, `TranscriptEditError`. One word to one: keeps its slot; one to several: even split of the slot (monotonic, sums to the original); several to one: combined slot; several to the same number: each keeps its slot; other many-to-many, deletions and insertions are refused. A stretch of pasted text that changes 3 words into 2 is refused with "one word at a time".
- **Routes:** `GET/PATCH …/studio/runs/{id}/transcript`. PATCH takes `edits` or `text`, plus `dry_run`. 422 with the reason on refusal, 409 once a storyboard exists or while a transcription runs. A valid edit writes a new `voice_alignment` version and regenerates the script; the audio is untouched.
- **Studio:** Transcript pane — audio player, clickable words (shift-click selects several), inline edit, "Rebuild from text" with Check / Apply, the rule in one sentence.
- **Known limit:** transcript words carry no punctuation (stored like generated-run Deepgram words), so scene-break hints from sentence punctuation are weaker than with a pasted script.
- **Files that mattered:** `cf_platform/workers/transcript_edit.py`, `cf_platform/interfaces/routes/studio_voice.py`, `cf_platform/workers/storyboard_worker.py#_normalize_deepgram_words_with_display` (why indices are collapsed at upload), `src/static/studio-v2.html` (`renderTranscript`).
---

## [P14b-S3] Storyboard from the transcript; uploaded audio through timeline, render and CapCut
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 3
**Depends on:** P14b-S2

### Goal
From a reviewed transcript the operator creates the storyboard in the usual way, and everything after it behaves as for a generated voice.

### Acceptance Criteria
- [x] The StoryboardWorker takes its script from the uploaded run's script artifact and its words and timing from the uploaded `voice_alignment`; its coverage check passes on a faithfully transcribed VO and still catches a mismatch
- [x] `build_timeline`, the FFmpeg render and the CapCut export read the uploaded audio through `mp3_r2_key` with no change to their code paths; the golden render suite is unchanged
- [x] TTS settings (voice, pace, register) are hidden for uploaded runs; narration regeneration controls are removed rather than disabled
- [x] Studio stage list for an uploaded run: Upload → Transcript → Storyboard → Acquire → Render → Metadata, reachable in order
- [x] Metadata generation uses the transcript as the script
- [x] Tests: storyboard from an uploaded run; timeline equal in shape to a generated run's; render script built from an uploaded run; CapCut zip contains the uploaded audio; stage gating

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- P14b-S1 and S2 Handovers
- `cf_platform/workers/storyboard_worker.py`, `cf_platform/workers/timeline.py`, `cf_platform/workers/render_worker.py`, `cf_platform/workers/capcut_export.py`, `cf_platform/workers/youtube_metadata.py`
- `src/static/studio-v2.html` — stage list and gating

### Handover
- **Storyboard:** `POST /platform/workers/storyboard` uses the uploaded run's own script artifact and ignores the request body's script (`_uploaded_script_key` in `routes/workers.py`); `voice_alignment` is passed as before. `POST /platform/workers/voice` answers 409 for an uploaded run. Metadata reads the same script artifact, so it uses the transcript.
- **Timeline / render / CapCut** are unchanged and read the upload through `mp3_r2_key` (tests assert timeline voiceover key, render script and CapCut zip contents). One small addition in `render_worker.py`: after writing the alignment's audio, other audio files in the local `voiceover/` folder are removed, so a re-upload in a different format cannot leave the old file for the script's glob to pick up. Golden suite unchanged.
- **Studio:** `createStoryboard()` reads the transcript for uploaded runs; stage gating follows the stage list.
- **Files that mattered:** `cf_platform/interfaces/routes/workers.py`, `cf_platform/workers/render_worker.py`, `cf_platform/interfaces/routes/_helpers.py#prepare_run_timeline`, `tests/cf_platform/p13_helpers.py`.
---

## [P14b-S4] Guards and end-to-end tests for the upload path
**Epic:** E51 — Uploaded voiceover
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 2
**Depends on:** P14b-S3

### Goal
Bad input and re-uploads fail with a clear message instead of producing a broken run.

### Acceptance Criteria
- [x] Unreadable or non-audio files, silent audio, audio shorter than a minimum and longer than a maximum (both from ENV vars) are refused before or right after Deepgram, with a message in Studio
- [x] Deepgram returning no words ends the job in `error` with a readable message, not a stuck `running`; if Deepgram detects a language other than the run's `language`, Studio shows a warning with the detected language and lets the operator confirm or change the run's language (not a hard failure)
- [x] Re-uploading on a run that already has a transcript or storyboard asks for confirmation and says what will be discarded (storyboard, acquired assets, anchors); on confirm it invalidates them, as the storyboard re-run warning already does
- [x] One end-to-end test: create an uploaded run, upload (Deepgram mocked), edit a word, build the storyboard, render script built, timeline valid
- [x] DEV smoke test steps written into the Handover for the operator: upload an mp3, correct a misheard word, storyboard, acquire, render

### Definition of Done
- [x] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [x] Human touchpoint (closes the sprint): the operator creates an uploaded-VO run on DEV and renders a video from it

### Files to read
- P14b-S1..S3 Handovers
- `docs/TESTING.md`; memory note on the storyboard re-run warning (regenerating invalidates acquired assets)
- `cf_platform/interfaces/routes/studio.py` — storyboard regenerate warning

### Handover
- **Guards:** file header check, size, min / max length (`VOICE_UPLOAD_MIN_S` / `MAX_S`, measured by Deepgram), no words, Deepgram failure and unexpected crash all end the job in `error` with a readable message. A job never stays `running`.
- **Language mismatch is a warning, not an error** (as amended 2026-10-05). Deepgram is told the run's language, so it cannot report a mismatch; `language_warning` (in `voice_upload.py`) uses two signals: wrong script (Cyrillic vs Latin) and mean word confidence below `VOICE_LOW_CONFIDENCE`. It is stored in the job record, returned by `voice/status` and `GET …/transcript`; Studio shows a banner with "Keep" / "Change" (`PUT …/language`, which marks the warning acknowledged; a changed language means upload again). It cannot catch e.g. French audio in an English run.
- **Re-upload:** 409 `needs_confirmation` with the list of what is discarded; with `?confirm_discard=true` the storyboard is discarded by a marker (`runs/{id}/storyboard/discarded.json`, honoured by `latest_artifact_key`, acquisition and render), the asset manifest is emptied (envelope kept), and editing unlocks.
- **Tests:** `test_p14b_transcript_edit.py` (19), `test_p14b_upload_routes.py` (35, including the end-to-end test), `test_log_redaction.py` (8). Suite at close: 2645 passed, CI green on `dbec47d`.
- **DEV smoke test steps (as given to the operator):** (1) create an "Upload voiceover" run (stage track has no Script / Voice); (2) upload a 20–60 s mp3 → transcript appears, no warning; (3) correct a word, split one into two, try to delete a word (refused), paste text with an added word (refused); (4) create the storyboard → words locked; (5) acquire, render and/or CapCut zip contains `voiceover/uploaded.mp3`; (6) re-upload with confirm → storyboard empty, editing works; (7) guards: renamed `.txt`, silent mp3, clip under 3 s; (8) language `ru` run with Russian audio (no warning), English audio in a `ru` run (banner); (9) a generated run still behaves as before; (10) DEV log shows `key=REDACTED`.
- **Smoke result and what is NOT verified:** the operator made two real Shorts on DEV with the uploaded-voiceover flow and found no issues. The scripted steps were not run one by one. Not verified on DEV: the guards (step 7), the re-upload confirmation (6), language `ru` — including Deepgram's `language=ru` on Nova-2, only tested against a mocked request — and the log check (10).
---

## [P14b-S5] Stop logging API keys; rotate the Pixabay key
**Epic:** E51 — Uploaded voiceover (rides in the sprint; unrelated to the upload path)
**Sprint:** P14b
**Status:** done
**Completed:** 2026-10-07
**Priority:** high
**Points:** 2
**Depends on:** —

### Goal
No provider API key appears in any log line, and the key that already leaked is replaced.

### Acceptance Criteria
- [x] `httpx` / `httpcore` loggers do not print request URLs containing `key=`, `api_key=`, `token=` or `apikey=` values; either a redacting log filter on the root handlers or `httpx` raised to WARNING — whichever keeps useful request logging for other hosts (state the choice in the Handover)
- [x] Test: a request to a URL with `?key=SECRET` produces no log record containing `SECRET`; covers Pixabay, Pexels and Freesound URL shapes
- [x] Other places that can print a key (exception messages with the URL, retry logs) checked and covered by the same filter or listed in the Handover
- [ ] Operator rotates the Pixabay key on DEV (and on PROD at release); the old key is revoked. The step is recorded as done in SPRINT.md open items — **carried to SPRINT.md open items (operator action)**
- [ ] PROD log re-checked for `key=` at the next `/prod-check` — **carried to SPRINT.md open items (operator action)**

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done` — two operator AC carried, see Handover

### Files to read
- `SPRINT.md` open items (finding of 2026-10-05); the raised task chip
- logging setup in `cf_platform/` and `src/` (find where handlers are configured), `src/` Pixabay adapter

### Handover
- **Choice: a redacting formatter, not `httpx` at WARNING.** `src/log_redaction.py` wraps the formatter of every root / uvicorn / httpx / httpcore handler (`install_log_redaction`, called from `_configure_logging` in `src/main.py`) and redacts `key=`, `api_key=`, `apikey=`, `token=`, `access_token=` values in the *final* text, so messages, `%s` args, exception messages and tracebacks are all covered while other request logging stays.
- **Other places checked:** the Pixabay and Freesound clients pass the key as a query parameter (covered); Pexels sends it in an `Authorization` header (never in a URL). `requests`/urllib3 log URLs only at DEBUG, which the app does not enable; they pass through the same formatter anyway.
- **Not done — operator actions, carried in SPRINT.md open items:** rotate the Pixabay key on DEV (and PROD at release) and revoke the old one; check DEV log for `key=` and re-check PROD at the next `/prod-check`.
- **Files that mattered:** `src/log_redaction.py`, `src/main.py#_configure_logging`, `tests/test_log_redaction.py`.
---

## EPIC 52 — UI/UX redesign (Sprint P-UX3 discovery and design, then build)

Operator request at the Sprint P14 review (2026-10-05). The product now has three levels the current UI grew into rather than was designed for: **project** (discovery and market analysis, idea shortlist, project settings) → **idea → run** (run settings, a pipeline of steps, each with several options). Settings exist at tenant, project and run level. Before building, understand the market and the current flow, then design and prototype. The UI stays plain HTML/JS (CLAUDE.md hard constraint).

---

**Status 2026-10-08:** the operator approved the prototype after six review rounds (`docs/ux/REVIEW.md`) and asked for it to be applied to the real DEV app, so the build sprint was folded in and S4's separate build-story drafting was skipped. Built: shell, project pages, run without an idea, idea editing, one five-step pipeline with the Script step choosing the source (`PUT …/voice-source`), run settings drawer, storyboard cards, Integrations and Defaults (migration 0004), tenant-wide Libraries, derived run progress. **Not built (listed in D105):** library "use in a scene", music from the library, per-service default models, Research / Publishing panel entries. **Open:** the operator's pain points for `docs/ux/AUDIT.md` section 1; smoke test on DEV.

## [P-UX3-S1] Audit of today's flow and review of comparable tools
**Epic:** E52 — UI/UX redesign
**Sprint:** P-UX3
**Status:** in-progress
**Priority:** high
**Points:** 3
**Depends on:** P14b (so both entry paths are in the audit)

### Goal
A written picture of where today's UI is hard to use and of what comparable products do well, so the redesign argues from evidence.

### Acceptance Criteria
- [ ] `docs/ux/AUDIT.md`: the current flow screen by screen (login, project list, project, shortlist, Studio stages for both entry modes, Settings) with friction points named, each tied to a screen and to something observed (operator reports in memory/handovers, steps needed for a task, dead ends)
- [ ] A review of at least six comparable tools (e.g. Opus Clip, InVideo, Pictory, Descript, CapCut, VidIQ) covering: how projects and runs are structured, how ideation/research feeds production, how multi-step pipelines with options are presented, where settings live. Sources named; findings summarised in our own words
- [ ] A short list of patterns worth adopting and mistakes worth avoiding, each traced to a finding
- [ ] The operator's own pain points are collected in a short session or list and recorded as the first section

### Definition of Done
- [ ] All AC checked · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator reads the audit and adds or corrects points

---

## [P-UX3-S2] Information architecture: project → idea → run, and where settings live
**Epic:** E52 — UI/UX redesign
**Sprint:** P-UX3
**Status:** in-progress
**Priority:** high
**Points:** 3
**Depends on:** P-UX3-S1

### Goal
A navigation and settings model the whole product fits into, including the pages P15 (research) and P16 (publishing) will add.

### Acceptance Criteria
- [ ] `docs/ux/IA.md`: the page map for project level (overview, discovery / market analysis, shortlist, project settings), idea, and run (pipeline steps, run settings), plus tenant-level settings and where P15 and P16 attach
- [ ] A settings matrix: every setting that exists today (image provider, style, aspect ratio, caption style, TTS, music, SFX, channel later) plus **language** (project default, per-run override, never locked by earlier runs; shown where the operator creates a run and in the run header) placed at tenant, project or run level, with the inheritance rule (tenant → project → run) and what the operator sees when a run overrides a default
- [ ] Pipeline-step options: a rule for how a step with several options is presented (defaults, advanced, per-scene overrides) applied to each current step
- [ ] Both entry modes (generated and uploaded voiceover) and both render paths (FFmpeg, CapCut) shown in the flow
- [ ] Mobile and desktop: which screens must work at phone width
- [ ] Anything that needs a backend or data-model change is listed, not assumed

### Definition of Done
- [ ] All AC checked · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator approves or corrects the page map and settings matrix

---

## [P-UX3-S3] Clickable static prototype of the key screens
**Epic:** E52 — UI/UX redesign
**Sprint:** P-UX3
**Status:** in-progress
**Priority:** high
**Points:** 4
**Depends on:** P-UX3-S2

### Goal
The operator clicks through the redesigned product with demo data before anything is built.

### Acceptance Criteria
- [ ] Plain HTML/CSS/JS prototype under `docs/ux/prototype/` (no framework, no backend), served the way the demo mode is served today
- [ ] Screens: project list, project overview with discovery and shortlist, idea → create run (both entry modes), the run pipeline view with step options and run settings, Settings at tenant and project level; desktop and phone width
- [ ] Visual direction follows `docs/UI_GUIDELINES.md` unless the audit argues for a change, in which case the guideline change is part of the S4 decision
- [ ] Reviewed with the operator in at least one round; changes made and the decision on each recorded in `docs/ux/REVIEW.md`

### Definition of Done
- [ ] All AC checked · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator clicks through it and approves or redirects

---

## [P-UX3-S4] Design decision and build plan
**Epic:** E52 — UI/UX redesign
**Sprint:** P-UX3
**Status:** in-progress
**Priority:** high
**Points:** 1
**Depends on:** P-UX3-S3

### Goal
The approved design is recorded and turned into stories for the build sprint(s).

### Acceptance Criteria
- [ ] D105 in DECISIONS.md: the chosen structure, settings model and any change to `docs/UI_GUIDELINES.md`
- [ ] Build stories drafted in the `/add-story` format, sized, ordered so the pipeline stays operable throughout (the old screens are replaced behind a switch or one area at a time), with the backend changes from the IA listed as their own stories
- [ ] The roadmap in SPRINT.md and the P15 outline updated for the new project structure
- [ ] CLAUDE.md "Current sprint" updated

### Definition of Done
- [ ] All AC checked · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

---

## EPIC 55 — Animation mode: AI-image videos from a Visual Director storyboard (Sprint P-AN1)

Operator request 2026-10-10, placed 2026-10-11 as the **immediate continuation after P-UX3 closes** (ahead of EPIC 53). A run can be made entirely from generated images in one consistent style: the operator picks Animation in the run settings, gives a master style, and gets a storyboard whose every scene carries a visual concept, keywords and a pre-filled image prompt, with recurring characters, props and settings held in an editable continuity bible. Reference inputs (operator's own, outside the repo): `visual_director_prompt_v4.1.md` and a 170-scene sample storyboard with five images generated from it on Nano Banana.

**Scope decisions (operator, 2026-10-10 / 11):**
- **First target is sub-minute videos in both 9:16 and 16:9.** One storyboard call is enough; chunked storyboard generation for long-form is deferred.
- **Characters come from the Visual Director**, stored as a continuity bible on the run that the operator can edit before generating. Not part of the master style (it is appended to every scene, including scenes with no character), and not manual-only.
- **No reference images in this sprint.** The operator's five test images held the character from text alone (same hair, glasses, sweater, scrunchie); what drifted was whatever the description left open (sweater pattern, face rendering in one shot). Tighter bible entries are the first remedy.
- **Image model: Nano Banana.** kie.ai lists `nano-banana-2` on the same `createTask` endpoint and `input` shape the current provider uses (web check 2026-10-11, third-party documentation — confirm against kie.ai's own docs in S6). The operator's tests used "Nano Banana 2.1"; whether kie.ai offers that exact version is unverified.

**Findings from the sample that shape the stories:**
- About 1,700 of each sample prompt's 2,400 characters are the master style repeated. The model writes only the scene-specific part; code assembles the rest (S3).
- The sample images have inconsistent letterbox bars and panel borders, and the "keep the lower 20% calm" line produced a dark band at the bottom. The fixed lines get a full-bleed instruction and the lower-20% line is added only where a scene has an overlay (S3).
- The renderer has `ken_burns`, `zoom_in`, `zoom_out`, `pan_right`, `pan_left`, `static`. Push-ins, pullbacks, lateral drifts and holds map onto these; tilts and parallax do not (S2 keeps the free text as a note).

**Decision to log at sprint start (`/decide`, next free number):** animation mode as a second storyboard path; the continuity bible; bulk generation as an operator-triggered job, which amends D104 ("generated per scene on demand").

**Deferred, not in this sprint:** chunked storyboard generation for long-form (with E54-S1); character reference sheets with a reference-capable model; vertical pans; a shot-variety check in code.

**Human touchpoint:** the operator makes one sub-minute run in 9:16 and one in 16:9, each from script to rendered video with generated images in the master style.

---

## [P-AN1-S1] Run settings: visual mode and master style
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 3
**Depends on:** P-UX3 closed

### Goal
A run says whether it is made from stock footage or from generated images, and carries the master style its images are generated in.

### Acceptance Criteria
- [ ] `settings.json` gains `visual_mode` (`stock` | `ai_animation`, default `stock`) and `master_style` (free text, default empty); existing runs load unchanged
- [ ] The run settings drawer shows the visual mode and, when Animation is chosen, a master style text area
- [ ] The run's master style defaults to the project's `ai_image_style` (project → run inheritance, same pattern as language and format); a value set on the run wins
- [ ] Visual mode can be changed until a storyboard exists; after that the drawer shows it read-only with a note that changing it means regenerating the storyboard
- [ ] The existing `visual_style` dropdown (Realistic / Cinematic / …) is checked for what it actually drives and is hidden in Animation mode if it has no effect there
- [ ] Tests: settings round-trip, inheritance (run value, project fallback, empty), old `settings.json` without the new keys

### Definition of Done
- [ ] All AC checked · CI green · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `src/models.py` — `VideoSettings`
- `src/routes/runs.py` — settings GET/POST
- `cf_platform/core/integrations.py` — `project_run_defaults`, `resolve_run_values`
- `src/static/studio-v2.html` — run settings drawer (`#settings-drawer`)
- `src/static/project.html` — `ai_image_style` field
- `DECISIONS.md` — D105 (tenant → project → run settings)

### Handover
_(blank)_

---

## [P-AN1-S2] Animation storyboard: the Visual Director prompt, structured
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 8
**Depends on:** P-AN1-S1

### Goal
In Animation mode the storyboard step produces scenes with a visual concept, keywords, shot description and a pre-filled image prompt, plus a continuity bible, using the Visual Director's method on the run's real voiceover timing.

### Acceptance Criteria
- [ ] The storyboard worker picks its prompt from the run's `visual_mode`; the stock path is unchanged (golden / existing tests still pass)
- [ ] The animation prompt adapts Visual Director v4.1 sections 1–3 and 5–7 (narrative analysis, concept development, continuity bible, shot planning and variety, narration fit, prompt structure). Its timing section is replaced by the existing word-index contract: the model returns `start_word` / `end_word`, Python derives durations
- [ ] Output is JSON, not markdown. The storyboard gains a `continuity` list (`id`, `kind`: character | prop | setting, `name`, `description`); each scene gains `visual_concept`, `visual_keywords`, `shot` (size, angle), `entities` (bible ids used), `motion_note` (free text), and `ai_prompt` holding **only the scene-specific description** — no style block, no bible text, no aspect ratio
- [ ] Every scene is created with `asset_strategy = ai_image`; no stock queries are required in this mode
- [ ] Scene length: 1.0–5.0 s in both formats. A scene over the limit is not split in Python by copying its prompt; it is flagged on the storyboard for the operator
- [ ] `motion_effect` is set from the model's choice among the existing `MOTION_EFFECTS`; `motion_note` keeps the original wording
- [ ] Overlays map to the existing `on_screen_text` / `on_screen_text_type`; the model does not invent overlay copy
- [ ] The run's master style is passed to the model as context (so concepts fit the style) but is not echoed in the output
- [ ] The review pass either handles the new fields or is skipped in this mode — decided and noted in the handover
- [ ] `docs/PROMPTS.md` gets the animation prompt and a changelog entry; the prompt version is recorded on the artifact
- [ ] Tests: prompt selection by mode, parsing and validation of the new fields, entity ids resolve to bible entries, 5 s rule, old storyboards without the new fields still load

### Definition of Done
- [ ] All AC checked · CI green · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/workers/storyboard_worker.py` — `_GENERATE_SYSTEM_PROMPT_V013`, `_generate`, `_reify_scene`, `_split_long_scenes`, `_review`, `_sanitize_storyboard_data`
- `src/models.py` — `StoryboardScene`, `Storyboard`, `MOTION_EFFECTS`, `effective_asset_strategy`
- `src/validators/storyboard_validator.py`
- `docs/PROMPTS.md` — current version and changelog format
- `cf_platform/workers/visual_director_worker.py` — the P11 worker of the same name plans stock shots; do not confuse or reuse without checking
- `CONVENTIONS.md#async-function-discipline`, `docs/TESTING.md`

### Handover
_(blank)_

---

## [P-AN1-S3] Image prompt assembled in code
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 3
**Depends on:** P-AN1-S2

### Goal
The text sent to the image model is built from parts — scene prompt, bible descriptions, fixed lines, master style, aspect ratio — so the style is identical on every image and can change without regenerating the storyboard.

### Acceptance Criteria
- [ ] One pure function builds the prompt in this order: scene `ai_prompt` → descriptions of the scene's `entities`, verbatim from the bible → fixed lines → master style → aspect phrase ("Vertical 9:16" / "Horizontal 16:9")
- [ ] Fixed lines: no readable text, letters or numerals; full-bleed, no borders, no letterbox, no panel frame. The "keep the lower part calm" line is added only when the scene has on-screen text
- [ ] Master style resolves run → project `ai_image_style` → none
- [ ] The per-scene Generate route uses this function for runs in Animation mode; stock-mode runs keep today's behaviour (project style, then prompt)
- [ ] The stored `ai_prompt` stays scene-specific; the assembled text is what the scene's edit dialog shows as a read-only preview
- [ ] Tests: ordering, each part optional, overlay-conditional line, unknown entity id ignored with a warning, stock-mode output unchanged

### Definition of Done
- [ ] All AC checked · CI green · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/core/ai_images.py` — `build_prompt`
- `cf_platform/interfaces/routes/studio_ai.py` — `studio_generate_scene_image`, `_project_style`, `_run_aspect`
- `DECISIONS.md` — D104

### Handover
_(blank)_

---

## [P-AN1-S4] Studio: scene cards and an editable continuity bible
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 5
**Depends on:** P-AN1-S2, P-AN1-S3

### Goal
The operator reviews an animation storyboard as scene cards with concept, keywords and prompt, and edits the characters, props and settings in one place before spending on images.

### Acceptance Criteria
- [ ] In Animation mode each scene card shows the visual concept, keywords, shot, the image prompt (editable) and which bible entries it uses; stock-only controls (search queries, image/video strategy) are hidden
- [ ] A Continuity panel on the Storyboard step lists the bible entries; the operator can edit a description, add an entry and remove an unused one
- [ ] Editing an entry marks the scenes that use it and already have an image as out of date, with one action to regenerate those scenes (uses the S5 job; shows the cost first)
- [ ] The scene's edit-image dialog is pre-filled from `ai_prompt` (not the voiceover line) and shows the assembled prompt preview from S3
- [ ] Regenerating the storyboard in Animation mode warns that existing generated images will no longer match their scenes
- [ ] Split and merge keep working: a split scene's second half gets an empty prompt and is flagged; a merge keeps the first scene's prompt
- [ ] Follows `docs/UI_GUIDELINES.md`; plain HTML/JS; demo-mode data covers an animation run

### Definition of Done
- [ ] All AC checked · CI green · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `src/static/studio-v2.html` — scene cards, `patchScene`, the edit-image dialog (`#pencil-ai-prompt`), demo data
- `cf_platform/interfaces/routes/studio.py` — scene patch endpoint, `_apply_scene_edit_to_storyboard`
- `cf_platform/workers/storyboard_edit.py` — split / merge rules (D102)
- `docs/UI_GUIDELINES.md`

### Handover
_(blank)_

---

## [P-AN1-S5] Generate all images for a run
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 5
**Depends on:** P-AN1-S3

### Goal
One action generates the image for every scene that does not have one, in the background, with the cost shown before it starts.

### Acceptance Criteria
- [ ] "Generate all images" on the Storyboard step shows scene count, estimated cost and remaining cap, and starts only on confirmation
- [ ] Runs as a background job with a concurrency limit from an ENV var; scenes that already have an image are skipped unless the operator asked for specific scenes (the S4 regenerate action)
- [ ] Progress is visible per scene; a failed scene is retried once, then reported with its reason and a per-scene retry — the rest of the job continues
- [ ] The job stops cleanly at the spend cap and says how many scenes are left; every paid generation is in the ledger even if a later step fails
- [ ] Starting the job twice does not double-generate; after a server restart the job can be started again and picks up the scenes still missing
- [ ] The per-run cap can be raised for a run from the confirmation dialog, up to a tenant maximum; documented in `ENV.md`
- [ ] The generation logic shared with the per-scene route lives in one pure async function; both routes are thin wrappers
- [ ] Tests: skip logic, cap stop mid-job, retry then failure, idempotent start, ledger entries

### Definition of Done
- [ ] All AC checked · CI green · decision logged (amends D104) · BACKLOG_ACTIVE.md status updated to `done`

### Files to read
- `cf_platform/interfaces/routes/studio_ai.py` — the per-scene route to factor
- `cf_platform/core/ai_images.py` — ledger and cap
- `cf_platform/interfaces/routes/workers.py` — the voice background task and `current_job.json` pattern
- `cf_platform/core/integrations.py` — `resolve_defaults` (spend cap)
- `DECISIONS.md` — D096, D104; `CONVENTIONS.md#async-function-discipline`

### Handover
_(blank)_

---

## [P-AN1-S6] Nano Banana as the image model, and the sprint smoke test
**Epic:** E55 — Animation mode
**Sprint:** P-AN1
**Status:** backlog
**Priority:** high
**Points:** 2
**Depends on:** P-AN1-S5

### Goal
Animation runs generate on the model the operator validated the look with, and the sprint ends with two rendered videos.

### Acceptance Criteria
- [ ] kie.ai's own documentation is checked for the Nano Banana model id, the accepted `aspect_ratio` values (9:16 and 16:9 must be accepted) and the price per image; findings recorded in the handover. As of 2026-10-11 third-party docs give `nano-banana-2` with `input.prompt`, `aspect_ratio`, `resolution` on `/api/v1/jobs/createTask`
- [ ] The model is selectable in Settings → Integrations without a code change; any request field the model needs beyond today's three is added behind the provider interface
- [ ] The per-image cost used for the estimate and the cap matches the selected model instead of one global `IMAGE_COST_USD`
- [ ] Provider test with a mocked transport for the new model's request and response
- [ ] Smoke test on DEV: one sub-minute run in 9:16 and one in 16:9, each from script to rendered video in Animation mode; character and style consistency noted in the handover, including any bible entries that had to be tightened

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`
- [ ] Human touchpoint: the operator watches both videos

### Files to read
- `cf_platform/core/image_provider.py` — `KieImageProvider`, `build_image_provider`
- `cf_platform/core/tenant_settings.py` — `resolve_image_config`
- `cf_platform/core/config.py` — `IMAGE_*`, `KIE_IMAGE_MODEL`
- `src/static/settings.html` — Integrations
- `ENV.md`

### Handover
_(blank)_

---

## EPIC 53 — Multi-language: Russian (planned stub; detail at the sprint boundary)

Operator request 2026-10-05. A video can be made in Russian end to end: script, generated voice, uploaded voice (P14b), storyboard content, on-screen text, captions, metadata, and the rendered video. Scheduled after the UI build and before P15, because P15 research needs the project's language and region.

**Decisions (operator, 2026-10-05):**
- **Language is a per-run setting** (`language`, seeded in P14b-S1) with an optional project default. It is not locked per project: a project that already has English videos can make a Russian one. Russian content will mostly live in separate projects, but nothing blocks mixing.
- **AI image prompts stay in English** even in a Russian video. Only what viewers read or hear is in the video's language.

**Story outline (not yet detailed):**
- **Script and storyboard prompts** take a language parameter (docs/PROMPTS.md v0.4 is English-written); voiceover lines, on-screen text and captions come out in the run's language; `ai_prompt` and visual descriptions stay English.
- **Voice:** Gemini TTS voice choice per language; pace and duration estimate (`_estimate_duration`) calibrated for Russian.
- **Uploaded VO:** Deepgram language from the run; coverage check and the P14b transcript edit rule tested on Cyrillic.
- **Text handling:** `_normalize_deepgram_words` and word-index logic tested with Cyrillic (е / ё, punctuation, hyphens) — unverified as of 2026-10-05, first test to write.
- **Render:** fonts with Cyrillic glyphs for captions (Standard, Punch) and on-screen text; a Russian case in the golden render suite; CapCut export checked with the same fonts.
- **Metadata:** YouTube title, description and tags in the run's language.
- **Studio:** language shown at run creation and in the run header; Studio's own labels stay as they are.
- **Human touchpoint:** the operator creates a Russian run (generated voice, and one with an uploaded VO), and renders a video with Russian captions and on-screen text.

---

## EPIC 49 — CapCut export (P13b) — done 2026-10-04

Stories P13b-S1..S4 and their handovers moved to BACKLOG.md at the P14 review (2026-10-05). Handover summary: DONE.md.

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

## [E54-S1] Chunked voiceover generation for long scripts
**Epic:** E54 — Voice reliability (new 2026-10-10)
**Sprint:** unassigned — operator-requested 2026-10-10, not in the D099 roadmap
**Status:** backlog
**Priority:** high
**Points:** 5
**Depends on:** —
**Blocks:** nothing in flight. Long scripts (~1,400 words, ~9 min of audio) are a coin flip on PROD until this lands.

### Goal
Generate the voiceover for a long script as several shorter Gemini TTS calls and merge them, so one dropped connection costs one chunk and not the whole job — and so a TTS failure is visible to the operator instead of silent.

### Evidence (PROD, run `6fe35dab`, 2026-10-10)
- `build_voice_production_worker` sends the whole script in **one** call (`_call_gemini_tts_sync`): no chunking, no retry, no explicit timeout.
- 1,422 words ≈ 9 min of audio ≈ 5–6 min of Gemini time. Job 19:06 ended with `TTS failed … peer closed connection without sending complete message body (incomplete chunked read)`; the worker swallowed it, fell back to proportional timestamps with `mp3_r2_key=""`, and reported **complete** — Studio showed no voiceover and no error.
- The same script on retry (19:20) succeeded: 26,183,610 bytes (~9m06s), Deepgram aligned 1,401 of 1,422 words.

### Mechanism (operator's request)
1. Split the script into chunks of about **500 words**, cutting at the nearest sentence end (`.`) at or after the target.
2. One Gemini TTS call per chunk, run concurrently up to a cap; each chunk retried (max 2).
3. The same delivery instruction (pace + style, D083) on every chunk.
4. Merge the PCM in order **before** the WAV wrap; one `generated.wav` is stored as today.
5. Deepgram runs **once** on the merged audio, so `word_timestamps`, the storyboard and the CapCut export see one voiceover as they do now.
6. Scripts under the chunk size keep today's single call.

### Acceptance Criteria
- [ ] `split_script_for_tts(text, target_words)` — pure function; cuts at the first sentence end at or after the target; no `.` found → cuts at the next `?`/`!`/newline, else at a word boundary; does not cut at abbreviations (`U.S.`, `Dr.`) or decimals (`3.5%`); concatenating the chunks returns the original text
- [ ] Chunk size, concurrency cap and retry count come from ENV vars (`VOICE_TTS_CHUNK_WORDS`, `VOICE_TTS_CONCURRENCY`, `VOICE_TTS_RETRIES`) documented in `ENV.md`; no hardcoded values
- [ ] Each chunk is retried on connection errors and empty responses; chunk results are merged in script order regardless of completion order
- [ ] A chunk that still fails after retries fails the voice job with a clear message; `voice/status` reports `failed` with the reason and Studio shows it with a retry action — no silent proportional fallback when TTS was attempted and failed
- [ ] Scripts at or under one chunk produce the same call as today (no behaviour change)
- [ ] `total_duration_s` and `word_timestamps` come from Deepgram on the merged audio; merged duration equals the sum of chunk durations
- [ ] TraceEvent records chunk count and per-chunk retries (cost tracking unchanged)
- [ ] Tests: splitter (sentence boundary, no-period fallback, abbreviations, decimals, round-trip), retry then success, retry exhausted → failed job, merge order and length, single-chunk path unchanged

### Open points to settle in the story
- **Seams:** a short silence between chunks (e.g. 150–300 ms) vs. none. Gemini may drift slightly in tone between calls; listen to a 3-chunk sample before fixing the value.
- **Concurrency cap** vs. Gemini rate limits for the paid key; start low (2–3).
- **Deepgram coverage:** `smart_format` returned 1,401 of 1,422 words (numbers merged). Check whether the storyboard coverage check and captions tolerate that on long scripts, or whether the missing words are real.
- Optional later: the same chunking for the Test voice and for regenerated narration.

### Files to read
- `cf_platform/workers/voice_production.py` — `_call_gemini_tts_sync`, `_tts_generate`, `_pcm_to_wav`, `build_voice_production_worker`
- `cf_platform/interfaces/routes/workers.py` — voice background task and `voice/status`
- `cf_platform/interfaces/routes/studio_voice.py` — voice status as Studio reads it
- `docs/TESTING.md`, `CONVENTIONS.md#async-function-discipline`

### Handover
_(blank)_

### Definition of Done
- [ ] All AC checked · CI green · DONE.md updated · BACKLOG_ACTIVE.md status updated to `done`

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
