# Content Factory — Session Bootstrap

## Startup protocol
On every new session, read in this order:
1. **This file** (CLAUDE.md)
2. **SPRINT.md** — current sprint and active story
3. **The active story** in BACKLOG.md
4. **DONE.md** — last 3 entries for recent context
5. **CONVENTIONS.md** — coding standards before touching any code

## Project summary
Content Factory is a modular, automated content production pipeline for "The Housing Equation" — a faceless, data-driven YouTube Shorts channel about American housing economics. The operator triggers and monitors each pipeline step via a minimal HTML/JS web UI hosted on Railway. POC scope covers pipeline Steps 2b–7; Step 2a (`script-generator.html`) is a standalone reference tool in `/tools`, not integrated.

## Current sprint
**Platform v2 — Sprint P1** — Platform Skeleton & Core. Canonical spec: docs/v2_platform_plan.md; sprints in SPRINT.md (Platform Track); decisions D047–D057.
_Legacy Sprints 1–13 are done and running in DEV/PROD; the legacy pipeline stays untouched (D047). S14–S17 (video-UX polish) are paused._

## Active story
**P1-S3** — Artifact Manager → R2 (immutable, versioned). P1-S1 and P1-S2 done; P1-S3 depends only on P1-S1 and can proceed now.

## Environments

| Env   | Deploy trigger    | Railway service         | Drive root folder       |
|-------|-------------------|-------------------------|-------------------------|
| Local | `.env.local`      | —                       | `GOOGLE_DRIVE_ROOT_ID`  |
| DEV   | Push to `main`    | `content-factory-dev`   | Content Factory DEV     |
| PROD  | Git tag `v*.*.*`  | `content-factory-prod`  | Content Factory         |

## Key documents

| File | Purpose |
|------|---------|
| BACKLOG.md | All epics and stories |
| SPRINT.md | Current sprint, story statuses |
| DONE.md | Completed stories log |
| DECISIONS.md | All architecture and dependency decisions |
| CONVENTIONS.md | Python coding standards |
| ENV.md | All environment variables (no values) |
| docs/ARCHITECTURE.md | System design, data flow, component map |
| docs/v2_platform_plan.md | **v2 platform migration — canonical spec, contracts, decisions D047–D057** |
| docs/TECH_STACK.md | Stack choices, versions, rationale |
| docs/PROMPTS.md | Storyboard prompt v0.4 and changelog |
| docs/TESTING.md | Test strategy per layer |
| docs/UI_GUIDELINES.md | Operator UI design rules |

## Run folder structure (Drive)
```
/Content Factory/runs/{YYYY-MM-DD}_{slug}/
  storyboard.json
  asset_manifest.json
  run_log.json        ← step-level checkpoint state
  run_log.txt         ← human-readable log
  ffmpeg_script.sh
  /video
  /images
  /sfx
  /music              ← copied from /music-library
  /voiceover          ← operator uploads .mp3 here
  /output
```

## Drive root structure
```
/Content Factory          ← PROD root (GOOGLE_DRIVE_ROOT_ID)
  /music-library          ← shared, operator-managed
  /runs
    /{YYYY-MM-DD}_{slug}/
```

## Hard constraints
- **No new dependencies** without a DECISIONS.md entry first
- **Every function** must have a docstring
- **Every story** ships with tests (see docs/TESTING.md)
- **No hardcoded values** — all config via ENV vars
- **No UI frameworks** — plain HTML/JS only for operator UI
- **Free-tier APIs only** for POC (Pexels, Replicate, Freesound)
- CI must be green before marking a story complete
- **Pipeline step functions must be pure async** — take explicit inputs, return explicit outputs, no coupling to HTTP request context. Routes are thin wrappers only. See CONVENTIONS.md § Async function discipline and DECISIONS.md D040.

## Human Touchpoint Rule
Every sprint must include or culminate in a human-testable artifact. If the sprint is purely infrastructure, scope a minimal UI shim or smoke-test endpoint that a non-technical stakeholder can interact with. Never go more than one sprint without something a human can touch.

**Before finalizing any sprint plan, answer:** "What can a human touch at the end of this sprint?" If the answer is nothing, add a story.

Logged in DECISIONS.md as D019.

## Pipeline steps reference

| Step | Epic | Description |
|------|------|-------------|
| 2a   | —    | Brief → Script (`/tools/script-generator.html`, standalone) |
| 2b   | E1   | Script → `storyboard.json` (Claude API, prompt v0.4) |
| 3    | E2   | Storyboard → `asset_manifest.json` |
| 4    | E3   | Asset acquisition (Pexels → Replicate fallback) |
| 5    | E4   | Asset manifest → `ffmpeg_script.sh` |
| 6    | E5   | FFmpeg execution → upload output to Drive |
| 7    | E6   | Operator UI (trigger, monitor, retry, upload voiceover) |
