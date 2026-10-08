-- cf_platform migration 0004 — tenant-level defaults (Sprint P-UX build).
--
-- `defaults` holds what every project inherits unless it overrides it: language,
-- format (aspect ratio), captions and the AI-image spend cap per run. Idempotent /
-- re-runnable like 0001-0003.

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS defaults JSONB NOT NULL DEFAULT '{}'::jsonb;
