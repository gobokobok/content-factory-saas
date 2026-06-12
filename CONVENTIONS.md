# Coding Conventions — Content Factory

Language: Python 3.11
All code must follow these conventions. No exceptions.

---

## General rules

- **No hardcoded values.** All config via ENV vars through `src/config.py`.
- **Every function has a docstring.** One-line minimum. Multi-line for complex logic.
- **Type hints required** on all function signatures (parameters + return type).
- **Every story ships with tests.** No exceptions. See docs/TESTING.md.
- **No new dependency** without a DECISIONS.md entry.

---

## Naming

| Item | Convention | Example |
|------|-----------|---------|
| Files | `snake_case.py` | `drive_client.py` |
| Functions | `snake_case` | `create_run_folder()` |
| Classes | `PascalCase` | `DriveClient` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT_SECONDS` |
| Pydantic models | `PascalCase` | `StoryboardScene` |
| ENV vars | `UPPER_SNAKE_CASE` | `ANTHROPIC_API_KEY` |
| Route files | `snake_case.py` in `src/routes/` | `src/routes/runs.py` |

---

## Project structure

```
/src
  main.py              ← FastAPI app, router registration, startup validation
  config.py            ← pydantic-settings Settings class, all ENV vars
  models.py            ← all Pydantic schemas (RunLog, Storyboard, Manifest, etc.)
  drive.py             ← Google Drive client and helpers
  storyboard.py        ← Claude API call, storyboard parsing
  manifest.py          ← asset manifest builder
  pexels.py            ← Pexels API client
  replicate_client.py  ← Replicate/Flux client
  acquisition.py       ← asset acquisition orchestrator
  ffmpeg_builder.py    ← FFmpeg script generator
  renderer.py          ← FFmpeg execution and output upload
  /routes
    runs.py            ← /runs endpoints
    storyboard.py      ← /storyboard endpoints
    manifest.py        ← /manifest endpoints
    assets.py          ← /assets endpoints
    ffmpeg_script.py   ← /ffmpeg-script endpoints
    render.py          ← /render endpoints
  /static
    index.html
    run.html
    app.js
    run.js
    style.css
/tests
  test_health.py
  test_drive.py
  test_runs.py
  test_storyboard.py
  test_manifest.py
  test_pexels.py
  test_replicate_client.py
  test_acquisition.py
  test_ffmpeg_builder.py
  test_renderer.py
  test_ui_routes.py
/tools
  script-generator.html    ← standalone, not integrated
/docs
/scripts
```

---

## Docstrings

```python
def create_run_folder(slug: str, root_folder_id: str) -> str:
    """Create a dated run folder and all subfolders in Drive. Returns folder ID."""

def call_storyboard_api(script: str, system_prompt: str) -> dict:
    """
    Call Claude API with v0.4 system prompt and plain-text script.

    Returns parsed storyboard dict. Raises StoryboardParseError on invalid response.
    """
