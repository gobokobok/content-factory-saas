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
**P-CORE built 2026-10-14 (branch `sprint/p-core`, commits ahead of `main`; NOT merged, NOT pushed — a push to `main` deploys DEV).** The Studio's features are Super-only screens and controls of `/create` (D121): Projects, project pages, Libraries, Integrations, Defaults; script generation, voice upload and transcript editing, stock footage, metadata, CapCut, Auto-advance. `/`, `/studio`, `/project`, `/library`, `/settings` redirect; the old pages and their tests are deleted. Tests 3218 passing. Looked at in a local preview with in-memory storage only.
Closed before it: **P-AUTH** (2026-10-14; on DEV; smoke PARTIAL → AUTH-S10).
_Roadmap (D114, D117, D118): **P-BILL-1 (starts with AUTH-S10; friends beta opens)** → P-BILL-2 → **P-LANG Russian (EPIC 53)** → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance. Unplaced: EPIC 50, E54-S1 chunked voiceover, library "use in a scene", long-form animation._

## Active story
**P-CORE DEV smoke (operator + Claude).** After the operator's go-ahead: push `sprint/p-core` to `main`, wait for the DEV deploy, run the steps in DONE.md [P-CORE], then `/finish-story`. AUTH-S10 (friend-account smoke) is still open.

**Blockers / operator actions:** AUTH-S0: set the `PROD_URL` GitHub variable and record the first restore drill in `docs/RUNBOOK.md` (F1) before real users. Keep `SIGNUP_OPEN` unset until AUTH-S10 passes. Choose the female Creator voice and set `CREATOR_VOICE_FEMALE`. For published videos set `IMAGE_RESOLUTION=2K` and the `nano-banana-2-1` price to 0.03 in `IMAGE_MODEL_COSTS_USD`. Rotate the Pixabay key on DEV; check the DEV log for `key=REDACTED`. PROD stays on v0.24.0 on purpose — release only when DEV is complete and smoke tested (at release: new `SETTINGS_ENCRYPTION_KEY`, 12+ character `OPERATOR_PASSWORD`, the Google / `OWNER_EMAILS` / `CAP_*` variables, migration 0005). Google API audit application in progress (P16 lead time). Empty Railway variables now count as unset.
Telegram is dormant (D093) and unmounted unless `TELEGRAM_ROUTES_ENABLED`; the legacy pipeline UI is off unless `LEGACY_ROUTES_ENABLED` (D116).

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
