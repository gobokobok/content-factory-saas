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
**Status:** in progress
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
