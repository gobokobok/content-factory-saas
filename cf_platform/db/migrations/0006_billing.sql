-- cf_platform migration 0006 — usage ledger, credit balances and credit transactions
-- (Sprint P-BILL-1, D114, D123). Idempotent / re-runnable like 0001-0005.
--
-- usage_entries:       one row per paid action (LLM, TTS, transcription, image, render)
--                      with its raw provider cost and the credits it was priced at.
--                      status: held -> settled | refunded; 'exempt' (owner) and 'metered'
--                      (billing off) rows carry no credits.
-- credit_accounts:     one balance per tenant, in whole credits. The CHECK is the
--                      last line of defence: a balance can never go negative.
-- credit_transactions: every change to a balance (topup, signup, hold, settle, refund,
--                      adjustment), signed, so a balance can be rebuilt from them.

CREATE TABLE IF NOT EXISTS usage_entries (
    entry_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL,
    run_id       TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL CHECK (kind IN ('llm', 'tts', 'transcription', 'image', 'render')),
    what         TEXT NOT NULL DEFAULT '',
    units        DOUBLE PRECISION NOT NULL DEFAULT 1,
    raw_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    actual_usd   DOUBLE PRECISION,
    credits      BIGINT NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'settled', 'refunded', 'exempt', 'metered')),
    note         TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_usage_entries_tenant_created ON usage_entries (tenant_id, created_at DESC);

CREATE TABLE IF NOT EXISTS credit_accounts (
    tenant_id  TEXT PRIMARY KEY,
    balance    BIGINT NOT NULL DEFAULT 0 CHECK (balance >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS credit_transactions (
    tx_id      BIGSERIAL PRIMARY KEY,
    tenant_id  TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('topup', 'signup', 'hold', 'settle', 'refund', 'adjustment')),
    credits    BIGINT NOT NULL,
    entry_id   TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    actor      TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_credit_transactions_tenant_created ON credit_transactions (tenant_id, created_at DESC);
-- A sign-up grant is made once per tenant, whatever happens to the request that makes it.
CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_transactions_signup ON credit_transactions (tenant_id) WHERE kind = 'signup';
