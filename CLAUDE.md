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
**Sprints P-PROJ1 (EPIC 57, D111) and P-INT1 (EPIC 58, D112)** closed 2026-10-13 (built 2026-10-11 back to back, with the operator away), on top of P-UX4 (D109); a run can also follow one character (D113). Look and image source are two settings locked after the storyboard; a project has a channel identity and saved characters/places the animation storyboard reuses; the Realistic prompt v0.18 exists behind `STORYBOARD_STOCK_PROMPT_VERSION` (default still v0.17); Settings → Integrations is five blocks with a default and a model per provider, and YouTube metadata can run on OpenAI. Earlier: P-AN1 animation mode (D108).
Studio is the only operator interface; Telegram is dormant (D093); legacy pipeline UI lives at `/legacy`.
_Roadmap (D109, 2026-10-11): **P-UX4 (done)** → **P-PROJ1 (done)** → **P-INT1 (done)** → `/audit` → P-AUTH → P-BILL-1 (**friends beta**) → P-BILL-2 → **P-LANG Multi-language: Russian (EPIC 53)** → P15 Research → P16 Publishing via n8n → P17 Server-side Auto Advance. Unplaced: EPIC 50, E54-S1 chunked voiceover, library "use in a scene" and music-from-library (D105), long-form animation (chunked storyboard, D108)._

## Active story
**None started.** P-UX4, P-PROJ1 and P-INT1 are closed. Next: the operator runs the DEV smoke sweep (INT1-S5, list in BACKLOG_ACTIVE.md EPIC 58) and `/sprint-review` for P-UX4, P-PROJ1 and P-INT1. Then, per D109: `/audit` → P-AUTH → P-BILL-1 (friends beta).

**Blockers / operator actions:** for published videos set `IMAGE_RESOLUTION=2K` and the `nano-banana-2-1` price to 0.03 in `IMAGE_MODEL_COSTS_USD` on Railway (1K is below the 1080p frame). Rotate the Pixabay key on DEV (the old one is in DEV log history); check the DEV log for `key=REDACTED`. Re-render a run with zooms to confirm the zoom fix (D107). PROD stays on v0.24.0 on purpose — release DEV to PROD only when DEV is complete and smoke tested (at release set a new `SETTINGS_ENCRYPTION_KEY` and re-check PROD logs for `key=`). `/audit` never run (planned before P15). Google API audit application in progress (lead time for P16). Deferred/partial smoke entries: 4 (P-UX4, P-PROJ1 partial, P-INT1, D113 cast → all INT1-S5; the sweep is mandatory). Set `OPENAI_LLM_MODEL` on Railway if `gpt-4.1-mini` is not valid on the OpenAI account; `STORYBOARD_STOCK_PROMPT_VERSION` stays `v0.17` until the v0.17 vs v0.18 test is done.

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
