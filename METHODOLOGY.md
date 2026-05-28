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
