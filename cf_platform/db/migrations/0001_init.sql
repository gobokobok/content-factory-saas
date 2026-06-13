-- cf_platform migration 0001 — initial Postgres metadata-index schema (P2-S2, D048).
--
-- Idempotent / re-runnable: every statement uses IF NOT EXISTS so this file can be
-- applied repeatedly without error. Applied by cf_platform/core/migrations.py, which
-- tracks applied migrations in schema_migrations.
--
-- Source of truth split (D048):
--   R2       -> artifact bodies (immutable, versioned JSON/media)
--   Postgres -> queryable index: lineage as COLUMNS (not JSON), so
--               prompt_version / worker_version / model can be grouped and
--               joined directly for analytics (P7 attribution query).
-- See docs/v2_platform_plan.md §6 and cf_platform/db/schema.sql for the design draft.

-- ── runs ─────────────────────────────────────────────────────────────────
-- One row per RunRecord (cf_platform/core/schemas.py). run_id matches the R2
-- key prefix: users/{user_id}/runs/{run_id}/...
CREATE TABLE IF NOT EXISTS runs (
    run_id     TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    block      TEXT NOT NULL,                 -- e.g. "niche_to_ideas", "idea_to_script", "pipeline"
    status     TEXT NOT NULL CHECK (status IN ('created', 'running', 'complete', 'failed')),
    inputs     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error      TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_runs_user_id ON runs (user_id);
CREATE INDEX IF NOT EXISTS idx_runs_block_status ON runs (block, status);

-- ── artifacts ────────────────────────────────────────────────────────────
-- One row per Artifact (cf_platform/core/schemas.py). Body lives in R2 at
-- r2_key; this row is the queryable index + lineage. Artifacts are immutable
-- — a re-run inserts a new row with version = previous + 1, never an UPDATE
-- of r2_key/version on an existing row (D055).
CREATE TABLE IF NOT EXISTS artifacts (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs (run_id),
    name            TEXT NOT NULL,            -- e.g. "signals", "script"
    stage           TEXT NOT NULL,            -- e.g. "niche_to_ideas"
    version         INT NOT NULL,
    r2_key          TEXT NOT NULL,
    content_type    TEXT NOT NULL DEFAULT 'application/json',
    schema_version  TEXT NOT NULL DEFAULT '1',
    -- lineage (D051, D055) — columns, not nested JSON, so they're directly groupable/joinable
    worker          TEXT NOT NULL,
    worker_version  TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    sampling_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, stage, name, version)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts (run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_prompt_version ON artifacts (prompt_version);

-- ── worker_executions ───────────────────────────────────────────────────
-- One row per WorkerExecution (cf_platform/core/schemas.py) — written by the
-- observability wrapper (Layer B, P1-S5) around every worker-node. Exactly
-- one execution row per node call; it points at the one artifact that call
-- produced via artifact_r2_key (nullable — a "retry"/"branch" control signal
-- may short-circuit before an artifact is written).
CREATE TABLE IF NOT EXISTS worker_executions (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs (run_id),
    worker          TEXT NOT NULL,
    worker_version  TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    sampling_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12, 6) NOT NULL DEFAULT 0,
    latency_ms      INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    artifact_r2_key TEXT,
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_executions_run_id ON worker_executions (run_id);
CREATE INDEX IF NOT EXISTS idx_worker_executions_prompt_version ON worker_executions (prompt_version);
CREATE INDEX IF NOT EXISTS idx_worker_executions_worker_version ON worker_executions (worker_version);

-- ── trace_events ─────────────────────────────────────────────────────────
-- One row per TraceEvent (cf_platform/core/schemas.py) — emitted by IO
-- adapters (SourceAdapter, legacy adapter), never by workers (D050, D057).
-- A single worker_execution can emit N trace_events (e.g. one Discovery
-- worker call fanning out to 3 source adapter fetches).
CREATE TABLE IF NOT EXISTS trace_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs (run_id),
    worker      TEXT NOT NULL,             -- the worker the adapter ran inside
    source      TEXT NOT NULL,             -- e.g. "reddit", "google_trends", "legacy_video"
    op          TEXT NOT NULL,
    latency_ms  INT NOT NULL DEFAULT 0,
    cost_usd    NUMERIC(12, 6),
    status      TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run_id ON trace_events (run_id);
CREATE INDEX IF NOT EXISTS idx_trace_events_source ON trace_events (source);

-- ── published_videos (reserved for P7) ──────────────────────────────────
-- Links a completed run to the platform(s) it was published to. Populated
-- by P7-S1 (publish linkage capture).
CREATE TABLE IF NOT EXISTS published_videos (
    id           BIGSERIAL PRIMARY KEY,
    run_id       TEXT NOT NULL REFERENCES runs (run_id),
    platform     TEXT NOT NULL,            -- e.g. "youtube", "instagram"
    external_id  TEXT NOT NULL,            -- platform's video/post ID
    url          TEXT,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, external_id)
);

CREATE INDEX IF NOT EXISTS idx_published_videos_external_id ON published_videos (external_id);
CREATE INDEX IF NOT EXISTS idx_published_videos_run_id ON published_videos (run_id);

-- ── video_metrics (reserved for P7) ─────────────────────────────────────
-- Time series of platform-reported metrics per published video. Populated
-- by P7-S2 (YouTube Analytics ingestion worker).
CREATE TABLE IF NOT EXISTS video_metrics (
    id          BIGSERIAL PRIMARY KEY,
    external_id TEXT NOT NULL,
    platform    TEXT NOT NULL,
    metric      TEXT NOT NULL,             -- e.g. "average_view_percentage"
    value       DOUBLE PRECISION NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_video_metrics_external_id_captured_at ON video_metrics (external_id, captured_at);

-- ── record hierarchy ─────────────────────────────────────────────────────
-- run (1) -> worker_executions (N) -> trace_events (N)
-- run (1) -> artifacts (N)
-- run (1) -> published_videos (N) -> video_metrics (N, joined via external_id)
