> ## ⚑ ACTIVE DIRECTION — Content Factory v2 (Platform Track)
> As of 2026-06-13 the active work is the **Platform v2 track (Sprints P0–P7)**, defined at the end of this file and in **docs/v2_platform_plan.md** (decisions D047–D057).
> - **Sprint P1 complete** (16/16 pts). **Current sprint:** P2 — Lineage & Observability Store. **P2-S1 done** (smoke test deferred — Railway Postgres not yet provisioned). **Active story:** P2-S2 (Schema migrations).
> - Sprints **S14–S17** (video-UX polish) are **PAUSED** — they resume later behind the legacy adapter.
> - The legacy Script→Video pipeline (Sprints 1–13) keeps running in DEV/PROD, untouched (D047).
>
> _History below (Sprints 1–19) is retained as-is._

---

# Sprint 1 — Railway Foundation & Drive Integration

**Goal:** Deployable FastAPI service on Railway with Google Drive integration and storyboard generation via Claude API.
**Status:** done

---

## Stories

| ID | Title | Status |
|----|-------|--------|
| E1-S1 | Railway service skeleton (FastAPI, health check, ENV validation) | done |
| E1-S2 | Google Drive integration (service account auth, run folder creation, run_log.json init) | done |
| E1-S2b | Migrate storage from Google Drive to Cloudflare R2 | done |
| E1-S3 | Storyboard generation (Claude API call with v0.4 prompt, parse, upload to R2, update run_log.json) | done |
| E6-S0 | Minimal run creation UI (slug form → POST /runs → show run_id + Drive link) | done |
| E6-S1 | End-to-end pipeline UI (Runs + Storyboard + Manifest) — 3pts | done |

---

# Sprint 2 — Operator UI + Polish

**Goal:** Operator can run the full pipeline start to finish from the browser UI without touching the terminal or R2 console.
**Status:** done
**Velocity:** 8/8 planned + 1 bonus (E4-S4) = 37 pts

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| E1-S4 | Run list and artifact retrieval endpoints | 3 | done |
| E6-S2 | Operator UI — run list and pipeline runner | 5 | done |
| E6-S3 | Voiceover upload via presigned R2 URL | 2 | done |
| E5-S2 | Pacing calibration — sync scene durations to voiceover | 5 | done |
| E5-S3 | Visual-semantic matching improvement | 4 | done |
| E4-S2 | Captions and on-screen text overlay | 5 | done |
| E4-S3 | Ken Burns zoompan effect on static images | 3 | done |
| E4-S5 | Real-time captions from voiceover_line | 5 | done |
| E4-S4 | CLIP semantic reranking of Pexels results *(bonus)* | 5 | done |

---

# Sprint 3 — First Real Video + Audio Sync + Cost Foundation

**Goal:** Watch a complete rendered video produced entirely from the browser UI. Add ms-precise audio sync and start model cost routing.
**Status:** done
**Velocity:** 5/6 stories completed (15/18 pts = 83%). E5-S5 slipped to Sprint 4 (correctly anticipated in sprint notes).

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| E6-S4 | End-to-end production smoke test | 2 | done |
| E4-S6 | Subtitle style revision (Poppins Bold, TikTok-style) | 2 | done |
| E5-S4 | Word-level timestamp extraction via Deepgram | 5 | done |
| E8-S1 | Haiku schema validator — storyboard.json | 3 | done |
| E8-S3 | Haiku run log summarizer | 3 | done |
| E5-S5 | Pipeline reorder: VO-first with Deepgram-driven storyboard | 8 | slipped → Sprint 4 |

---

# Sprint 4 — Accurate Audio-Visual Sync

**Goal:** Operator watches a video where scene cuts land exactly on word boundaries. Full VO-first pipeline flow live in the UI — upload voiceover, run alignment, generate storyboard from real timestamps, render.
**Status:** done
**Velocity:** 13/13 pts (100%)
**Points:** 13

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| E5-S5 | Pipeline reorder: VO-first with Deepgram-driven storyboard | 8 | done |
| E4-S7 | Word-synced captions using Deepgram timestamps | 5 | done |

**Dependency order:**
1. E5-S5 — critical anchor. Full pipeline reorder (backend + UI rewrite). Smoke test: 20s VO → 20s video with on-beat cuts.
2. E4-S7 — starts after E5-S5 merges. Smoke test: captions track speech word-by-word in rendered video.

---

## Sprint 4 Definition of Done
- [x] VO-first pipeline flow works end-to-end from browser UI: upload VO → alignment → storyboard → manifest → assets → ffmpeg-script → render
- [x] Scene cut timing derived from Deepgram word timestamps (not guessed durations)
- [x] Storyboard prompt updated to v0.8 (not v0.7 — bumped further during E5-S5), receives word timestamps as input
- [x] Operator UI fully reordered to match new pipeline (Alignment step row present, VO upload at top)
- [x] Word-synced captions advance in sync with VO audio in rendered video
- [x] All stories have passing tests and CI green (512 passing)
- [x] **Human touchpoint:** operator watches a rendered Short with captions that track word-by-word

---

## Notes
- E5-S5 is the highest-risk story: storyboard prompt change requires few-shot examples with timestamp-aware scene construction. Allocate most of the sprint time to it.
- E4-S7 depends on E5-S5 being merged — do not start E4-S7 until E5-S5 smoke test passes.
- E5-S5 UI work is a full rewrite of pipeline.html step order — do not patch incrementally (see backlog note).
- Outstanding deferred smoke tests from Sprint 3: E5-S4 (needs DEEPGRAM_API_KEY on DEV), E8-S1, E8-S3 — these should be validated during E5-S5 smoke test session.

---

# Sprint 5 — Navigation, Performance, Auth & UI Redesign

