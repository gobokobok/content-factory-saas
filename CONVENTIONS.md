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
