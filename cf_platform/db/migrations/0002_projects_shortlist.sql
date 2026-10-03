-- cf_platform migration 0002 — Tenant -> Project -> Run hierarchy + persistent shortlist
-- (Sprint P12, D092, D094).
--
-- Idempotent / re-runnable like 0001: every statement is IF NOT EXISTS / ON CONFLICT
-- DO NOTHING, so applying it twice — or on a database that already holds runs — is safe.
--
-- Backfill: one default project is created and every pre-existing run is assigned to
-- it, so nothing disappears when runs stop being top-level. Only runs that already
-- have a row are covered here. Studio runs started from a pasted script never wrote
-- one (their ids were minted in the browser); those are registered into the default
-- project by POST /platform/projects/{id}/runs/import the first time a browser that
-- knows them opens the project list.

-- ── projects ─────────────────────────────────────────────────────────────
-- One row per Project (cf_platform/core/projects.py). `config` holds content/style
-- defaults for new runs; research configuration lands in it in P15.
CREATE TABLE IF NOT EXISTS projects (
    project_id         TEXT PRIMARY KEY,
    tenant_id          TEXT NOT NULL,
    name               TEXT NOT NULL,
    niche              TEXT NOT NULL DEFAULT '',
    config             JSONB NOT NULL DEFAULT '{}'::jsonb,
    default_channel_id TEXT,                       -- filled in P16
    archived_at        TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_projects_tenant_id ON projects (tenant_id);

-- The default project. tenant_id matches PLATFORM_USER_ID, the single operator
-- (D092 — no multi-tenant auth yet).
INSERT INTO projects (project_id, tenant_id, name)
VALUES ('default', 'operator', 'Default project')
ON CONFLICT (project_id) DO NOTHING;

-- ── runs: project membership ─────────────────────────────────────────────
-- project_id is NOT NULL with a default, so adding the column IS the backfill:
-- every existing row lands in the default project, and a run can never be stored
-- without one. `name` is the operator-facing label in the project's run list;
-- archived_at hides a run whose R2 assets the operator deleted from Studio.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS tenant_id TEXT;
UPDATE runs SET tenant_id = user_id WHERE tenant_id IS NULL;
ALTER TABLE runs ALTER COLUMN tenant_id SET NOT NULL;

ALTER TABLE runs ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES projects (project_id);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS name TEXT NOT NULL DEFAULT '';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_runs_project_id_created_at ON runs (project_id, created_at DESC);

-- ── shortlist_items ──────────────────────────────────────────────────────
-- One row per ShortlistItem (cf_platform/core/shortlist.py). Items are only ever
-- added, and only ever removed one at a time by the operator (D094). Removal is a
-- soft delete so a run created from an item keeps a valid reference. The origin
-- columns (discovery_method, source, evidence, kpis, research_run_id) are filled
-- by hand-entry now and by research in P15.
CREATE TABLE IF NOT EXISTS shortlist_items (
    item_id          TEXT PRIMARY KEY,
    tenant_id        TEXT NOT NULL,
    project_id       TEXT NOT NULL REFERENCES projects (project_id),
    title            TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    discovery_method TEXT NOT NULL CHECK (discovery_method IN ('manual', 'trend', 'competitor')),
    source           TEXT,                          -- e.g. "reddit", "google_news", a channel handle
    evidence         JSONB NOT NULL DEFAULT '{}'::jsonb,   -- why it is trending / why it performs
    kpis             JSONB NOT NULL DEFAULT '{}'::jsonb,   -- e.g. likes_per_1k_views, outlier_score
    research_run_id  TEXT,                          -- filled in P15
    discovered_at    TIMESTAMPTZ NOT NULL,
    removed_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shortlist_items_project_id ON shortlist_items (project_id, discovered_at DESC);

-- ── run_shortlist_items ──────────────────────────────────────────────────
-- Many-to-many: one run can come from several items, one item can feed several runs.
CREATE TABLE IF NOT EXISTS run_shortlist_items (
    run_id     TEXT NOT NULL REFERENCES runs (run_id),
    item_id    TEXT NOT NULL REFERENCES shortlist_items (item_id),
    position   INT NOT NULL DEFAULT 0,             -- order the operator selected them in
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, item_id)
);

CREATE INDEX IF NOT EXISTS idx_run_shortlist_items_item_id ON run_shortlist_items (item_id);

-- ── record hierarchy ─────────────────────────────────────────────────────
-- tenant (1) -> projects (N) -> runs (N)
-- project (1) -> shortlist_items (N) <-> runs (N), via run_shortlist_items
