# Runbook — production checks

PROD is the Railway project `content-factory-saas-prod`, service `content-factory-saas`. The repository is linked to the DEV project, so PROD logs are read by passing the project, environment and service explicitly:

```bash
railway list --json          # project, environment and service ids
railway logs -p <prod project id> -e <environment id> -s <service id> -n 5000
```

`railway logs` shows the live deployment only. A release replaces it, so `/prod-check` runs before each `/release` (APEX-DEV, 2026-10-03).

Entries are newest first.

---

## Backups and restore (HARD2-S1, SECURITY.md F1)

**Status 2026-10-13: procedure written, no drill recorded yet.** F1 stays open until the first row of the drill table below is filled in. Nothing here has been run against DEV or PROD by the author; every "expected" line is what to look for, not a verified result.

### What holds state

| Store | Holds | Lost means | Backed up by |
|-------|-------|------------|--------------|
| Postgres (Railway; `DATABASE_URL`) | Projects, runs, the artifact index (`artifacts` rows with R2 keys and lineage), `tenant_settings` (including the **encrypted** tenant API keys), shortlist, trace events, worker executions | Every run still has its files, but nothing points at them: runs disappear from Studio, lineage and cost history are gone, saved keys are gone | Railway database backups (step 1) |
| R2 bucket (`R2_BUCKET_NAME`: DEV `content-factory-dev`, PROD `content-factory`) | Every artifact body, voiceover, image, render, library file | The videos and their sources | Object versioning, if the bucket supports it (step 2); otherwise a copy (step 2b) |
| `SETTINGS_ENCRYPTION_KEY` (Railway variable) | Decrypts the tenant keys in Postgres | A restored database is readable but every saved key is useless | **Your password manager, not Railway.** Store the value there now. |
| Google Drive | Legacy runs only; not written by the platform | — | Not in scope |

A Postgres backup is only useful with the R2 bucket and `SETTINGS_ENCRYPTION_KEY` as they were at the same time. R2 objects are never mutated in place (artifacts are immutable, D055), so a database restored to an earlier point still finds every object it refers to; objects written after that point are orphaned, not corrupted.

### 1. Postgres backups — enable and check (operator, Railway dashboard)

Do this for DEV and PROD separately.

1. Railway → the project → the **Postgres** service → **Backups**.
2. Enable scheduled backups (daily is enough for now). Backups are plan-dependent: if the tab is missing or locked, the plan does not include them — then use the manual dump in step 1b and run it before every release.
3. Press **Backup now** once and confirm a row appears with a size above zero.
4. Write down the retention the dashboard shows in the drill table (a backup that expires before you notice a problem is not one).

**1b. Manual dump (works on any plan; also the base of the drill).** From a machine with `pg_dump` 15+ (the Postgres major version of the service):

```bash
# DATABASE_URL: Railway → Postgres service → Variables → DATABASE_PUBLIC_URL
pg_dump "$DATABASE_PUBLIC_URL" --format=custom --no-owner --file=cf-$(date +%F).dump
ls -lh cf-*.dump
```

Expected: a file of a few MB (more with long history). Keep it out of the repository.

### 2. R2 — check versioning (operator, Cloudflare dashboard)

D025 assumed object versioning could be switched on per bucket. **That has never been checked, and R2 may not offer it.**

1. Cloudflare → R2 → the bucket → **Settings**. Look for an object-versioning or object-lock control.
2. Record what you find in the drill table: "versioning on", or "no such setting".
3. If there is no such setting, D025's protection does not exist. A deleted or overwritten object is then gone. See 2b.

**2b. Without versioning.** The platform never overwrites an artifact, but `current_job.json`, `settings.json`, voice uploads and a scene upload (`scene_NN_op.*`) are overwritten in place, and a run delete removes everything under `runs/{run_id}/`. Until a copy job exists, the rule is: **do not delete a run you might want back.** A scheduled bucket-to-bucket copy (for example `rclone sync` to a second R2 bucket or another provider) is the fix; it needs a decision on where and at what cost, so it is a backlog item, not part of this section.

### 3. Restore drill — onto a scratch database

Purpose: prove a backup restores and the app can read it, **without touching DEV or PROD**. Repeat before the beta opens and after any schema change that matters.

