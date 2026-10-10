# Prototype review log

_Story P-UX3-S3 · prototype: `docs/ux/prototype/` · served at `/prototype/` (behind login) · locally: preview config `ux-prototype`, or open `index.html`_

Each round records what the operator said, the decision, and what changed. The operator's pain points with **today's** UI go into `AUDIT.md` section 1, not here.

## How to walk it

Everything is demo data held in memory; reloading the page resets it. Buttons that would call the backend show a "Demo: …" message instead.

| # | Path | What to judge |
|---|------|---------------|
| 1 | Projects → **+ New project** → create | Are these four questions the right ones for a new project? |
| 2 | In the new (empty) project → **+ New run** with no idea | Starting a run without an idea |
| 3 | The Housing Equation → **Ideas** → **Start run →** on one idea; then tick two ideas | Idea → run; combining ideas |
| 4 | In a run: the header, **Run settings**, the steps | Run facts always visible; settings as a panel instead of step 1 |
| 5 | A new run's Script step (three sources); a run from an uploaded voiceover (`r-27ab90`) → Voice → "Generate a voice instead" | One pipeline, three script sources; the replace warning |
| 6 | Storyboard: click a word, Merge, on-screen text, sound effect, the Script view, **Edit** on a scene | Scene controls; Stock / Upload / AI as tabs |
| 7 | Video step | The two render paths as a choice |
| 8 | The left panel: fold it, open a run (it folds itself), narrow the window to phone width | Panel behaviour |
| 9 | Libraries (all five), filter by project | Asset ID, project and run on every asset |
| 10 | Settings → Integrations and Defaults; then a project's Settings | Tenant → project → run inheritance and how an override is shown |

## Round 0 — self-check before the operator's review (2026-10-07)

Checked in the browser at desktop width and at 375 px: every route renders, the flows in rows 1–10 complete without script errors, and no page scrolls sideways at phone width. Three phone-width layout faults were found and fixed (run rows, the run header, the panel's shadow showing while closed).

Known limits of the prototype, by design:

- Storyboard scenes, the script and the transcript are the same demo content for every run.
- Thumbnails are colour blocks, not images; nothing plays or downloads.
- "Research" (P15) and "Publishing" (P16) are placeholders to agree their position; the build will not ship empty entries.
- "Use" on a library asset is shown but is a later build story.

## Round 1 — operator review (2026-10-07)

Overall: liked. The run was the biggest gap to what exists today.

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Some pages are a little too crowded | Accepted. Which pages still feel crowded is open — the operator did not name them | Lists show fewer facts (run rows: voice, language, format and one status; idea rows: source and run count only when present; project rows: one state and the run count). Run header drops cost, ID and auto-advance (cost and ID are in Run settings). Project Overview drops the Discovery placeholder. New project and New run ask one thing fewer. Wider margins and more space between rows |
| 2 | A run starts with the script, not necessarily with a voiceover upload. Script step: generate, paste, or take from a voiceover (the upload option then appears) | Accepted. One pipeline for every run: Script → Voice → Storyboard → Video → Metadata. The entry-mode choice leaves the New run dialog | Script step opens with three source choices; "From a voiceover" shows the upload and turns the transcript into the script, with timing-safe word edits. The separate Upload and Transcript steps are gone |
| 3 | The next step can still be a voice. If the script came from an uploaded voiceover, generating a voice must warn that the upload will be replaced and ask | Accepted | Voice step shows the recording for an uploaded run, with "Generate a voice from the script instead". It asks first, naming what is replaced and discarded, and says the recording stays in the Audio library |
| 4 | Storyboard looks more modern, liked. Missing: on-screen text and SFX, both definable, changeable and removable by the operator | Accepted | Each scene card carries its on-screen text (add, edit, remove) and sound effect (pick from the library, or none) |
| 5 | Missing: split a scene by selecting a word; merge scenes | Accepted — carried over from today's Studio | Click a word to split before it; "Merge" on every scene but the last, warning when text or SFX would be dropped |
| 6 | Today's DEV has two modes, "Storyboard" and "Script" — check them | Checked in `studio-v2.html` (today's labels: "Table" and "Script"). Script view is one paragraph per scene; moving the blank lines moves the boundaries; words cannot change there | Both views are in the prototype, labelled Storyboard and Script, with "Apply boundaries" and the same word-change guard |

