# Content Factory — Session Bootstrap

## Startup protocol
On every new session, read in this order:
1. **This file** (CLAUDE.md)
2. **SPRINT.md** — current sprint status and story table (active sprints only; history in SPRINT_ARCHIVE.md)
3. **The active story** in **BACKLOG_ACTIVE.md** (current + next two sprints; full archive in BACKLOG.md)
4. **DONE.md** — recent entries for context (older ones are in DONE_ARCHIVE.md)
5. **CONVENTIONS.md** — coding standards before touching any code

## Project summary
Content Factory is a modular, automated content production pipeline for "The Housing Equation" — a faceless, data-driven YouTube Shorts channel about American housing economics. The operator triggers and monitors each pipeline step via a minimal HTML/JS web UI hosted on Railway. POC scope covers pipeline Steps 2b–7; Step 2a (`script-generator.html`) is a standalone reference tool in `/tools`, not integrated.

## Current sprint
**Sprint P14 — AI Created style** (D096, D104): the operator generates an AI image per scene from the storyboard's edit-image dialog (prompt field + Generate) — manual only, never automatic. Provider, model and API key are tenant settings (`/settings`, encrypted); an optional project-level `ai_image_style` is prepended to every prompt; a per-run spend cap guards cost. P12, P13 and P13b are complete. Studio is the only operator interface: `/` project list → `/project?id=` shortlist + runs → `/studio#run/<id>` pipeline. Telegram is dormant (D093); legacy pipeline UI lives at `/legacy`.
_Backlog order: P14 → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance. Unplaced: EPIC 50 (E50-S1..S3 word-anchored overlays, SFX library)._

## Active story
**P14-S1..S4** — built in one pass, code complete on `main`'s working tree (CI-equivalent suite green), **not yet pushed**. Next: commit and push, wait for the DEV deploy, then the smoke test (SPRINT.md, Sprint P14); then `/finish-story`.

**Blockers / operator actions:** none. PROD stays on v0.24.0 on purpose — the operator releases DEV to PROD only when DEV is complete and smoke tested (no `/release` pending). Before the P14 smoke test: set `SETTINGS_ENCRYPTION_KEY` on Railway DEV, then save a kie.ai key in Settings. `/audit` never run (no `docs/SECURITY.md`). Google API audit application in progress (lead time for P16). Deferred smoke tests: 0.

## Environments

| Env   | Deploy trigger    | Railway service         | Drive root folder       |
|-------|-------------------|-------------------------|-------------------------|
| Local | `.env.local`      | —                       | `GOOGLE_DRIVE_ROOT_ID`  |
| DEV   | Push to `main`    | `content-factory-dev`   | Content Factory DEV     |
| PROD  | Git tag `v*.*.*`  | `content-factory-prod`  | Content Factory         |

## Key documents

| File | Purpose |
|------|---------|
| BACKLOG_ACTIVE.md | **Active stories — last completed sprint, upcoming sprint outlines, open unassigned stories (read this)** |
| BACKLOG.md | Full story archive (all epics; read for sprint planning only) |
| SPRINT.md | Roadmap table (P0–P17), open carried items, and the current sprint only |
| SPRINT_ARCHIVE.md | Every closed sprint: legacy S1–S19 + platform P0–P12 |
| DONE.md | Completed stories log — last two sprints plus any entry with an open smoke-test deferral; older in DONE_ARCHIVE.md |
| DECISIONS.md | All architecture and dependency decisions |
| CONVENTIONS.md | Python coding standards |
| ENV.md | All environment variables (no values) |
| docs/ARCHITECTURE.md | System design, data flow, component map |
| docs/v2_platform_plan.md | **v2 platform migration — canonical spec, contracts, decisions D047–D057** |
| docs/TECH_STACK.md | Stack choices, versions, rationale |
| docs/PROMPTS.md | Storyboard prompt v0.4 and changelog |
| docs/TESTING.md | Test strategy per layer |
| docs/RUNBOOK.md | Production checks — how to read PROD logs, findings per check |
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
- **Free-tier APIs only** for POC (Pexels, Pixabay, Freesound) — exception: paid AI image generation (D096)
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