1. **Scratch database.** A second Postgres service in a throwaway Railway project, or a local one: `docker run --rm -e POSTGRES_PASSWORD=drill -p 5433:5432 postgres:15`. Never restore into the service you took the dump from.
2. **Restore** the dump (from 1b, or a Railway backup downloaded from the Backups tab):

   ```bash
   pg_restore --no-owner --dbname "postgresql://postgres:drill@localhost:5433/postgres" cf-YYYY-MM-DD.dump
   ```

   Expected: no errors other than "role does not exist" notices (hidden by `--no-owner`).
3. **Check the data is intact.** Run on both the source and the scratch database and compare:

   ```sql
   SELECT 'runs' AS t, count(*) FROM runs
   UNION ALL SELECT 'artifacts', count(*) FROM artifacts
   UNION ALL SELECT 'projects', count(*) FROM projects
   UNION ALL SELECT 'tenant_settings', count(*) FROM tenant_settings
   UNION ALL SELECT 'schema_migrations', count(*) FROM schema_migrations;
   ```

   Expected: counts equal, or the scratch ones smaller by only what was created after the dump.
4. **Check the pointers resolve.** Take one `r2_key` from `SELECT r2_key FROM artifacts ORDER BY created_at DESC LIMIT 1;` and confirm that object exists in the bucket (Cloudflare dashboard → R2 → the bucket → search the key). Expected: it exists.
5. **Optional, the strongest check.** Start the app locally with `DATABASE_URL` pointing at the scratch database, the DEV R2 credentials and the matching `SETTINGS_ENCRYPTION_KEY`, open a run in Studio, and confirm the script and voiceover load. `GET /health` shows `"migrations": "ok"`.
6. **Tear down** the scratch database and delete the dump if it holds anything you would not want on a laptop. Record the drill below.

### Drill record

| Date | Environment | Backups enabled (retention) | R2 versioning | Restore result | Row counts matched | By |
|------|-------------|-----------------------------|---------------|----------------|--------------------|----|
| _none yet_ | | | | | | |

### After a failed deploy

`/health` reports `"migrations"` (`ok`, `unavailable` when no database is configured, `error` when the start-up migration failed, which also turns `"status"` to `"degraded"`). The PROD deploy workflow calls it after `railway up` and fails the run on `error` (set the `PROD_URL` repository variable once; without it the step warns and skips). A failed migration leaves the app serving on the old schema: fix the migration, or roll back to the previous deployment in Railway, then re-check `/health`.

---


## Prod check — 2026-10-13 (Sprint review: P14b, P-UX3, P-AN1, P-UX4, P-PROJ1, P-INT1)
**Range:** the live deployment's log, 2026-10-07 18:01 UTC → 2026-10-11 15:39 UTC (839 lines, 22 container starts, PROD still v0.24.0). First check with real traffic since 2026-10-03: four runs (`09ec9c83`, `6fe35dab`, `b285c66c`, `597e4d62`), 5 voice, 3 storyboard, 2 acquisition, 2 render, 2 metadata, 5 scene uploads, 2 re-acquires. Both renders completed (final.mp4 uploaded).

**Errors:** no 5xx. 404s are `/favicon.ico` (15), manifest/storyboard/metadata of a run before the step ran (9).
**Degraded, repeated:** `trace_events.record failed` — `ForeignKeyViolation` on `trace_events_run_id_fkey`, run has no row in `runs` (7 times: upload ×5, reacquire ×2). Pre-P12 Studio runs have no `runs` row; the route swallows the error so the request answers 200 and the trace event is lost. Goes away when P12 is released; until then PROD loses scene-edit lineage.
**Silent failure:** run `6fe35dab` 2026-10-10 19:12 — Gemini TTS answered 200 but the body was cut (`incomplete chunked read`); the worker set `mp3_r2_key=""`, fell back to proportional timing, and logged "VoiceWorker background task complete". The job reads as done with no audio. Not known whether the operator noticed or regenerated.
**Coverage warnings (storyboard worker):** 3 `coverage check failed` — a misheard word ("from" for "of"), a fragmented "60%", missing plural. The storyboard was produced anyway. Same candidate as 2026-10-03 (captions can carry the misheard word).
**API keys in logs:** zero `key=` matches (the log-redaction fix of P14b-S5 is not on PROD, but no Pixabay request is in this window either; DEV check still open).
**Usage:** PROD is used by the operator on real content despite being the older version; DEV carries the new work. Pan/zoom render fix (D107) is not on PROD.
**Stories opened:** proposed in the 2026-10-13 sprint review (voice failure must fail loudly; see BACKLOG).
**Next check due:** before the release of P12 → P-INT1 to PROD.

---