**Goal:** URL-based navigation, performance fixes, single-operator login, and a redesigned three-panel UI that hides pipeline complexity from the operator.
**Status:** done
**Velocity:** 4/4 planned (S5-S3 deferred indefinitely; S5-S5 added as replacement) = 16 pts delivered
**Points:** 16 (S5-S3 deferred; replaced by S5-S5)

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S5-S1 | URL-based run navigation (fix refresh bug) | 2 | done |
| S5-S2 | Page load performance diagnosis + fixes | 3 | done |
| S5-S4 | UI redesign: 5-step collapsed pipeline + new visual design | 8 | done |
| S5-S5 | Single-operator password gate | 3 | done |
| S5-S3 | Multi-user auth + per-user run isolation | 8 | deferred |

**Execution order:** S5-S1 ✓, S5-S2 ✓, S5-S4 ✓, S5-S5 ✓ — Sprint 5 complete. S5-S3 deferred indefinitely (requires per-user R2 isolation; out of scope for POC).

---

## Sprint 5 Definition of Done
- [x] S5-S1: Refresh inside a run stays in the run. Deep link works.
- [x] S5-S2: `docs/PERF.md` written. At least 2 fixes applied. Load time measurably improved.
- [x] S5-S4: Three-panel UI, 4-section flow, light design, all CTAs functional end-to-end.
- [x] S5-S5: Login/logout working. All pipeline routes return 302 when unauthenticated. Tests cover login success/failure and auth gating.
- [x] All existing tests pass (535 total: 515 baseline + 20 new for S5-S5).
- [ ] CI green on merge.
- [ ] **Human touchpoint:** operator logs in, creates a run, completes full pipeline from Input to Download in the new UI.

---

# Sprint 6 — Product UX: Design System, Project Identity & Stage Polish

**Goal:** Implement the full product UX spec — consistent design system, human-readable project names, Save Draft / Create Storyboard input flow, table-based storyboard view, clickable asset media links, bounded video player with modal, and permanent stage locking (no regenerate in MVP).
**Status:** done
**Velocity:** 18/18 pts (100%)

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S6-S1 | Design system: color palette, typography, panel spacing | 3 | done |
| S6-S2 | Project Name as primary identifier (auto-slug, backend + UI) | 3 | done |
| S6-S3 | Input stage: Save Draft + Create Storyboard (lock mechanic) | 5 | done |
| S6-S4 | Storyboard stage: full-data table view (all scene fields) + permanent lock | 3 | done |
| S6-S5 | Assets stage: Description column + media link column | 2 | done |
| S6-S6 | Render Video: bounded player + modal + Download button | 2 | done |

---

# Sprint 7 — Smoke Test + Cost Optimization Foundation

**Goal:** Validate the full pipeline end-to-end on Railway DEV (clearing 10 deferred smoke tests), then establish the cost optimization layer with Haiku model routing.
**Status:** done
**Velocity:** 2/3 planned stories completed; S7-S2 superseded (manifest generation is deterministic — no Claude call). 6/8 pts delivered.
**Points:** 8

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S7-S1 | Full pipeline smoke test — validate all deferred smoke tests on Railway DEV | 3 | done |
| S7-S2 | E8-S2: Haiku model for manifest generation | 2 | superseded — manifest is deterministic (no Claude call) |
| S7-S3 | E8-S4: Model router utility — centralize all Claude API model selection | 3 | done |

---

## Sprint 7 Definition of Done
- [x] S7-S1: Operator completes full pipeline from login → download on Railway DEV. All 10 deferred smoke tests signed off. Zero blocking bugs.
- [x] S7-S2: Superseded — manifest generation is a pure deterministic function (no Claude call); adding Haiku would add cost/complexity for zero benefit.
- [x] S7-S3: `ModelRouter` class centralizes all Claude model strings. Cost per call logged (model, tokens, USD estimate). All existing Claude API calls refactored through router. Tests pass.
- [x] All existing tests pass. (612 total)
- [x] **Human touchpoint:** S7-S1 IS the human touchpoint — operator ran full pipeline on Railway DEV and signed off.

---

## Roadmap (approved)

| Sprint | Theme | Key stories |
|--------|-------|-------------|
| Sprint 8 | UI Polish & Workspace | Collapsible sidebar, pipeline status cleanup, storyboard table UX, project deletion |
| Sprint 9 | Project Details + Commit + Video Settings UI | Input → Project Details, commit modal, video settings selectors |
| Sprint 10 | TTS Voiceover Generation | ElevenLabs chunked TTS, auto-alignment |
| Sprint 11 | Audio Layer | Background music upload, audio controls, ffmpeg integration |
| Sprint 12 | Video Settings Pipeline Wiring + Publishing Metadata | Video settings → render, metadata generator + UI |
| Sprint 13 | Scale Foundation | Chunked storyboard generation, parallel asset acquisition, background render task |
| Sprint 14 | Creative Draft Foundation | Editable AI prompts, per-scene asset mode, Visual Style Prompt field, Global Values panel |
| Sprint 15 | Storyboard UX + Source Expansion | Sticky headers, Pixabay source, AI-driven historic vs realistic routing |
| Sprint 16 | Assets Overhaul + Replacement | Per-asset upload replacement, full descriptions, VO column |
| Sprint 17 | Project Report + Token Tracking | Token cost per call, Project Report pipeline step |
| Sprint 18 | API-First Pipeline | External API endpoint + webhook for N8N integration |
| Sprint 19 | Multi-tenant + Google OAuth | Google sign-in, per-user run isolation |

---

# Sprint 8 — UI Polish & Workspace

