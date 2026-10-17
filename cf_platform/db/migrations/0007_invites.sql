-- cf_platform migration 0007 — invited Google accounts, managed by the owner in the Studio.
-- Sign-in is allowed for these e-mails in addition to the ALLOWED_EMAILS variable (D119).
-- Idempotent / re-runnable like 0001-0006.

CREATE TABLE IF NOT EXISTS invited_emails (
    email      TEXT PRIMARY KEY,
    added_by   TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
