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
