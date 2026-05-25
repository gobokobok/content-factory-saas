# Sprint 1 — Railway Foundation & Drive Integration

**Goal:** Deployable FastAPI service on Railway with Google Drive integration and storyboard generation via Claude API.
**Status:** In progress

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

## Sprint 1 Definition of Done
- [ ] FastAPI service deploys to Railway DEV and health check passes
- [ ] Run folders created in Google Drive with correct structure
- [ ] `run_log.json` initialized with all steps `pending`
- [ ] Storyboard generated from plain-text VO script and uploaded to Drive
- [ ] All stories have passing tests and green CI
- [ ] **Human touchpoint:** non-technical user can create a run via browser form (E6-S0)

---

## Notes
- Framework decision: FastAPI (over Flask) — async support for concurrent API calls, Pydantic validation, auto-generated docs. Logged in DECISIONS.md.
- Start with E1-S1. Do not begin E1-S2 until E1-S1 smoke test passes on Railway DEV.

---

# Sprint 2 — Operator UI + Polish

**Goal:** Operator can run the full pipeline start to finish from the browser UI without touching the terminal or R2 console.
**Status:** planned
**Points:** 21

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

**Sprint 2 total:** 22 pts remaining (10 pts done, 22 pts in ready)

**Dependency order:** E1-S4 → E6-S2 → E6-S3 (done). E5-S2, E5-S3, E4-S2, E4-S3 are independent of each other. E4-S5 depends on E4-S2 (done).

**Note:** Technical research (Gemini deep research) incorporated — E5-S2 expanded to include concat→filter_complex migration; E4-S3 added for zoompan; E4-S4 added to backlog as deferred. E5-S2 repointed 3→5; E5-S3 repointed 3→4 and promoted from backlog to ready. E4-S5 added for voiceover-line captions (second ASS track, scene-boundary timing).

---

## Sprint 2 Definition of Done
- [ ] Operator can list all past runs in the browser
- [ ] Operator can trigger every pipeline step from the browser (no curl)
- [ ] Operator can upload voiceover from the browser (no R2 console)
- [ ] Operator can view all step artifacts inline (storyboard, manifest, script, video)
- [ ] Scene durations match actual voiceover length (pacing calibration)
- [ ] Video cuts use filter_complex with PTS reset (no concat demuxer)
- [ ] Static images show Ken Burns motion effect
- [ ] Captions burned in via ASS subtitles
- [ ] Pexels queries use concrete nouns only (no adjectives)
- [ ] All stories have passing tests and green CI
- [ ] **Human touchpoint:** full end-to-end pipeline run completed from browser UI only