Also carried into the scene panel from today's table: motion. Today's "Type" and "Query" columns are not on the card; search words are in the scene panel.

Backend consequence recorded in `IA.md` section 7 as B13: today the voice source is fixed at run creation.

## Round 2 — operator review (2026-10-07)

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Inside a run, the space between the left panel and the content is too small; keep today's DEV spacing | Accepted. Today's Studio uses 40 px side padding | Content sits 40 px from the panel on every screen |
| 2 | Breadcrumbs are good, but not as a separate top bar; put them on the page background | Accepted | The bar (white background and border) is removed; the breadcrumbs are the first line of the page |
| 3 | The scene's Edit button on the right is far from the asset on the left; put a pencil icon next to the asset | Accepted | A pencil on the corner of the asset preview opens the asset panel. Merge moved into the scene's tool row, so nothing sits apart on the right |
| 4 | On-screen text must be an editable field | Accepted | An inline field on the scene card: type to add or change, clear it to remove |

## Round 3 — operator review (2026-10-07)

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Still too little space between the left panel and the content; tables and fields sit too close | Accepted | Gutter widened from 40 px to 72 px (48 px on windows narrower than 1100 px, 16 px on a phone) |
| 2 | Breadcrumbs should move with the scroll | Accepted, read as: they scroll away with the page instead of staying pinned | The breadcrumbs are part of the scrolling page |
| 3 | More space above the breadcrumbs, and between the breadcrumbs and the page title | Accepted | 36 px above and 36 px below (was 18 and 22) |

## Round 4 — operator review (2026-10-07)

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Remove the horizontal line under the pipeline | Accepted | Removed |
| 2 | Use the pipeline visualisation from policy-scout (latest on its main branch) | Accepted. Read from `gobokobok/policy-scout` `main`: `src/app/templates/_run_head.html` and the `.steps` / `.step` rules in `src/app/static/app.css` (its D-037) | Arrow-shaped steps in one row, all one colour, the current step darker and bold, one status dot per step: grey not started, amber in progress, green completed, red failed. Colours use this product's tokens; the shape, states and dot are policy-scout's |

## Round 5 — operator review (2026-10-07)

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Looks nice; a bit more space between the pipeline and the tags above it | Accepted | 32 px (was 18) |
| 2 | Push to DEV; the operator will test there and report pain points | — | Prototype served at `/prototype/` on DEV |

## Round 6 — operator review on DEV (2026-10-10)

The built UI was walked on DEV by the operator against the ten-step smoke list. Everything worked as intended; the remaining items of the list were closed by the operator without notes.

| # | Feedback | Decision | Change made |
|---|----------|----------|-------------|
| 1 | Switching a scene from Stock image (with Ken Burns) to Upload image and then choosing another motion leaves a second motion on top, which looks weird | Investigated on the operator's run: the stored motion and the render script matched every selection, and a Static scene does not move. What does exist is a shake in every zoom (0.6 px off a smooth path, 2.4 px jumps between frames), which reads as a second motion; the operator confirmed it on a Zoom out | The picture is enlarged four times before `zoompan` (`a199b76`, D107). Operator re-test of the fix: not yet done |
| 2 | In 16:9, Pan left / Pan right moves in steps | The operator's stills (2752×1536) have 15 px of spare width in a 1920×1080 frame, so a pan moved one pixel every six frames | Pans are drawn at four times the size, so they move in quarter pixels, and always have 10 % of the width to travel (`58f361e`, D107). Operator confirmed: "pans left right work" |
| 3 | Other smoke items | Closed by the operator | — |
