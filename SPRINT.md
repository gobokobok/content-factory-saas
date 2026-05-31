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
**Status:** planned
**Points:** 10

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S11-S1 | Background music upload — presigned PUT to `runs/{run_id}/music/`, stored in R2, playback preview in UI | 3 | done |
| S11-S2 | Audio controls UI — volume slider (0–100%), voiceover ducking toggle, loop vs fit-to-duration mode; stored in run config | 2 | backlog |
| S11-S3 | Audio → ffmpeg integration — BG music key + volume + ducking settings passed into generated ffmpeg script; replaces hardcoded `music 0.15` | 5 | backlog |

**Execution order:** S11-S1 → S11-S2 (controls require upload widget to exist); S11-S3 depends on both.

---

## Sprint 11 Definition of Done
- [ ] S11-S1: Audio section in Project Details. Background music file picker → presigned PUT → R2 at `runs/{run_id}/music/bg.mp3`. Playback `<audio>` preview shown after upload.
- [ ] S11-S2: Volume slider (0–100%, default 15%), voiceover ducking toggle (default ON), loop/fit-to-duration selector render and persist in run config.
- [ ] S11-S3: ffmpeg script generator reads audio settings from run config. When BG music present: uses configured volume (not hardcoded 0.15). Ducking ON: applies ffmpeg `volume` envelope or `sidechaincompress` to lower music under voiceover. Loop/fit mode controls whether BG music is trimmed or looped to match video duration. Tests cover each variant.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator uploads a background track, sets volume to 40%, enables ducking, renders video, hears the track duck under the voiceover in the final output.

---

# Sprint 12 — Video Settings Pipeline Wiring + Publishing Metadata

**Goal:** Wire the stored video settings into the actual render pipeline (aspect ratio changes ffmpeg output, visual style feeds Replicate prompts, subtitles toggle skips caption burn). Add post-render publishing metadata generation.
**Status:** planned
**Points:** 9

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| S12-S1 | Video settings → pipeline — aspect ratio into ffmpeg output dimensions, visual style into Replicate `ai_generate_prompt`, subtitles toggle enables/disables caption burn steps | 4 | backlog |
| S12-S2 | Publishing metadata generator — Claude API call post-render; generates title (primary + 2 variants), YouTube description, Instagram description, hashtags + SEO tags; stored at `runs/{run_id}/metadata.json` | 3 | backlog |
| S12-S3 | Publishing metadata UI — display below video player after render; copy-to-clipboard per field | 2 | backlog |

**Execution order:** S12-S1 independent; S12-S2 → S12-S3.

---

## Sprint 12 Definition of Done
- [ ] S12-S1: 9:16 project renders 1080×1920; 16:9 renders 1920×1080; 1:1 renders 1080×1080. Visual style value appended to Replicate `ai_generate_prompt` modifier (e.g. "cinematic, shallow depth of field"). Subtitles OFF skips both caption burn steps in ffmpeg script. Tests cover all aspect ratios and subtitle toggle.
- [ ] S12-S2: `POST /runs/{run_id}/metadata` endpoint calls Claude API (Haiku) with run storyboard + project name as context. Returns and stores `{title, alt_titles: [str, str], youtube_description, instagram_description, hashtags: [str], seo_tags: [str]}` at `runs/{run_id}/metadata.json`. Updates `run_log.json` step `metadata → complete`.
- [ ] S12-S3: After render section loads and render is complete, metadata section appears below video player. Each field (title, descriptions, hashtags) has a "Copy" button. No auto-posting to any platform.
- [ ] All existing tests pass.
- [ ] **Human touchpoint:** operator renders a video, sees metadata section appear automatically, clicks "Copy" on the YouTube description, pastes it directly into YouTube Studio.