**Goal:** Fast, high-visibility UI improvements — no backend changes except project deletion. Collapsible sidebar, pipeline status simplification, storyboard table readability, storyboard settings header collapsible, and project deletion flow.
**Status:** planned
**Points:** 10

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S8-S1 | Collapsible sidebar — toggle hides/shows left panel; center + right expand full width | 2 | done |
| S8-S2 | Pipeline status simplification — remove step-level completion bars; global step circles are the only status indicator | 1 | done |
| S8-S3 | Storyboard table UX — text cells wrap (no truncation, no ellipsis), dynamic row height | 2 | done |
| S8-S4 | Storyboard settings header — collapsible grouped section (compact summary / expanded detail) | 2 | done |
| S8-S5 | Project deletion — header CTA + confirmation modal + `DELETE /runs/{run_id}` endpoint that purges R2 prefix | 3 | done |

**Execution order:** S8-S1 → S8-S2 → S8-S3 → S8-S4 are all independent frontend-only; S8-S5 adds a backend endpoint.

---

## Sprint 8 Definition of Done
- [x] S8-S1: Sidebar collapses via toggle button; center + right panels expand to fill width when collapsed; state preserved during session.
- [x] S8-S2: No "completed" banner or status bar inside any pipeline stage UI; global pipeline step circles are the sole completion indicator (5 states: grey/dashed-spin/yellow/green/red).
- [x] S8-S3: Every storyboard table cell wraps its text content; no `text-overflow: ellipsis`; row height expands with content; horizontal scroll still allowed.
- [x] S8-S4: Storyboard settings show one-line summary by default (Style / Aspect Ratio / Subtitles / Music); clicking expands to grouped detail (VIDEO STYLE + AUDIO sections).
- [x] S8-S5: Delete button in project header; confirmation modal shows exact warning text; confirmed delete removes all `runs/{run_id}/` keys from R2 and removes run from left panel without page reload.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator collapses sidebar to gain workspace for the wide storyboard table; deletes a test project.

---

# Sprint 9 — Project Details + Commit System + Video Settings UI

**Goal:** Rename "Input" → "Project Details" and restructure it as a proper configuration hub. Add the formal commit flow with confirmation modal and locked state. Add video settings selectors (UI only — no pipeline wiring yet).
**Status:** done
**Velocity:** 8/8 pts (100%)
**Points:** 8

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S9-S1 | Project Details tab — rename Input → Project Details; restructure into Content section (Name, Script, Voiceover) and Settings section | 3 | done |
| S9-S2 | Commit system — "Commit" CTA replaces "Create Storyboard"; confirmation modal with lock warning; ✓ committed state indicator | 3 | done |
| S9-S3 | Video settings UI — aspect ratio (9:16 / 16:9 / 1:1), visual style enum, subtitles toggle + style selector; stored in run config, no pipeline wiring yet | 2 | done |

**Execution order:** S9-S1 → S9-S2 (commit UI built on restructured Project Details); S9-S3 independent.

---

## Sprint 9 Definition of Done
- [x] S9-S1: Tab label reads "Project Details". Content section: Project Name, Script, Voiceover upload. Settings section visible below content. Existing functionality (Save Draft, VO upload) preserved.
- [x] S9-S2: "Commit" button replaces "Create Storyboard". Clicking opens modal with text: "After committing, you will NOT be able to modify: Project Name, Script, Voiceover. Do you want to continue? [Cancel] [Commit]". After confirming: Project Details locked read-only, ✓ green indicator shown. Triggers alignment + storyboard as before.
- [x] S9-S3: Aspect ratio selector (9:16 default), visual style dropdown (Realistic/Cinematic/Cartoonish/Documentary/Minimalist), subtitles toggle + style selector (TikTok / Classic) all render, persist in run config via `POST /runs/{run_id}/settings`, and survive page reload.
- [x] All existing tests pass (630 passing).
- [ ] **Human touchpoint:** operator fills Project Details, clicks Commit, reads the confirmation modal, confirms, and sees the section lock with a green ✓.

---

# Sprint 10 — TTS Voiceover Generation

**Goal:** Operator can provide a script with no audio file and have ElevenLabs generate the voiceover. Script is chunked, sent in parallel, merged as PCM, and stored as MP3. Alignment runs automatically — invisible to the user.
**Status:** planned
**Points:** 6

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S10-S1 | TTS VO generation — ElevenLabs chunked parallel requests, PCM merge via ffmpeg, auto-run alignment | 6 | done |

---

## Sprint 10 Definition of Done
- [ ] S10-S1: "Generate Voiceover" toggle available alongside "Upload VO" in Project Details. Script split at sentence boundaries (~1000-char chunks). All chunks sent to ElevenLabs concurrently (`asyncio.gather`). `previous_text`/`next_text` context params sent per chunk. PCM responses concatenated in order, encoded to MP3 via ffmpeg subprocess, stored as `runs/{run_id}/voiceover/generated.mp3`. Alignment (`POST /alignment`) runs automatically after generation — no user action required. `ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` added to `config.py` and `ENV.md`. Tests pass (ElevenLabs API mocked). DECISIONS.md D038 + D039 pre-exist.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator pastes a script, clicks "Generate Voiceover", sees a progress indicator, then the pipeline advances to Commit without requiring an audio file upload.

---

# Sprint 11 — Audio Layer

**Goal:** Background music as a first-class pipeline component. Operator uploads a background track, sets volume, enables voiceover ducking. Settings flow through to the ffmpeg render — replaces the hardcoded `music 0.15` constant.
**Status:** done
**Velocity:** 10/10 pts (100%)
**Points:** 10

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S11-S1 | Background music upload — presigned PUT to `runs/{run_id}/music/`, stored in R2, playback preview in UI | 3 | done |
| S11-S2 | Audio controls UI — volume slider (0–100%), voiceover ducking toggle, loop vs fit-to-duration mode; stored in run config | 2 | done |
| S11-S3 | Audio → ffmpeg integration — BG music key + volume + ducking settings passed into generated ffmpeg script; replaces hardcoded `music 0.15` | 5 | done |

