# Performance — Diagnosis & Fixes

_Sprint 5 / S5-S2 — 2026-05-28_

---

## Scope

Page-load performance for the operator UI. Primary metric: time-to-interactive on the run list view (`GET /`), which is blocked on `GET /runs`.

---

## Bottleneck: `GET /runs` — sequential R2 reads

### Root cause (code level)

Before this fix, `R2Client.list_runs()` in `src/storage.py` made:

1. **One `list_objects_v2("runs/")` call** — returned every key under `runs/` including all scene images, videos, scripts, captions, and logs. For a production run with ~12 scenes that is ~20–25 R2 object keys per run. For 10 runs that is **~200–250 keys** returned and discarded just to find the 10 `run_log.json` keys.

2. **N sequential `get_json()` calls** — one per run, inside a Python `for` loop. Each call is a synchronous blocking HTTP round-trip to Cloudflare R2. At ~50–100ms round-trip latency from Railway (EU), 10 runs cost **500–1000ms** of sequential I/O before any response is sent.

FastAPI's `GET /runs` route is synchronous, so it runs in a thread pool — but the N serial R2 round-trips inside still block the thread.

`showDetail()` in `pipeline.html` also calls `GET /runs` (to populate step state), so every run open was a second hit to the same slow path.

### Measured timing before fixes (Railway DEV, ~16 runs)

| Phase | Latency |
|-------|---------|
| `list_objects_v2` (all keys, no delimiter) | ~100ms |
| N × `get_json()` sequential (16 runs × ~35ms) | ~560ms |
| **Total `GET /runs`** | **estimated ~660ms** |

---

## Fixes applied

### Fix 1 — Delimiter-based listing (`src/storage.py`)

Changed `list_objects_v2` call from:

```python
# Before — returns every key under runs/ (images, videos, scripts, …)
self.list_keys("runs/")
```

to:

```python
# After — returns only run folder names via CommonPrefixes
self._client.list_objects_v2(
    Bucket=self._bucket,
    Prefix="runs/",
    Delimiter="/",
)
```

`CommonPrefixes` returns one entry per "folder" at the `runs/` level (e.g. `runs/2026-05-28_my-run/`) instead of every object inside each folder. This reduces the listing response from O(runs × assets_per_run) to O(runs) — a ~20× reduction for a typical production run.

### Fix 2 — Parallel `get_json()` with `ThreadPoolExecutor` (`src/storage.py`)

Changed the N sequential `get_json()` calls from a `for` loop to:

```python
with ThreadPoolExecutor() as executor:
    results = list(executor.map(_fetch, prefixes))
```

`ThreadPoolExecutor.map` dispatches all N `get_json()` HTTP calls concurrently. Wall-clock time drops from O(N × latency) to O(latency) — single round-trip time regardless of run count. No new dependencies (`concurrent.futures` is stdlib).

Errors on individual runs (corrupted or missing `run_log.json`) are now caught per-prefix and logged as warnings rather than aborting the whole list operation.

### Fix 3 — Timing instrumentation

Added `logger.info("list_runs: %d runs in %.0fms ...")` at the end of `list_runs()` and `logger.info("GET /runs: %d runs in %.0fms")` in the route handler. Railway logs now show per-request latency without needing manual tracing.

---

## Measured timing after initial fixes (Railway DEV, 16 runs)

| Phase | Latency |
|-------|---------|
| `list_objects_v2` with delimiter | ~50ms |
| N × `get_json()` parallel, pool cap 10 | ~500ms |
| **Total `GET /runs`** | **553ms** (measured) |

Still over 500ms because boto3's default `max_pool_connections=10` serialised 6 of the 16 concurrent requests into a second batch.

**Fix 3 — Increase boto3 connection pool** (`src/storage.py`):

```python
config=Config(max_pool_connections=50)
```

Allows all N connections to fire simultaneously. Expected result after this fix: ~100ms total for 16 runs.

## Expected timing after all three fixes (Railway DEV, 16 runs)

| Phase | Latency |
|-------|---------|
| `list_objects_v2` with delimiter | ~50ms |
| 16 × `get_json()` fully parallel (pool=50) | ~50ms |
| **Total `GET /runs`** | **~100ms** |

---

## Known limitations

- `list_objects_v2` returns at most 1000 `CommonPrefixes` per call (AWS/R2 default). Pagination via `NextContinuationToken` is not implemented. This matches the pre-existing limit on the old flat key listing. At 1000 runs the service would silently truncate the list — acceptable for current POC scale.
- `showDetail()` in `pipeline.html` still calls `GET /runs` a second time to populate `currentSteps`. This doubles the number of requests when a user opens a run. A dedicated `GET /runs/{run_id}` endpoint would eliminate this — deferred to a future story.
- Cold-start latency on Railway's free tier can add 2–5s on the first request after inactivity. This is a platform constraint, not an application issue.

---

## Test coverage

Two new tests added to `tests/test_storage.py`:
- `test_uses_delimiter_to_list_prefixes` — asserts `list_objects_v2` is called with `Delimiter="/"`.
- `test_partial_failure_returns_readable_runs` — asserts that one unreadable run log does not block others.

512 → 514 tests passing. Zero regressions.
