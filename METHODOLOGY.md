# Methodology

## Version
APEX-DEV v0.1

## Commands installed
- `/init-project` — initialize project artifacts from spec
- `/start-story` — begin a story, read all context files
- `/finish-story` — complete a story, update DONE.md and BACKLOG.md
- `/sprint-review` — end-of-sprint retrospective and Sprint N+1 planning
- `/add-story` — add a new story to the backlog mid-sprint

## Improvement log
_METHODOLOGY IMPROVEMENT notes from sprint reviews are recorded here._

| Sprint | Date | Improvement |
|--------|------|-------------|
| 0 (init) | 2026-05-21 | Project initialized via /init-project |
| 0 (init) | 2026-05-21 | Before issuing git commands, check the last reported commit in the session to avoid duplicate commit suggestions. |
| 1 | 2026-05-22 | Infrastructure-first rule: all cloud services, CI/CD pipelines, and environment integrations (Railway, GitHub Actions, external API accounts) must be fully provisioned and verified before Sprint 1 Story 1 begins. Add an "Infra & DevOps Setup" pre-sprint checklist to /init-project output. |
| 2 | 2026-05-25 | Deferred smoke test tracking: every DONE.md entry must have an explicit `Smoke test: PASSED` or `Smoke test: DEFERRED — [condition]` line. When deferred smoke tests reach 5+, sprint-review flags an integration story. Applied to /finish-story v0.2 step 3 (DONE.md format) and step 7 (tracking rule). |
| 3 | 2026-05-27 | **Proposal A — Sprint note hygiene:** If implementation used a different technology than what the SPRINT.md notes row stated (provider swap, library change, etc.), update SPRINT.md notes in the same finish-story commit. Applied to /finish-story v0.3 step 5. Root cause: E5-S4 switched WhisperX → Deepgram but the SPRINT.md notes still referenced WhisperX. |
| 3 | 2026-05-27 | **Proposal B — Backend/UI pairing rule:** When a story adds a new pipeline step endpoint, its UI surface must be explicitly resolved before the story is marked done: either (a) the UI was updated in the same story, or (b) a follow-up story ID is cited in AC/Notes and that story exists in BACKLOG.md. Applied to /finish-story v0.3 step 1. Root cause: E5-S4 shipped the alignment endpoint with no UI row, requiring a post-sprint hotfix and leaving the step order incorrect until E5-S5. |
| 5 | 2026-05-29 | **Shared VALID_ENV in conftest.py:** When a new required `Settings` field is added, all 9 test files currently need individual VALID_ENV updates — tedious and error-prone. Centralise `VALID_ENV` in `tests/conftest.py` as a module-level dict and import it in each test file. When a required field changes, update only conftest.py. Add to `/finish-story` step 1: "If you added a required `Settings` field, check whether VALID_ENV is centralised in conftest.py. If not, flag centralisation as a follow-up task." |
| 6 | 2026-05-30 | **M-1 — Preview viewport reset before visual verification:** The static preview defaults to a very narrow viewport (~141px) left over from prior sessions. Before taking any screenshot in `/finish-story`, always call `preview_resize width=1280 height=800` explicitly — do not rely on the `desktop` preset alone. Also reload the page after resize if the URL hash shows stale run state. Applied to `/finish-story` v0.4 step 1 (frontend verification note). |
| 11 | 2026-05-31 | **Proposal A — Lower deferred smoke test threshold 5 → 3:** Smoke tests at threshold 5 are already too late — S11 hit 5 and one session found 3 real bugs. Threshold lowered to 3. Applied to `/finish-story` v0.5 step 7 deferred tracking rule. |
| 11 | 2026-05-31 | **Proposal B — Cross-origin download pattern in UI Guidelines:** The HTML `download` attribute is silently ignored by all browsers for cross-origin presigned URLs (R2, S3). Any download button pointing at a presigned URL must use the blob-fetch pattern. Documented in `docs/UI_GUIDELINES.md` "File downloads" section. |
| 11 | 2026-05-31 | **Proposal C — Negative-path test requirement for fallback/skip branches:** When a story adds a function with a fallback or early-return branch (e.g. "if X already exists, skip"), tests must explicitly cover the "already has X" case. Root cause: `copy_music_to_run` had 7 tests, none covering the operator-upload-already-present path; the bug was only caught during smoke testing. Applied to `/finish-story` v0.5 step 1 verification checklist. |
| P10/P11-S1 | 2026-07-03 | **Proposal A — Enforce the deferred-smoke-test threshold:** The Sprint 11 rule (count ≥ 3 → "flags an integration story") had no teeth — deferred count reached 7 across P9–P11-S1 with no sweep story ever added. Changed `/sprint-review` step 6 so the DEV smoke-sweep story is now mandatory (not a footnote) once the threshold is crossed. Applied to `/sprint-review` v0.2 step 6. |
| P10/P11-S1 | 2026-07-03 | **Proposal B — Surface untracked fixes:** 10 `fix:` commits landed after P11-S1 shipped with no story ID and no DONE.md entry; 5 of them repeatedly re-patched the same feature (character/person portrait acquisition) instead of getting a proper regression-tested story. Added `/sprint-review` step 1.5: grep commits since the last sprint-review for story-less `fix:`/`hotfix:` messages, list them, and call out 3+-commit clusters on the same area as a story candidate. Applied to `/sprint-review` v0.2. |
| P10/P11-S1 | 2026-07-03 | **Proposal C — Keep CLAUDE.md in sync at sprint boundaries:** CLAUDE.md's "Current sprint"/"Active story" lines were stale (still said "P8 complete, next P9") while SPRINT.md and DONE.md showed work through P11-S1 — the bootstrap file every session reads first had drifted. `/sprint-review` step 7 now updates CLAUDE.md alongside SPRINT.md. Applied to `/sprint-review` v0.2 step 7. |