**Execution order:** S11-S1 → S11-S2 (controls require upload widget to exist); S11-S3 depends on both.

---

## Sprint 11 Definition of Done
- [ ] S11-S1: Audio section in Project Details. Background music file picker → presigned PUT → R2 at `runs/{run_id}/music/bg.mp3`. Playback `<audio>` preview shown after upload.
- [x] S11-S2: Volume slider (0–100%, default 15%), voiceover ducking toggle (default ON), loop/fit-to-duration selector render and persist in run config.
- [x] S11-S3: ffmpeg script generator reads audio settings from run config. When BG music present: uses configured volume (not hardcoded 0.15). Ducking ON: applies `_DUCKING_FACTOR=0.4` volume multiplier. Loop mode sets `-stream_loop -1`; fit mode plays once. Tests cover each variant (686 total passing).
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator uploads a background track, sets volume to 40%, enables ducking, renders video, hears the track duck under the voiceover in the final output.

---

# Sprint 12 — Video Settings Pipeline Wiring + Publishing Metadata

**Goal:** Wire the stored video settings into the actual render pipeline (aspect ratio, visual style, subtitles). Fix two user-facing commit flow bugs. Add post-render publishing metadata generation with copy-to-clipboard UI.
**Status:** done
**Velocity:** 12/12 pts (100%)
**Points:** 12

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S12-S1 | Video settings → pipeline — aspect ratio into ffmpeg output dimensions, visual style into Replicate `ai_generate_prompt`, subtitles toggle enables/disables caption burn steps | 4 | done |
| BUG-001 | Storyboard commit: re-poll run log on fetch failure before showing error state | 2 | done |
| BUG-002 | Clear stale Save Draft error message on successful commit transition | 1 | done |
| S12-S2 | Publishing metadata generator — Claude Haiku post-render; title + 2 variants, YouTube description, Instagram description, hashtags, SEO tags; stored at `runs/{run_id}/metadata.json` | 3 | done |
| S12-S3 | Publishing metadata UI — display below video player after render; copy-to-clipboard per field | 2 | done |

**Execution order:** S12-S1 → BUG-001 → BUG-002 → S12-S2 → S12-S3

**Notes:**
- S12-S1: depends on S9-S3 ✓ and S11-S3 ✓ (both done)
- BUG-001/BUG-002: UI-only fixes; independent of S12-S1 but batched after it to keep focus
- S12-S2 depends on S12-S1 (needs render to be complete before metadata call)
- S12-S3 depends on S12-S2

---

## Sprint 12 Definition of Done
- [x] S12-S1: 9:16 project renders 1080×1920; 16:9 renders 1920×1080; 1:1 renders 1080×1080. Visual style value appended to Replicate `ai_generate_prompt` modifier (e.g. "cinematic, shallow depth of field"). Subtitles OFF skips both caption burn steps in ffmpeg script. Tests cover all aspect ratios and subtitle toggle.
- [ ] BUG-001: After a fetch error during storyboard Commit, UI re-polls `run_log.json` to check actual step status. If backend shows `complete`, green dot and ✓ Committed shown — no error. If backend shows `failed`, shows real error from log.
- [x] BUG-002: Any displayed error message is cleared when a Commit or Save Draft operation transitions to success. `✓ Committed` shown cleanly without stale error text.
- [x] S12-S2: `POST /runs/{run_id}/metadata` endpoint calls Claude Haiku with storyboard + project name as context. Stores `{title, alt_titles: [str, str], youtube_description, instagram_description, hashtags: [str], seo_tags: [str]}` at `runs/{run_id}/metadata.json`. Step `metadata → complete` in run log.
- [x] S12-S3: After render completes, metadata section appears below video player. Each field has a "Copy" button — clicking writes to clipboard and briefly shows "Copied ✓". No auto-posting to any platform.
- [x] All existing tests pass (734 total).
- [ ] **Human touchpoint 1:** operator renders a 16:9 project and downloads a wide-format video (1920×1080).
- [ ] **Human touchpoint 2:** operator clicks "Copy" on the YouTube description and pastes it directly into YouTube Studio.

---

## Deferred smoke tests to clear during this sprint
_(new threshold: 3 outstanding triggers integration session)_
- S9-S3: video settings persist + lock (aspect ratio, visual style, subtitles)
- S10-S1: ElevenLabs TTS generate flow (requires ELEVENLABS keys on DEV)
- S11-S1: music upload, preview, delete, re-upload
- S11-S2: audio controls persist, lock read-only after commit
- S11-S3: audible listen check — music ducks under voiceover in final.mp4

---

# Sprint 13 — Scale Foundation

**Goal:** Remove all hard ceilings on video length. Chunked storyboard generation handles scripts of any length. Parallel asset acquisition cuts acquisition time from hours to minutes. Background render decouples the render step from Railway's 60s request timeout.
**Status:** planned
**Points:** 13

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S13-S1 | Chunked storyboard generation — split script at paragraph boundaries into ~10-para chunks; run each as a separate parallel Claude call; re-number and merge into one `storyboard.json` | 5 | done |
| S13-S2 | Parallel asset acquisition — replace sequential per-scene loop with `asyncio.gather` in batches of 20; reduces 300-scene acquisition from ~15 min to ~30 s | 3 | done |
| S13-S3 | Background render task + polling — decouple `POST /runs/{run_id}/render` into an async background task; add `GET /runs/{run_id}/render/status` polling endpoint; UI already polls step status so no UI changes needed | 5 | done |

**Execution order:** All three stories are independent — no intra-sprint dependencies. S13-S1 and S13-S2 can be built in parallel. S13-S3 is the highest-risk item (Railway background task pattern).

---

