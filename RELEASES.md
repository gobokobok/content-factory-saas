# Releases

PROD releases are cut by pushing a `v*.*.*` tag, which triggers
`.github/workflows/cd.yml` (`railway up --service content-factory-saas --detach`).
Newest first.

## v0.23.1 — 2026-09-01

**Shipped:**
- **Operator video on a still scene no longer fails the render (D089).** A scene whose
  storyboard said `still_with_motion` while holding an operator-uploaded MP4 reached the
  still path, whose `-loop 1` is an image2-demuxer option; FFmpeg 7 rejects it on mov/mp4
  and **the whole render exits 1, not just that scene**. `_render_scene` now routes on
  file extension alone — the check already existed but guarded only the opposite
  direction (a JPEG on a `hard_cut` scene). The upload endpoint additionally re-derives
  the scene's `asset_tier` / `clip_type` / `motion_effect` from what was uploaded:
  `asset_tier` comes from scene *duration* at storyboard time, and nothing re-derived it
  when the operator overruled that guess by hand. Motion effects being stills-only is now
  enforced in the data — an effect on a video scene is cleared rather than ignored at
  render time — so the Studio table and the render can no longer disagree.

## v0.23.0 — 2026-08-31

**Shipped:**
- **Curated SFX library (D076, D078, D080):** 8-entry controlled vocabulary suggested
  per scene by the storyboard prompt and overridable in Studio; copied into the run and
  auto-timed at render. Freesound auto-seeding was rejected on a listening pass, so
  `scripts/upload_sfx.py` provides a manual path (D078). The Studio dropdown now always
  reflects the scene's stored value, synthesizing an `(unavailable)` option when the
  library fetch fails (D080).
- **CD waits for the Railway build (D077):** `railway up --ci` replaces `--detach`, so a
  failed image build now turns the workflow red instead of green. `build_info.json` is
  stamped before upload and `GET /platform/version` reads it, replacing a `git rev-parse`
  that could never work inside the image.
- **OST left margin restored (D079):** flush-to-edge text was clipped by the real Shorts
  player; a 60px safe-title margin now matches the right side.
- **Sprint P-UX2 — render & narration controls (D081–D083):** a shared `.cf-select`
  dropdown component; a Punch caption preset (one uppercase word at a time); a real
  per-scene motion-effect vocabulary; and operator-selectable narration pace and
  register. **`motion_effect` had never reached the render script at all** — the filter
  returned early on `clip_type` before reading it — and was absent from
  `_PATCHABLE_FIELDS`, so it could not be edited either.
- **Punch captions use Barlow Condensed Bold (D084):** chosen on measured width —
  "CHAMPIONSHIP" sets 765px against Titillium's 1008px at matched cap height, and 960px
  is all that fits between the margins, so the outgoing face wrapped long words.
- **Settings persistence fixed (D085):** every run load POSTed the defaults back to the
  server, racing the GET meant to restore them, so operator settings were lost on reload.
- **Artifact versions resolved numerically (D086) — the significant one.**
  `sorted(keys)[-1]` is a string sort, so `@v9.json` ranks above `@v10.json`. **Once any
  artifact passed nine versions, every reader silently pinned to v9 and no later edit was
  ever seen again** — not by the operator, the patch endpoint, or the renderer. Present
  since the artifact store landed (D055) and invisible below ten versions.
- **Motion presets are per-second rates (D087):** Ken Burns spread a fixed 5% across the
  clip, so on a 0.56s scene it zoomed at 8.9%/s — faster than a `zoom_in` the operator had
  explicitly chosen. All presets now share one speed model.
- **Narration tempo split from register (D088):** the `educational` clause read "measured
  and articulate", a slow-down instruction sitting beside a speed-up one; fast delivered
  126 wpm against normal's 139. Register now describes voice only. `fast` 172 → 190 wpm.

**Range:** `v0.22.0..307313f` — 14 commits, 41 files, +3475/−202. Full suite green
(2205 passed), ruff clean. CI verified on the tagged commit itself.

**Migrations:** none.

**Behaviour changes PROD operators will notice:**
- **Narration is slower by default.** The default pace is `normal` (160 wpm) where 9:16
  previously ran the D073 ~172. Choose **Fast** to get the old pace. 16:9, which received
  no narration instruction at all before, now gets one.
- **Every still scene moves less.** A 3.5s scene now pushes 3.5% where it pushed 5%
  (D087). D081's byte-identity guarantee with the old default is explicitly withdrawn.
- Studio settings now persist across reloads, which changes what a returning operator sees.

**Build risk:** the `Dockerfile` changes again (`BarlowCondensed-Bold.ttf`). Unlike
v0.22.0 this is now genuinely gated — D077's `--ci` means a failed image build turns the
tag run red. The same layer built twice on DEV.

**PROD verified:** _pending._

**Known gap to check on PROD:** the SFX code ships, but `sfx-library/*.mp3` lives in the
bucket, not the image. If the PROD bucket has never been seeded, scenes with an SFX
selected will silently render without it (`_copy_sfx_to_run` logs and continues). If it
*was* seeded from the rejected Freesound batch, PROD will mix in audio the operator turned
down — see the unresolved D080 follow-up. Neither state could be checked from here: the
local `.env.local` holds DEV credentials only.

**Rollback:** deleting the tag does not un-deploy. Roll forward: tag the previous good
commit as `v0.23.1` and push, since the CD workflow deploys tags.

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

**PROD verified:** operator supplied the container startup log (2026-08-27 15:36:09,
~7 min after the tag run). Image built — so the new `COPY assets/fonts/*.ttf` layer
resolved — and the service is up: `Startup OK — environment=prod`,
`cf_platform migrations: ok`, `cf_platform checkpointer setup: ok`, uvicorn listening
on 0.0.0.0:8000, no errors. Font wiring confirmed by inspection: `_OST_FONTFILE`
(`/usr/local/share/fonts/Montserrat-Bold.ttf`) is the exact Dockerfile COPY target and
is passed to drawtext as an absolute path, so fontconfig is not a dependency (and
`fc-cache -f` runs regardless). NOT yet exercised: a real 9:16 render with a long
on-screen-text string, which is what would prove the D075 wrap against the deployed
image rather than the local checkout.

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
