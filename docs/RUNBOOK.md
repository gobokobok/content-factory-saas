# Runbook — production checks

PROD is the Railway project `content-factory-saas-prod`, service `content-factory-saas`. The repository is linked to the DEV project, so PROD logs are read by passing the project, environment and service explicitly:

```bash
railway list --json          # project, environment and service ids
railway logs -p <prod project id> -e <environment id> -s <service id> -n 5000
```

`railway logs` shows the live deployment only. A release replaces it, so `/prod-check` runs before each `/release` (APEX-DEV, 2026-10-03).

Entries are newest first.

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