## Sprint 13 Definition of Done
- [ ] S13-S1: Script of 30+ paragraphs produces a valid merged `storyboard.json`. Chunk boundaries never split mid-sentence. Scene numbers are contiguous (1, 2, 3 … N). Alignment timestamps sliced per-chunk and passed into each Claude call. Tests: chunk splitting, per-chunk call (mocked), merge + renumbering logic.
- [ ] S13-S2: Asset acquisition for a 50-scene manifest completes in under 60s on Railway DEV. Batch size configurable via `ACQUISITION_BATCH_SIZE` ENV var (default 20). Errors in one scene do not cancel other batches. Tests: batch grouping; partial failure handling; idempotent re-run.
- [ ] S13-S3: `POST /runs/{run_id}/render` returns HTTP 202 immediately; render runs in background. `GET /runs/{run_id}/render/status` returns `{status: "running"|"complete"|"failed", progress_pct: int}`. `run_log.json` updated to `render: complete` on finish. Tests: 202 immediate response; status polling; failure propagation.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator submits a 10-minute script; the pipeline completes without timeout errors; the downloaded video is the correct length.

---

# Sprint 14 — Creative Draft Foundation

**Goal:** Establish the core product concept shift — storyboard becomes an editable working layer, asset strategy moves to per-scene control, and the operator gains a free-text Visual Style Prompt that injects into every AI generation call.
**Status:** planned
**Points:** 11 (S14-S1 blocked pending screenshot)

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S14-S1 | Notion-like feature — details TBD (blocked: awaiting operator screenshot) | TBD | blocked |
| S14-S2 | Editable AI Prompt in storyboard table — `ai_generate_prompt` cell editable inline; `primary_query` fixed (read-only) | 2 | done |
| S14-S3 | Asset Mode column in storyboard — "Source" dropdown per row: Stock \| AI Generated; selecting Stock highlights primary_query cell; selecting AI Generated highlights ai_generate_prompt cell; drives acquisition routing | 3 | done |
| S14-S4 | Visual Style Prompt field — free-text input in Project Settings; saved in run config; injected as suffix into every Replicate/Flux prompt call | 2 | planned |
| S14-S5 | Global Values panel — consolidate all project config (Aspect Ratio, Visual Style, Visual Style Prompt, Duration from Deepgram, Subtitles, Music, Rhythm placeholder) into a single readable/editable "Global Values" section; replaces the current storyboard settings header | 3 | planned |

**Execution order:** S14-S2 → S14-S3 (both touch storyboard table; do sequentially). S14-S4 → S14-S5 (S14-S5 displays S14-S4 field). S14-S1 starts when screenshot received.

---

## Sprint 14 Definition of Done
- [ ] S14-S1: Defined and delivered once screenshot is reviewed.
- [ ] S14-S2: `ai_generate_prompt` cell is click-to-edit; changes persisted via `PATCH /runs/{run_id}/storyboard`; `primary_query` rendered as non-editable text.
- [x] S14-S3: "Source" column renders a `<select>` per row with Stock / AI Generated options. Selecting Stock applies a highlight class to the primary_query cell; AI Generated highlights the ai_generate_prompt cell. Selection stored in manifest `asset_mode` field. Acquisition orchestrator routes per `asset_mode`.
- [ ] S14-S4: Free-text "Visual Style Prompt" field in Project Settings. Saved to run config as `visual_style_prompt`. Injected by `ReplicateClient` as a prompt suffix on every AI generation call.
- [ ] S14-S5: Global Values panel shows all run config values. Duration auto-populated from `alignment.json` total word span. Rhythm shows "—" (not yet implemented). All editable fields (Visual Style Prompt, Visual Style enum, Aspect Ratio) are editable inline.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** Operator edits an AI prompt inline, switches that scene to "AI Generated", and sees the asset generated by Replicate using the custom prompt + Visual Style Prompt suffix.

---

# Sprint 15 — Storyboard UX + Source Expansion

**Goal:** Polish the storyboard table UX (sticky headers, column cleanup, query simplification). Expand stock sources with Pixabay. Add AI-driven source type classification so historic scenes route to Wikimedia automatically.
**Status:** planned
**Points:** 11

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S15-S1 | Sticky table headers — storyboard and assets tables maintain visible column headers on scroll | 2 | planned |
| S15-S2 | Rename `ID` → `Scene` column; hide Fallback Query column from storyboard UI (stays in backend data model) | 1 | planned |
| S15-S3 | Pixabay as second stock source — parallel search alongside Pexels; acquisition chain becomes Pexels → Pixabay → Replicate; new `PIXABAY_API_KEY` ENV var | 4 | planned |
| S15-S4 | AI-driven source type — storyboard prompt gains a `source_type: "realistic_stock" \| "historic_archival"` field per scene; for historic scenes Wikimedia Commons is the primary source (Pexels → Pixabay become fallbacks); realistic chain unchanged (Pexels → Pixabay → Replicate) | 4 | planned |

**Execution order:** S15-S1 and S15-S2 are independent frontend. S15-S3 before S15-S4 (S15-S4 extends the acquisition chain S15-S3 establishes).

---

## Sprint 15 Definition of Done
- [ ] S15-S1: `position: sticky; top: 0` on `<thead>` in both storyboard and assets tables. No horizontal scroll regression.
- [ ] S15-S2: Scene column header reads "Scene". Fallback Query column not rendered in the table UI; `fallback_query` field remains in `ManifestEntry` for backend use.
- [ ] S15-S3: `src/pixabay.py` client with `PIXABAY_API_KEY` ENV var. Acquisition orchestrator calls Pixabay when Pexels returns no result. Tests: Pixabay API mocked; chain falls through correctly.
- [ ] S15-S4: Storyboard prompt updated to include `source_type` per scene. `ManifestEntry.source_type` field added. Acquisition orchestrator branches: `historic_archival` → Wikimedia → Pexels → Pixabay (no Replicate fallback for historic); `realistic_stock` → Pexels → Pixabay → Replicate. `src/wikimedia.py` client. Tests cover both chains.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** Operator runs pipeline on a housing-history script; at least one scene routes to Wikimedia and displays an archival image in the final video.

