# Sprint 1 — Railway Foundation & Drive Integration

**Goal:** Deployable FastAPI service on Railway with Google Drive integration and storyboard generation via Claude API.
**Status:** In progress

---

## Stories

| ID | Title | Status |
|----|-------|--------|
| E1-S1 | Railway service skeleton (FastAPI, health check, ENV validation) | active |
| E1-S2 | Google Drive integration (service account auth, run folder creation, run_log.json init) | backlog |
| E1-S3 | Storyboard generation (Claude API call with v0.4 prompt, parse, upload to Drive, update run_log.json) | backlog |

---

## Sprint 1 Definition of Done
- [ ] FastAPI service deploys to Railway DEV and health check passes
- [ ] Run folders created in Google Drive with correct structure
- [ ] `run_log.json` initialized with all steps `pending`
- [ ] Storyboard generated from plain-text VO script and uploaded to Drive
- [ ] All stories have passing tests and green CI

---

## Notes
- Framework decision: FastAPI (over Flask) — async support for concurrent API calls, Pydantic validation, auto-generated docs. Logged in DECISIONS.md.
- Start with E1-S1. Do not begin E1-S2 until E1-S1 smoke test passes on Railway DEV.

---

# Sprint 2 — Asset Manifest & Acquisition

**Goal:** Parse storyboard into asset manifest; acquire assets from Pexels with Replicate fallback.
**Status:** planned

## Stories

| ID | Title | Status |
|----|-------|--------|
| E2-S1 | Asset manifest generation | backlog |
| E3-S1 | Pexels stock footage integration | backlog |
| E3-S2 | Replicate/Flux AI image generation fallback | backlog |
| E3-S3 | Asset acquisition orchestrator | backlog |
