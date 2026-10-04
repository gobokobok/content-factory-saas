-- cf_platform migration 0003 — tenant-level settings (Sprint P14, D104).
--
-- One row per tenant. Holds the chosen image provider and model and the tenant's
-- provider API keys. `api_keys` maps provider name -> {"encrypted": <Fernet token>,
-- "hint": <last four characters>}; a key is never stored in plain text and never
-- returned by the API. Idempotent / re-runnable like 0001 and 0002.

CREATE TABLE IF NOT EXISTS tenant_settings (
    tenant_id      TEXT PRIMARY KEY,
    image_provider TEXT,
    image_model    TEXT,
    api_keys       JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