---

# Sprint 16 — Assets Overhaul + Replacement

**Goal:** Give the operator full control over acquired assets — replace any asset with their own upload. Overhaul the assets table for readability: full descriptions, voice-over context, and clean labelling.
**Status:** planned
**Points:** 8

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S16-S1 | Per-asset upload replacement — "Replace" button per asset row; operator uploads their own image/video; presigned PUT to R2 replaces the existing key; `asset_manifest.json` updated | 4 | planned |
| S16-S2 | Full description visibility — remove ellipsis truncation from all asset table cells; enable text wrap; auto row height | 2 | planned |
| S16-S3 | Assets table cleanup — Voice Over column (second column, shows `voiceover_line` per scene); human-readable asset types (`still_with_motion` → "Still With Motion", `animated` → "Animated"); remove Status column | 2 | planned |

**Execution order:** All three independent. S16-S1 has backend; S16-S2 and S16-S3 are pure frontend.

---

## Sprint 16 Definition of Done
- [ ] S16-S1: Each asset row has a "Replace" button. Clicking opens a file picker. Selected file is PUT to R2 via presigned URL (same pattern as voiceover upload in E6-S3). `asset_manifest.json` entry updated with new `file_key`. UI refreshes to show replacement. Tests: presigned URL generation mocked; manifest update covered.
- [ ] S16-S2: No `text-overflow: ellipsis` in the assets table. All description/text cells wrap. Row height expands with content. Horizontal scroll preserved.
- [ ] S16-S3: Voice Over column renders as second column (after Scene). Asset Type cell shows Title Case label. Status column removed from the table entirely.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** Operator dislikes an AI-generated image, clicks Replace, uploads their own photo, sees it appear in the asset row, and renders a video using that photo.

---

# Sprint 17 — Project Report + Token Tracking

**Goal:** Give the operator cost visibility per project. Add a Project Report as the final pipeline step — aggregating token usage, render time, asset sources, and video stats into a single summary card.
**Status:** planned
**Points:** 7

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S17-S1 | Token cost tracking — every Claude API call logs `{model, input_tokens, output_tokens, cost_usd}` to `run_log.json`; `ModelRouter` extended to capture and persist cost per call | 2 | planned |
| S17-S2 | Project Report pipeline step — `POST /runs/{run_id}/report` aggregates: total token cost, asset breakdown by source (Pexels / Pixabay / Wikimedia / Replicate / uploaded), render duration, video duration, word count, scene count; stored as `runs/{run_id}/report.json` | 3 | planned |
| S17-S3 | Report UI — "Project Report" as final pipeline step; summary card shows cost, asset breakdown, duration stats; displayed after metadata step | 2 | planned |

**Execution order:** S17-S1 → S17-S2 (report needs cost data) → S17-S3.

---

## Sprint 17 Definition of Done
- [ ] S17-S1: `run_log.json` gains a `cost_log: [{step, model, input_tokens, output_tokens, cost_usd}]` array. `ModelRouter` updated to log each call. Tests cover cost accumulation.
- [ ] S17-S2: `POST /runs/{run_id}/report` reads `run_log.json` (cost_log), `asset_manifest.json` (source breakdown), `alignment.json` (word count), `storyboard.json` (scene count), `run_log.json` (render step duration). Stores `report.json`. `PIPELINE_STEPS` gains `"report"` after `"metadata"`.
- [ ] S17-S3: Report section appears in UI after metadata. Shows: Total AI cost (USD), assets by source, video duration, scene count, render time. Clean card layout — no raw JSON.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** Operator completes a full pipeline run and reads the Project Report — sees exactly how much the video cost to produce.

---

# Sprint 18 — API-First Pipeline

**Goal:** Enable N8N and other external tools to trigger the full pipeline via API, poll for status, and receive a download URL when the video is ready. Webhook support eliminates polling.
**Status:** planned
**Points:** 8

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S18-S1 | Pipeline trigger endpoint — `POST /api/pipeline` accepts `{script, project_name, settings, webhook_url?}`; creates run, queues full pipeline asynchronously; returns `{run_id, status_url}` immediately | 3 | planned |
| S18-S2 | Pipeline status + result endpoint — `GET /api/pipeline/{run_id}` returns `{status, steps, download_url?}`; `download_url` populated when `render: complete` | 2 | planned |
| S18-S3 | API key auth — `API_KEY` ENV var; Bearer token required on all `/api/*` routes; separate from operator session cookie | 2 | planned |
| S18-S4 | Webhook callback — when render completes, POST `{run_id, download_url, status}` to `webhook_url` if provided at trigger time | 1 | planned |

**Execution order:** S18-S3 → S18-S1 → S18-S2 → S18-S4.

---

## Sprint 18 Definition of Done
- [ ] S18-S1: `POST /api/pipeline` creates a run, kicks off the full pipeline as a background task (alignment → storyboard → manifest → assets → ffmpeg-script → render). Returns 202 with `{run_id, status_url}` immediately.
- [ ] S18-S2: `GET /api/pipeline/{run_id}` returns current step-level status. When render is complete, `download_url` is a presigned R2 URL (1h TTL). Returns 404 if run_id unknown.
- [ ] S18-S3: Bearer token middleware on all `/api/*` routes. Requests without a valid `Authorization: Bearer <API_KEY>` header receive 401. `API_KEY` in `config.py` and `ENV.md`.
- [ ] S18-S4: If `webhook_url` was provided at trigger time, an HTTP POST is sent to it when render step completes. Body: `{run_id, download_url, status: "complete"|"failed"}`. Non-blocking — webhook failure does not affect the pipeline.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** N8N HTTP request node triggers `POST /api/pipeline` with a housing script; N8N polls `GET /api/pipeline/{run_id}` until `download_url` appears; N8N uploads the video to YouTube/Instagram directly.

