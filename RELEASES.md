# Releases

PROD releases are cut by pushing a `v*.*.*` tag, which triggers
`.github/workflows/cd.yml` (`railway up --service content-factory-saas --detach`).
Newest first.

## v0.21.0 — 2026-08-27

**Shipped:**
- Shorts captions and voice: caption restyle scoped to 9:16 only; caption size cut
  108pt → 80pt after verifying against a real render; position, line-spacing and
  TTS pacing/pauses corrected (D070, D071, D072).
- On-screen text editing: clearing on-screen text now actually clears it (no stale
  `render_options` overlay, no coercion back to `"stat"`); `on_screen_text_type` is
  sanitized before render validation so a bad value no longer fails the render.
- Studio robustness: a trace-event write failure no longer 500s an otherwise
  successful upload/reacquire.
- Security: constant-time password comparison and per-IP login rate limiting.
- Script generator: VO word-count budget aligned to 160 wpm.
- Internal: API split into per-domain routers (D069); runtime/dev dependency split
  with version caps and a ruff lint gate in CI (D067, D068); README rewritten with
  Studio walkthrough screenshots; personal Telegram chat id and DEV deployment URL
  scrubbed from docs and tests.

**Range:** `v0.20.0..75ec309` — 15 commits, 166 files, +4206/−3314.

**Migrations:** none.

**PROD verified:** CD workflow run 33053414379 succeeded. `railway up` runs with
`--detach`, so the workflow going green only proves the deploy was accepted, not
that the build finished — endpoint verification against PROD (`/platform/health`,
`/platform/version`, one render path) is the operator check that closes this out.

**Rollback:** `git tag -d v0.21.0 && git push --delete origin v0.21.0` does **not**
un-deploy. Roll forward instead: tag the previous good commit (`v0.20.0` →
`0d7ee49`-era HEAD) as `v0.21.1` and push, since the CD workflow deploys tags.
