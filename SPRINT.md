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
**Status:** planned
**Points:** 18

---

## Stories

| ID | Title | Points | Status |
|----|-------|--------|--------|
| E6-S4 | End-to-end production smoke test | 2 | done |
| E4-S6 | Subtitle style revision (Poppins Bold, TikTok-style) | 2 | done |
| E5-S4 | Word-level timestamp extraction via Deepgram | 5 | done |
| E8-S1 | Haiku schema validator — storyboard.json | 3 | done |
| E8-S3 | Haiku run log summarizer | 3 | done |
| E5-S5 | Pipeline reorder: VO-first with Deepgram-driven storyboard | 8 | backlog |

**Dependency order:**
1. E6-S4 ✅ DONE — validated DEV is healthy.
2. E4-S6 — subtitle style revision (Poppins Bold); ready now.
3. E5-S4 — Deepgram alignment service (standalone, no pipeline integration yet); ready now, parallel with E4-S6.
4. E8-S1 + E8-S3 — independent, can run any time.
5. E5-S5 — pipeline reorder; depends on E5-S4 complete; likely Sprint 4.
6. E4-S7 — word-synced captions; depends on E5-S5 complete; Sprint 4+.

---

## Sprint 3 Definition of Done
- [ ] Full pipeline run completed from browser UI — `final.mp4` watchable in browser
- [ ] Video cuts are ms-precise (Deepgram alignment replaces proportional redistribution)
- [ ] Storyboard JSON validated by Haiku before downstream steps run
- [ ] Operator UI shows human-readable step summaries (Haiku run log summarizer)
- [ ] All stories have passing tests and green CI
- [ ] **Human touchpoint:** operator watches a complete rendered Short in the browser player

---

## Notes
- E6-S4 is a validation story, not a feature — it has no code deliverable unless bugs are found.
- E5-S4 (WhisperX) requires `whisperx` + `torch` CPU — significant Docker build time increase (~2min). Log in DECISIONS.md before adding to requirements.txt.
- R2 CORS must be configured for voiceover direct-upload before E6-S4 smoke test can complete (see E6-S2 deployment note).
- CLIP_RERANK_ENABLED can be toggled to True in Railway DEV during E6-S4 to validate E4-S4 smoke test at the same time.