---

# Sprint 19 — Multi-tenant + Google OAuth

**Goal:** Replace the single-operator password gate with Google OAuth. Each user sees only their own projects. Enables the product to scale beyond one operator.
**Status:** planned
**Points:** 8

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S19-S1 | Google OAuth login — replace password gate (`S5-S5`) with Google sign-in; `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` ENV vars; session stores `user_id` (Google sub) and email | 4 | planned |
| S19-S2 | Per-user run isolation — R2 prefix changes to `runs/{user_id}/{run_id}/`; `GET /runs` scoped to authenticated user; existing single-user runs migrated or legacy-prefixed | 3 | planned |
| S19-S3 | User registry — lightweight user record (`user_id`, `email`, `created_at`) stored in R2 as `users/{user_id}/profile.json`; no admin UI required for POC | 1 | planned |

**Execution order:** S19-S1 → S19-S2 → S19-S3.

---

## Sprint 19 Definition of Done
- [ ] S19-S1: Google OAuth flow works end-to-end. Unauthenticated requests redirect to Google login. After auth, session cookie set. `/logout` clears session. Tests: auth middleware mocked; login success/failure covered.
- [ ] S19-S2: All R2 reads/writes use `runs/{user_id}/{run_id}/` prefix. `GET /runs` filters by authenticated user. Existing runs at the old prefix are either migrated on first access or treated as a legacy "default" user.
- [ ] S19-S3: User profile written to R2 on first login. `email` and `created_at` recorded.
- [ ] All existing tests pass (auth mocked throughout).
- [ ] **Human touchpoint:** Two different Google accounts log in; each sees only their own project list with no cross-contamination.

---
---

# CONTENT FACTORY v2 — PLATFORM TRACK (Sprints P0–P7)

**Canonical spec:** docs/v2_platform_plan.md · **Decisions:** D047–D057 · **Stories:** BACKLOG.md "Platform Track" section.
Legacy Script→Video stays untouched and operable (D047). Specs are reviewed at the start of each sprint and story.

| Sprint | Theme | Pts | Depends on | Human touchpoint |
|--------|-------|-----|-----------|------------------|
| P0 | Boundary design & contracts (interfaces only) | 13 | — | Approve spec + schemas |
| P1 | Platform skeleton & core (LangGraph-aware) | 16 | P0 | `POST /platform/echo` → artifact in R2 |
| P2 | Lineage & observability store (Postgres) | 16 | P1 | Per-worker cost/latency/version; resume after restart |
| P3 | Telegram trigger + Discovery worker | 10 | P1, P2 | `/ideas <niche>` → signals in Telegram |
| P4 | Niche→Ideas block | 13 | P3 | Telegram niche → ranked ideas w/ scores |
| P5 | Idea→Script block | 16 | P4 (soft) | Telegram idea → fact-checked script |
| P6 | Orchestrator + legacy bridge | 13 | P4, P5 | `/produce <niche>` → finished video |
| P7 | Analytics & attribution | 11 | P2, P6 | Retention-by-prompt-version report |

**MVP (P0–P6) = 97 pts; with P7 = 108 pts.** Critical path: P0→P1→P2→P3→P4→P6→P7 (P5 soft-parallel after P2).
Post-MVP: **Epic 32** Legacy Rebuild (~3 sprints), **Epic 34** Replay & Evaluation (~3 sprints, ~30 pts).

---

# Sprint P0 — Boundary Design & Contracts

**Goal:** Lock the north-star spec, decisions D047–D057, and all universal contracts so P1 builds against a stable surface. **Interfaces only — no runtime behavior.**
**Status:** done
**Points:** 13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P0-S1 | North-star spec — docs/v2_platform_plan.md | 2 | done |
| P0-S2 | Ratify decisions D047–D057 | 2 | done |
| P0-S3 | Core contracts (Pydantic) — interfaces only | 5 | done |
| P0-S4 | Postgres data model + analytics-join design | 2 | done |
| P0-S5 | Doc hygiene + abstraction-model docs | 2 | done |

**Execution order:** P0-S1 → P0-S2 → (P0-S3 ∥ P0-S4) → P0-S5.

## Sprint P0 Definition of Done
- [x] Plan doc approved; D047–D057 written; D042 marked superseded
- [x] Universal contracts defined + schema-tested (no runtime)
- [x] Postgres DDL + attribution query designed; migration tooling chosen
- [x] ARCHITECTURE/CONVENTIONS carry the LangGraph abstraction model
- [x] **Human touchpoint:** operator reads and approves the spec + schemas

---

# Sprint P1 — Platform Skeleton & Core

**Goal:** A working spine — create a run, execute a single-node LangGraph graph through the observability wrapper, write a versioned R2 artifact, record a `WorkerExecution` (in-memory until P2).
**Status:** done
**Points:** 16
**Velocity:** 16/16 pts (100%)

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P1-S1 | cf_platform/ scaffold + router mount | 2 | done |
| P1-S2 | Run Manager | 3 | done |
| P1-S3 | Artifact Manager → R2 (immutable, versioned) | 3 | done |
| P1-S4 | LangGraph execution engine (Layer A) ⚠️ keystone | 3 | done |
| P1-S5 | Observability wrapper (Layer B) | 3 | done |
| P1-S6 | Echo graph end-to-end smoke | 2 | done |

**Execution order:** P1-S1 → (P1-S2 ∥ P1-S3) → P1-S4 → P1-S5 → P1-S6. Spike P1-S4 first.

