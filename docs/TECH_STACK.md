# Tech Stack — Content Factory

## Runtime

| Layer | Choice | Version | Rationale |
|-------|--------|---------|-----------|
| Language | Python | 3.11 | Strong library support for all required APIs |
| Web framework | FastAPI | 0.115+ | Async-native, Pydantic validation, auto OpenAPI docs (see DECISIONS.md D004) |
| ASGI server | Uvicorn | 0.32+ | Standard FastAPI production server |
| Data validation | Pydantic v2 | 2.10+ | Schema validation for storyboard, manifest, run_log |
| Config / ENV | pydantic-settings | 2.7+ | Fail-fast ENV validation at startup (see DECISIONS.md D005) |

## Hosting

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Cloud | Railway | Simple Python service deploy, free tier sufficient for POC |
| Environments | DEV (auto on `main`), PROD (git tag `v*.*.*`) | Isolated services, isolated Drive roots |

## Storage

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Run storage | Google Drive API | Operator-familiar, no infra, service account auth (see DECISIONS.md D003) |
| Auth | Service account JSON (base64 ENV var) | Avoids OAuth flow (see DECISIONS.md D015) |
| Client library | google-api-python-client + google-auth | Official Google SDK |

## External APIs

| Service | Use | Tier |
|---------|-----|------|
| Anthropic (Claude) | Storyboard generation (prompt v0.4) | Paid (usage-based) |
| Pexels | Stock footage and images | Free |
| Replicate + Flux | AI image generation fallback | Free tier |
| Freesound | SFX acquisition | Free |

## Video assembly

| Tool | Use |
|------|-----|
| FFmpeg | Video composition, audio mixing, 9:16 output |

FFmpeg runs directly on Railway Linux containers. Assets downloaded to `/tmp` during render.

## Operator UI

| Choice | Rationale |
|--------|-----------|
| Plain HTML + vanilla JS | No framework overhead for minimal operator UI (see DECISIONS.md D014) |
| Served by FastAPI | No separate frontend service needed |

## Key Python packages

```
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
anthropic>=0.40.0
google-api-python-client>=2.157.0
google-auth>=2.37.0
google-auth-httplib2>=0.2.0
requests>=2.32.0
replicate>=1.0.0
python-dotenv>=1.0.1
pydantic>=2.10.0
pydantic-settings>=2.7.0
pytest>=8.3.0
pytest-asyncio>=0.24.0
httpx>=0.28.0
```
