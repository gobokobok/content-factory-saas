# Releases

PROD releases are cut by pushing a `v*.*.*` tag, which triggers
`.github/workflows/cd.yml` (`railway up --service content-factory-saas --detach`).
Newest first.

## v0.22.0 — 2026-08-27

**Shipped:**
- On-screen text overlay redesign (D074): fontsize 60 → 90, font switched from
  NotoSans-Bold to Montserrat Bold (Futura was rejected — commercial licence, no
  free source), and the static centred fade replaced by a 0.4s slide-in from
  off-screen left.
- Overlay wrap correctness (D075): a real render showed text running off the right
  edge — D074's `textwrap.wrap(width=22)` was a character-count guess. Replaced with
  a greedy word-wrap measuring real glyph widths via `PIL.ImageFont.getlength()`
  against the bundled font. Box is now flush-left, 30% from the top, white@0.55 with
  black text.
- Font bundling (D075): `assets/fonts/Montserrat-Bold.ttf` (Google Fonts, SIL OFL) is
  committed and `COPY`'d to `/usr/local/share/fonts/` in the Dockerfile instead of
  resolved via the `fonts-montserrat` apt package, so the Python wrap measurement and
  ffmpeg's `drawtext` read identical font bytes.
- TTS pace retune (D073): ~170–175 wpm target; D071's pause requirement is kept but
  energetic delivery restored between pauses (duration had drifted 13s → 19s and read
  as flat).
- Caption number spell-out (D073): purely-numeric caption tokens are spelled out for
  display only (`$15,000` → "fifteen thousand dollars", `90%` → "ninety percent").
  Applied to the joined Dialogue text, never to `WordTimestamp.word`, so
  scene-alignment and gap-filling against the verbatim script are unaffected. No new
  dependency.
- Still deferred: the reference design's left-to-right opacity gradient on the overlay
  box — needs a composited image layer and a `filter_complex` restructure of the
  current single-pass `-vf` chain.

**Range:** `v0.21.0..d2308fb` — 4 commits (2 code, 2 RELEASES.md docs), 9 files,
+487/−38. Full suite green (2066 passed), ruff clean.

**Migrations:** none.

**Build risk:** first release to change the `Dockerfile` (font bundling). Because
`cd.yml` uses `railway up --detach`, a failed image build will NOT turn the workflow
red — confirm the Railway build log and the running service, not just the tag run.

**PROD verified:** pending — see the note on v0.21.0; no PROD base URL is recorded in
this repo and the local Railway CLI is broken, so endpoint verification
(`/platform/health`, `/platform/version`, one render path) is an operator step.

**Rollback:** deleting the tag does not un-deploy. Roll forward: tag the previous good
commit as `v0.22.1` and push, since the CD workflow deploys tags.

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
un-deploy. Roll forward instead: tag the previous good commit (`4250c2e`, tagged `v0.20.0`) as `v0.21.1` and push, since the CD workflow deploys tags.