## Prod check — 2026-10-05 (Sprint P14 review)
**Range:** the same live deployment as the two earlier checks (v0.24.0, `edc92ba`). The log holds 353 lines and ends with a clean shutdown; the only warning is still the 2026-10-02 caption coverage one. No new container start and no traffic.

**Errors:** none. **Silent failures:** none seen; stuck runs still cannot be listed (PROD has no P12 tables). **Usage:** nothing new. P14 is DEV-only, so PROD says nothing about it.
**API keys in logs:** zero `key=` matches in the PROD log. The DEV finding (httpx INFO logging prints the Pixabay key) cannot be confirmed or ruled out on PROD from this log — no Pixabay request was made in range. Re-check after the fix lands and before `/release`.
**New since last check:** nothing deployed. PROD is four sprints behind DEV (P12, P13, P13b, P14).

**Top issues:** unchanged — release backlog, no PROD error surface beyond the live log, service sleep vs. P17, misheard-caption candidate; plus the keys-in-logs decision carried from DEV.
**Stories opened:** none.
**Next check due:** before the release of P12–P14 to PROD.

---

## Prod check — 2026-10-04 (Sprint P13b review)
**Range:** the same live deployment as the 2026-10-03 check (v0.24.0, `edc92ba`). The log holds 359 lines and ends 2026-10-03 15:43 UTC — no traffic and no new container start since the previous check.

**Errors:** none. The only warnings are the five langgraph deprecation notices at start-up, the Railway config-as-code deprecation (existing files keep working until 2026-12-01), and the 2026-10-02 caption coverage warning already recorded below.
**Silent failures:** none seen. Still could not look at stuck runs in the database (PROD has no P12).
**Usage:** nothing new. P13b (CapCut export) is DEV-only, so PROD says nothing about it.
**New since last check:** nothing deployed. PROD is still two sprints behind DEV, now three with P13b.

**Top issues:** unchanged — release backlog (P12 + P13 + P13b), no PROD error surface beyond the live log, service sleep vs. P17, misheard-caption candidate.
**Stories opened:** none.
**Next check due:** before the release of P12 + P13 + P13b to PROD.

---

## Prod check — 2026-10-03
**Range:** 2026-10-02 13:16 UTC → 2026-10-03 15:49 UTC — the live deployment only (v0.24.0, `edc92ba`, Railway deployment `bafcc504`). First check on this project; nothing earlier was read.

**Errors:** none. No 5xx, no tracebacks; five container starts, each with migrations and checkpointer setup reported ok. The only non-200 responses were 401 on the auth-gated health / version routes, 404 on `/favicon.ico`, and 404 on a run's manifest before acquisition.

**Degraded path:** one `StoryboardWorker: coverage check failed` warning (run `70a93548`): the Deepgram transcript reads "pedals are wheel" where the script says "pedals or wheel", and the storyboard was produced anyway. Captions take their words from the same timestamps, so the wrong word probably reached the rendered video — not confirmed against the file.

**Silent failures:** none seen in the logs — every background task that was enqueued (6 voice, 2 storyboard, 2 render) logged completion. **Could not look:** stuck runs in the database (before P12 a Studio run has no reliable `runs` row, and PROD does not have P12), and anything before 2026-10-02.

**Usage:** 3 runs in two days, 2 rendered to a final video (render 22s and 30s). Voice was generated 6 times across the 3 runs (3×, 2× and 1×), so narration is regenerated often. 16 scene edits on the storyboard. Run `597e4d62` stopped after voice at the end of the range.

**New since last check:** first check.
- PROD is two sprints behind DEV: P12 and P13, including migration `0002_projects_shortlist.sql`, are not released.
- The service sleeps after 6–10 idle minutes (deployment status `SLEEPING`). Pipeline work runs as in-process background tasks, so this is harmless while the browser polls and will stop a server-side Auto Advance run with the tab closed (P17).

**Top issues:**
1. No error surface beyond the live deployment's log; no way to list stuck runs on PROD until P12 is released.
2. Service sleeping vs. P17 — recorded in the P17 outline (BACKLOG_ACTIVE.md, EPIC 48).
3. Misheard caption word — candidate story, not opened: show the coverage warning in Studio's Storyboard stage, or take caption words from the script and only the timing from Deepgram.

**Stories opened:** none. Items 1 and 2 are carried in SPRINT.md "Open items"; item 3 awaits the operator's decision.
**Next check due:** before the release of P12 + P13 to PROD.
