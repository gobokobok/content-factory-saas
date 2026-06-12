-- Content Factory v2 Platform — analytics queries (design draft, P0-S4)
--
-- These queries are written against cf_platform/db/schema.sql to prove the
-- joins resolve conceptually. Not executed by any code path yet (P0 is
-- interfaces-only). P7-S3 implements the attribution query for real.

-- ── Attribution query (P7-S3) ───────────────────────────────────────────
-- "Which prompt_version of <worker> correlates with higher retention?"
-- Join path: video_metrics.external_id -> published_videos.external_id
--            -> published_videos.run_id -> runs.run_id
--            -> worker_executions.run_id (filtered to the worker of interest)
-- All join keys are plain columns (TEXT), no JSON unpacking required.
SELECT
    we.prompt_version,
    AVG(vm.value) AS avg_retention,
    COUNT(*)      AS n
FROM video_metrics vm
JOIN published_videos pv ON pv.external_id = vm.external_id
JOIN runs r               ON r.run_id      = pv.run_id
JOIN worker_executions we ON we.run_id     = r.run_id
                          AND we.worker    = $1   -- e.g. 'script_writer' or 'storyboard' (legacy bridge)
WHERE vm.metric = 'average_view_percentage'
GROUP BY we.prompt_version
ORDER BY avg_retention DESC;

-- ── Per-run worker cost/latency/version (P2 human touchpoint) ──────────
-- "Operator inspects per-worker cost/latency/version for a run."
SELECT
    worker,
    worker_version,
    prompt_version,
    model,
    status,
    input_tokens,
    output_tokens,
    cost_usd,
    latency_ms,
    started_at,
    finished_at
FROM worker_executions
WHERE run_id = $1
ORDER BY started_at;

-- ── Run-level cost rollup ────────────────────────────────────────────────
-- Total cost/latency for a run, e.g. for a Project Report-style summary.
SELECT
    run_id,
    SUM(cost_usd)    AS total_cost_usd,
    SUM(latency_ms)  AS total_latency_ms,
    COUNT(*)         AS worker_execution_count
FROM worker_executions
WHERE run_id = $1
GROUP BY run_id;

-- ── Trace events for a run, newest first (debugging an adapter) ────────
SELECT
    worker,
    source,
    op,
    latency_ms,
    cost_usd,
    status,
    meta,
    created_at
FROM trace_events
WHERE run_id = $1
ORDER BY created_at DESC;

-- ── Artifact lineage for a run (replay / Epic 34) ───────────────────────
SELECT
    stage,
    name,
    version,
    r2_key,
    worker,
    worker_version,
    prompt_version,
    model,
    sampling_params,
    created_at
FROM artifacts
WHERE run_id = $1
ORDER BY stage, name, version;
