-- cf_platform migration 0005 — accounts, sessions, per-tenant usage and the prompt log
-- (Sprint P-AUTH, D114, D115, D118). Idempotent / re-runnable like 0001-0004.
--
-- users:        one row per person. `user_id` is internal; `google_sub` is the Google
--               identity (never the e-mail). `tenant_id` is the personal tenant every
--               row of data belongs to — the owner's row maps onto the legacy tenant
--               'operator' so existing runs stay theirs.
-- sessions:     server-side, expiring and revocable. Only the SHA-256 of the cookie
--               token is stored.
-- oauth_states: a pending Google sign-in (single use, minutes of life).
-- tenant_usage: one row per tenant per UTC day — runs started and dollars spent; the
--               interim cost bound until the credit ledger (P-BILL-1).
-- prompt_log:   what was sent to a paid model, per tenant, with the moderation verdict.

CREATE TABLE IF NOT EXISTS users (
    user_id           TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL UNIQUE,
    google_sub        TEXT UNIQUE,
    email             TEXT NOT NULL DEFAULT '',
    name              TEXT NOT NULL DEFAULT '',
    account_type      TEXT NOT NULL DEFAULT 'basic' CHECK (account_type IN ('basic', 'super')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at     TIMESTAMPTZ,
    terms_version     TEXT,
    terms_accepted_at TIMESTAMPTZ,
    disabled_at       TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users (user_id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL,
    revoked_at    TIMESTAMPTZ,
    view_as_basic BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);

CREATE TABLE IF NOT EXISTS oauth_states (
    state_hash    TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    next_path     TEXT NOT NULL DEFAULT '/',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tenant_usage (
    tenant_id  TEXT NOT NULL,
    day        DATE NOT NULL,
    runs       INT NOT NULL DEFAULT 0,
    spend_usd  DOUBLE PRECISION NOT NULL DEFAULT 0,
    renders    INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, day)
);

CREATE TABLE IF NOT EXISTS prompt_log (
    id         BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    user_id    TEXT NOT NULL DEFAULT '',
    run_id     TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    excerpt    TEXT NOT NULL DEFAULT '',
    verdict    TEXT NOT NULL DEFAULT 'allowed',
    reason     TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prompt_log_tenant_created ON prompt_log (tenant_id, created_at DESC);

-- A run's project must belong to the same tenant; the index serves the per-tenant lists.
CREATE INDEX IF NOT EXISTS idx_runs_tenant_created ON runs (tenant_id, created_at DESC);