## Sprint P1 Definition of Done
- [x] `langgraph` adopted (D052); worker=node contract implemented
- [x] Wrapper emits exactly one artifact + one execution record per node
- [x] Legacy routes unaffected; platform init fault-isolated
- [x] **Human touchpoint:** operator calls `/platform/echo` and sees the artifact in R2

---

# Sprint P2 — Lineage & Observability Store

**Goal:** Durable, queryable lineage in Postgres; LangGraph durability via the Postgres checkpointer; observability endpoints.
**Status:** planned
**Points:** 16

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P2-S1 | Provision Railway Postgres + connection layer | 3 | done |
| P2-S2 | Schema migrations (runs/artifacts/worker_executions/trace_events) | 3 | planned |
| P2-S3 | Persist Run/Artifact/Execution to Postgres | 5 | planned |
| P2-S4 | LangGraph PostgresSaver checkpointer | 3 | planned |
| P2-S5 | Observability endpoints | 2 | planned |

**Execution order:** P2-S1 → P2-S2 → (P2-S3 ∥ P2-S4) → P2-S5.

## Sprint P2 Definition of Done
- [ ] R2 = blob truth; Postgres = index (lineage as columns)
- [ ] A run resumes from checkpoint after a process restart
- [ ] **Human touchpoint:** operator inspects per-worker cost/latency/version for a run

---

# Sprint P3 — Telegram Trigger + Discovery Worker

**Goal:** First real input + first real worker; signals stored with full lineage; trace events per source.
**Status:** planned
**Points:** 10

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P3-S1 | Telegram webhook (trigger-only) | 3 | planned |
| P3-S2 | Discovery worker v1 + source adapters | 5 | planned |
| P3-S3 | Reply formatter + wire discovery | 2 | planned |

**Execution order:** (P3-S1 ∥ P3-S2) → P3-S3. Requires P2 (persisted lineage).

## Sprint P3 Definition of Done
- [ ] 3 `SourceAdapter`s; partial-failure isolation; adapters emit trace events
- [ ] Discovery emits one `signals` artifact with lineage
- [ ] **Human touchpoint:** `/ideas <niche>` → signals summary in Telegram

---

# Sprint P4 — Niche→Ideas Block

**Goal:** Full first E2E block as a LangGraph StateGraph (discovery → topic-gen → scoring → selection); per-node lineage; Telegram + REST.
**Status:** planned
**Points:** 13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P4-S1 | Topic Generator worker | 3 | planned |
| P4-S2 | Opportunity Scoring worker | 3 | planned |
| P4-S3 | Topic Selector worker | 2 | planned |
| P4-S4 | Assemble niche_to_ideas StateGraph (+ NicheToIdeasState) | 3 | planned |
| P4-S5 | Block interfaces (REST + Telegram) | 2 | planned |

**Execution order:** P4-S1 → P4-S2 → P4-S3 → P4-S4 → P4-S5.

## Sprint P4 Definition of Done
- [ ] `NicheToIdeasState` per plan §5; one run = 4 artifacts + 4 execution rows
- [ ] **Human touchpoint:** Telegram niche → ranked ideas with 7-axis scores + alternatives

---

# Sprint P5 — Idea→Script Block

**Goal:** Second block; cyclic write→score→fact-check→refine with bounded convergence; external search isolated.
**Status:** planned
**Points:** 16

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P5-S1 | Script Writer worker (write ×N) | 3 | planned |
| P5-S2 | Quality/virality scorer worker | 3 | planned |
| P5-S3 | Fact-check tool integration (web search) | 3 | planned |
| P5-S4 | Refine loop + convergence logic ⚠️ spike | 5 | planned |
| P5-S5 | Assemble idea_to_script graph + interfaces (+ IdeaToScriptState) | 2 | planned |

**Execution order:** P5-S1 → (P5-S2 ∥ P5-S3) → P5-S4 → P5-S5. Soft-parallel with P4 after P2.

## Sprint P5 Definition of Done
- [ ] Loop converges or stops at `max_iterations`; iteration is a typed state channel (D057)
- [ ] **Human touchpoint:** Telegram idea → fact-checked `script` artifact

---

# Sprint P6 — Orchestrator + Legacy Bridge

**Goal:** Parent graph chains niche→ideas → idea→script → legacy render via the adapter; optional HITL gates; one command → video.
**Status:** planned
**Points:** 13

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P6-S1 | Legacy adapter (interface + in-process impl) | 3 | planned |
| P6-S2 | Legacy-as-node + parent graph (+ PipelineState) | 5 | planned |
| P6-S3 | Human-in-the-loop gates | 3 | planned |
| P6-S4 | End-to-end /produce → video | 2 | planned |

**Execution order:** P6-S1 → P6-S2 → (P6-S3 ∥ P6-S4). P6-S3 needs P2-S4.

## Sprint P6 Definition of Done
- [ ] Only the adapter imports `src/`; legacy unchanged and still operable
- [ ] One run threads lineage across blocks + legacy node
- [ ] **Human touchpoint:** operator runs `/produce <niche>` and downloads the finished video

---

# Sprint P7 — Analytics & Attribution

**Goal:** Close the loop — which prompt/worker version produced higher-retention videos.
**Status:** planned
**Points:** 11

| ID | Title | Points | Status |
|----|-------|--------|--------|
| P7-S1 | Publish linkage capture | 3 | planned |
| P7-S2 | YouTube analytics ingestion worker | 5 | planned |
| P7-S3 | Attribution query + report | 3 | planned |

**Execution order:** P7-S1 → P7-S2 → P7-S3. (P7-S2 can be prototyped early — needs only video IDs.)

## Sprint P7 Definition of Done
- [ ] `published_videos` + `video_metrics` populated; lineage join works
- [ ] **Human touchpoint:** operator reads a report ranking prompt versions by retention