```

---

## Error handling

- Raise typed exceptions defined in `src/exceptions.py` (create as needed).
- FastAPI routes catch domain exceptions and return appropriate HTTP status codes.
- Never swallow exceptions silently. Log before re-raising or returning error response.
- On step failure: update `run_log.json` with `failed` status and error message before returning.

---

## Tests

- Use `pytest`.
- Mock all external APIs (Google Drive, Claude, Pexels, Replicate, Freesound).
- Test happy path + at least one failure case per function.
- Integration tests (hitting real APIs) live in `tests/integration/` and are excluded from CI via `pytest -m "not integration"`.
- See docs/TESTING.md for full strategy.

---

## Git

- Branch per story: `story/e1-s1-service-skeleton`
- Commit format: `feat(e1-s1): add health check endpoint`
- Merge to `main` when CI is green → auto-deploys to DEV.
- Tag `v*.*.*` to deploy to PROD.
- Never commit `.env`, `.env.local`, or service account JSON files.

---

## FastAPI conventions

- All routes registered in `src/main.py` via `app.include_router()`.
- Route files in `src/routes/` — one file per epic/resource.
- Use `Depends()` to inject `Settings` config into routes.
- Response models defined in `src/models.py` and referenced in route decorators.

---

## Async function discipline (agent-ready pipeline)

**Every pipeline step function must be a pure async function that takes explicit inputs and returns explicit outputs. It must not read from global state, session context, or the HTTP request object.**

This is a hard architectural constraint, not a style preference. It is required because:
- Sprints 13–19 introduce chunked storyboard generation, parallel acquisition, and background render tasks — all of which call the same functions from outside an HTTP request context.
- Sprints 20+ will wrap these functions in a durable workflow engine (Inngest). Functions that are tightly coupled to FastAPI's request lifecycle cannot be orchestrated externally.

### Rules

1. **Pure inputs, pure outputs.** The function signature carries everything it needs.
   ```python
   # ✅ correct
   async def generate_storyboard(
       script: str,
       alignment: list[WordTimestamp],
       settings: StoryboardSettings,
       storage: R2Client,
   ) -> Storyboard:
       ...

   # ❌ wrong — reads request state, not portable
   async def generate_storyboard(request: Request) -> Storyboard:
       script = await request.json()
       ...
   ```

2. **Routes are thin wrappers.** The route handler reads the request, calls the domain function, and writes the response. No business logic in route files.
   ```python
   # ✅ correct route handler
   @router.post("/runs/{run_id}/storyboard")
   async def storyboard_route(run_id: str, body: StoryboardRequest, ...):
       result = await generate_storyboard(body.script, alignment, settings, storage)
       await storage.upload_json(f"runs/{run_id}/storyboard.json", result.model_dump())
       return StoryboardResponse(status="complete", ...)
   ```

3. **No `asyncio.run()` inside functions.** If a function is sync today but will be called from an async context, mark it `async` and use `await asyncio.to_thread()` at the call site to wrap sync I/O.

4. **Sync clients wrapped at the call site.** `PexelsClient` and `ReplicateClient` are synchronous (HTTP via `requests`). When called from async acquisition batches, wrap with `asyncio.to_thread(client.acquire_for_entry, entry, run_id, storage)` — do not convert the client itself to async unless rewriting it.

5. **No side effects on failure mid-function.** If a function fails halfway, it must not leave partial state in R2 or `run_log.json`. Write atomically: compute the full result first, then write once.

### Rationale
Logged as D040 in DECISIONS.md.

---

## Platform v2 — worker/node contract (D056) and state discipline (D057)

Applies to all code under `cf_platform/`. Canonical spec: docs/v2_platform_plan.md §3–§5. Enforced in code review like D040.

### Worker = Node
- A **worker IS a LangGraph node implementation.** Hierarchy: **Worker → Node**, **Stage → StateGraph**, **Platform → Graph-of-graphs**.
- A worker is **stateless and pure** (D040 applies): it receives a typed `StageState` and returns a typed `WorkerOutput`. No hidden state, no side effects in the body.
- A worker is **version-pinned** (worker_version + prompt_version + model + sampling_params) and emits **exactly one artifact per execution** — written by the observability wrapper, **not** the worker body. The worker never knows its own `r2_key`.
- **Routing is graph edges, not workers.** Conditional/branch logic lives on edges; it produces no artifact and no `worker_execution`.
- **IO adapters are not workers.** Source adapters and the legacy adapter emit `TraceEvent`s, never artifacts.

### State is a message bus, not a data store
- Graph state carries **only** artifact references (`stage -> r2_key`) and strict control signals (`ControlSignal = "continue" | "retry" | "branch"`).
- **No `state_delta` / free-form dict.** Control *values* (iteration counters, mode) are typed channels on the per-stage `StageState`, updated by graph reducers; the **graph** (not the worker) enforces loop bounds.
- The durable source of truth is always the **artifact in R2**, indexed in Postgres. Anything that must persist or be queried is an artifact or a row — never a state field.

### Reproducibility (D055)
- Artifacts are **immutable** — a re-run writes a new version, never mutates in place.
- `execution = f(prompt_version, model, inputs, sampling_params)`; all are pinned and recorded. (No request seed on Claude — variance is bounded, not eliminated.)
