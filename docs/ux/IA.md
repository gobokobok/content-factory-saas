# Information architecture — project → idea → run, libraries, settings

_Story P-UX3-S2 · drafted 2026-10-07, revised after review round 1 · status: draft for the operator's review · prototype: `docs/ux/prototype/`_

Friction points (`F#`), patterns (`A#`, `M#`) and requests (`R#`) refer to `docs/ux/AUDIT.md`.

---

## 1. The primary flow

```
Enter the portal
  └─ Projects ── select a project ─────────────────────────────┐
        └─ New project (name, niche, language, format) ────────┤
                                                               ▼
                                                    Project · Overview
                                                     ├─ Ideas ── "Start run" on an idea ──┐
                                                     └─ "New run" (no idea) ──────────────┤
                                                                                          ▼
                                                              New run (title, brief, language, format)
                                                                                          ▼
                                        Run · Script → Voice → Storyboard → Video → Metadata
                                              +  Run settings (always available)
```

- A new project is one short form (M1). Everything not asked is inherited from the tenant defaults and is editable later under the project's Settings.
- A run starts from an idea **or** from nothing (R2, A3). Both paths open the same "New run" dialog; from an idea, the title and brief are prefilled.
- Every run follows one pipeline. Whether the script is generated, pasted or taken from an uploaded voiceover is chosen in the Script step (section 5).

## 2. The shell

One shell on every screen (A1): a left panel, a thin top bar with the breadcrumb, and the page.

```
┌────────────────────┬──────────────────────────────────────────────┐
│ CF Studio       «  │ Projects / The Housing Equation / Runs       │
│                    ├──────────────────────────────────────────────┤
│ PROJECTS           │                                              │
│  All projects      │                                              │
│  ▾ Housing Equation│                 page                         │
│     Overview       │                                              │
│     Ideas          │                                              │
│     Runs           │                                              │
│     Research  soon │                                              │
│     Publishing soon│                                              │
│     Settings       │                                              │
│                    │                                              │
│ LIBRARIES          │                                              │
│  Videos            │                                              │
│  Audio             │                                              │
│  Footage           │                                              │
│  AI generations    │                                              │
│  Music & SFX       │                                              │
│                    │                                              │
│ SETTINGS           │                                              │
│  Integrations      │                                              │
│  Defaults          │                                              │
│                    │                                              │
│ Log out            │                                              │
└────────────────────┴──────────────────────────────────────────────┘
```

| State | Behaviour |
|-------|-----------|
| Open | 240 px, labels and groups as above |
| Folded | 56 px icon rail; hovering an icon shows its label. The fold state is remembered per browser |
| In a run | Opens folded by default so the pipeline keeps the width (M5); unfolding it is one click and is not remembered as the general preference |
| Phone width | Hidden; a menu button in the top bar opens it as a drawer over the page |

The open project is the only one expanded in the panel. "Research" (P15) and "Publishing" (P16) are shown as planned entries in the **prototype only**, to agree their place; the build does not ship entries that do nothing (M3).

## 3. Page map

| Level | Page | Route (proposed) | Holds | Replaces |
|-------|------|------------------|-------|----------|
| Tenant | Projects | `/` | Project cards with state (runs in progress, last activity); New project | `projects.html` |
| Project | Overview | `/project/<id>` | Counts, runs that need attention, newest ideas, "New run" | top of `project.html` |
| Project | Ideas | `/project/<id>/ideas` | The shortlist: add, edit, remove, start a run from one or several | shortlist section |
| Project | Runs | `/project/<id>/runs` | All runs with mode, language, current step, status; filter | runs section |
| Project | Research _(P15)_ | `/project/<id>/research` | Trend and competitor research; results are ticked into Ideas with their evidence | — |
| Project | Publishing _(P16)_ | `/project/<id>/publishing` | Channel destinations and the schedule of this project's videos | — |
| Project | Settings | `/project/<id>/settings` | Name, niche, defaults for new runs, AI image look, default channel (P16) | hidden form in `project.html` |
| Run | Pipeline | `/run/<id>/<step>` | The five steps (Script → Voice → Storyboard → Video → Metadata); run facts in the header; Run settings panel | `studio-v2.html` |
| Tenant | Library · Videos | `/library/videos` | Every rendered or uploaded final video | — |
| Tenant | Library · Audio | `/library/audio` | Every generated or uploaded voiceover | — |
| Tenant | Library · Footage | `/library/footage` | Every acquired or operator-uploaded image and clip | — |
| Tenant | Library · AI generations | `/library/ai` | Every AI-generated image, including replaced ones | — |
| Tenant | Library · Music & SFX | `/library/music` | The shared music and SFX libraries | per-run music upload |
| Tenant | Settings · Integrations | `/settings/integrations` | One card per service: key state, default model | `settings.html` |
| Tenant | Settings · Defaults | `/settings/defaults` | Defaults every project inherits; spend caps | — |

An idea has no page of its own: it is a row in Ideas that expands to show its summary, source, evidence (P15) and the runs made from it.

### Libraries (R5)

- Every asset row shows a preview, the **asset ID**, the **project**, the **run**, its type-specific facts (duration, resolution, source, prompt) and the date, with **Download**.
- Filters: project, run, and a per-library facet (Footage: source and image/video; AI: provider; Audio: generated/uploaded).
- The project and run are links. Inside a project, the same library opens pre-filtered to that project.
- "Use in a scene" is designed (an action on a Footage or AI row that targets a scene of an open run) but is a later build story (M7).

### Where P15 and P16 attach

| Sprint | Attaches at | Notes |
|--------|-------------|-------|
| P15 Research | Project → Research; results flow into Project → Ideas | Research reads the project's language and region from project Settings. Competitor channel list lives in project Settings. |
| P16 Publishing | Tenant → Settings → Integrations (the n8n key and the channel list); Project → Settings (default channel); Run → Metadata step (destinations, publish time, status); Project → Publishing (schedule view) | Channels are tenant-level per the P16 outline. |
| P17 Auto Advance | Run header toggle; tenant Defaults (which steps may run unattended) | |
| EPIC 53 Russian | Language at tenant Defaults, project Settings, New run, run header | Already in the matrix below. |

## 4. Settings matrix

**Inheritance rule.** A value is resolved run → project → tenant → built-in default; the first one set wins. A level stores a value only when the operator sets it there, so changing a tenant default changes every project that has not overridden it. **A run is the exception: it copies its values at creation** and is not changed by later edits above it, so a finished run stays reproducible (D055).

**What the operator sees.** Every inheritable field shows where its value comes from: `Inherited from tenant: English`. Once changed, the field is marked `Overridden` with a "Reset" link that returns it to the inherited value. In a run, the header shows mode, language and format at all times; a run value that differs from the project default carries a dot in the Run settings panel.

| Setting | Tenant | Project | Run | Notes |
|---------|:------:|:-------:|:---:|-------|
| **API keys** (Claude, TTS, Deepgram, Pexels, Pixabay, Freesound, Replicate, kie.ai, OpenAI, n8n) | ● | — | — | Integrations. Never shown in full, never chosen below tenant level. Today only the image key is here; the rest are Railway variables, which stay as the fallback |
| **Default model per service** (script, storyboard, metadata, TTS, transcription, image) | ● | — | — | Integrations |
| **Image provider** | ● | ○ | — | Project may pick another configured provider |
| **Language** | ● default | ● default | ● | Asked at New project and New run. Per-run override is always allowed and **never locked by earlier runs**. Shown in the run header. Changeable in a run until a script or transcript exists |
| **Format (aspect ratio)** | ● default | ● default | ● | Asked at New run. Changing it after acquisition warns that assets must be re-acquired |
| **Script source** (generate / paste / from a voiceover) | — | ● usual source | ● | Chosen in the run's Script step, not at creation. The voice follows from it: a generated voice for a generated or pasted script, the recording itself for an uploaded one. It can be switched in the Voice step (see section 5) |
| **Niche** | — | ● | — | Passed to script generation; not asked again in the run (M2) |
| **Captions** on/off and style | ● default | ● default | ● | Changeable until render |
| **Narration** pace and style | — | ● default | ● | Generated mode only |
| **TTS voice** | ● default | ○ | ○ | Today a Railway variable |
| **Visual style** | — | ○ | ○ | One value today ("Realistic"); the field is not shown until there is a second (M3) |
| **AI image look** (style prefix) | — | ● | — | Per-scene prompt is the override |
| **AI image spend cap per run** | ● | ○ | — | Today a Railway variable |
| **Music** | — | ○ default track | ● | Picked from Library · Music & SFX; upload adds to the library |
| **SFX** | — | — | per scene | From the library |
| **Channel** _(P16)_ | ● list | ● default | ● destinations | |
| **Auto-advance** | ○ allowed steps _(P17)_ | — | ● toggle | |
| **Render path** (server render / CapCut) | — | — | ● at the Video step | Not a setting: chosen when rendering, and both can be used on one run |

● exists or is required there · ○ optional override, later · — not at this level

Platform limits (`VOICE_UPLOAD_MAX_MB`, timeouts, poll intervals) stay Railway variables and are not shown.

## 5. Pipeline-step options

**The rule (A5).** A step shows three layers, always in the same places:

1. **Defaults, inline** — at most three controls that most runs touch, already set from the run's settings. The step's primary action sits below them.
2. **Options** — a closed disclosure under the defaults for everything else. A changed option shows a count on the disclosure ("Options · 2 changed").
3. **Per-scene overrides** — on the scene, never in the step header. A scene that differs from the step's default is marked.

A step that would invalidate later work says so before it runs, naming what is lost (F17).

| Step | Defaults, inline | Options | Per-scene |
|------|------------------|---------|-----------|
| **Script** | The source, as three choices: **Generate** (brief, target length), **Paste**, **From a voiceover** (upload; language shown and changeable) | Generate only: niche override, narration style, model | — |
| **Voice** | Generated: voice, pace. Uploaded: the recording, with "Generate a voice from the script instead" | Generated: style, regenerate | — |
| **Storyboard** | Two views, **Storyboard** and **Script** (below); "Acquire assets" | Model, AI image spend, regenerate (warns what is discarded) | Asset type (stock / upload / AI), on-screen text, sound effect, split, merge; search words, AI prompt and motion in the scene panel |
| **Video** | Render path as two described choices: **Render here** or **Finish in CapCut** (download package → upload result) | Captions on/off and style, music track | — |
| **Metadata** | Generate; title, description, tags | Alternative titles, model | — |
| **Publish** _(P16)_ | Destinations and publish time | — | — |

**Run settings** leave the pipeline (F12): language and format are set in the New run dialog and stay available as a panel from every step.

### One pipeline, three script sources (operator, review round 1)

Every run has the same five steps. What differs is where the script comes from, and that is chosen in the Script step:

| Source | What the Script step holds | What the Voice step holds |
|--------|----------------------------|---------------------------|
| Generate | Free text, generated from the brief | A generated voice |
| Paste | Free text, pasted | A generated voice |
| From a voiceover | The transcript of the upload; edits are timing-safe (replace a word, one to several, several to one) because the audio is fixed | The recording itself |

Switching afterwards:

- **Uploaded → generated voice** (Voice step, "Generate a voice from the script instead"). The platform asks first: *the uploaded voiceover will be replaced by a generated voice; the storyboard and its acquired assets are discarded because the word timings change; the recording stays in Library · Audio.* After confirming, the script becomes free text.
- **A different source** (Script step, "Start again from a different source"). Asks first when a voice or storyboard exists, naming what is discarded.

### Storyboard: two views, and what a scene carries

Carried over from today's Studio (P13), restyled:

- **Storyboard view** — one card per scene: preview, time, asset type, the voiceover words, on-screen text and sound effect. **Click a word to split** the scene before it. **Merge** joins a scene with the next one and warns when the second scene's on-screen text or sound effect would be dropped. On-screen text can be added, changed or removed on the card; the sound effect is picked from Library · Music & SFX or removed.
- **Script view** — one paragraph per scene. Moving the blank lines moves the scene boundaries; "Apply boundaries" shows what changes first. The words themselves cannot be changed here.
- **Scene panel** ("Edit") — Stock / Upload / AI as tabs in place of three stacked sections (F14), plus motion.

## 6. Phone and desktop

| Screen | Phone width | Why |
|--------|:-----------:|-----|
| Projects, project Overview | must work | Checking state away from the desk |
| Ideas (add, start a run) | must work | Ideas arrive anywhere |
| New run, Script step (uploading a voiceover) | must work | Recording on the phone is the upload path's natural source |
| Run: step status, approve and continue, download the video | must work | Monitoring a run |
| Libraries: browse and download | must work | Getting a video onto the phone |
| Run: script word edits, storyboard scene editing | desktop first; readable on a phone, editing not optimised | Dense, pointer-driven |
| Settings · Integrations, Defaults; project Settings | desktop first; usable on a phone | Rare |

## 7. Backend and data-model changes

Listed, not assumed. Each becomes its own story in S4. "Verify" marks what was inferred from routes and handovers and needs checking against the code when the story is written.

| # | Change | Why | Size guess |
|---|--------|-----|-----------|
| B1 | **Run without an idea.** `POST /projects/{id}/runs` accepts no `item_ids` when a title (and optional brief) is given | R2, F4 | small |
| B2 | **Run creation takes format.** Aspect ratio is passed at creation and stored with the run instead of being seeded in the browser from `sessionStorage` | F12 | small |
| B3 | **Edit an idea.** `PATCH /projects/{id}/shortlist/{item_id}` | F8 | small |
| B4 | **Run list carries state.** `voice_source`, `language`, current step and "has video" on the run list response | F9, A10 | small; verify where step progress is derived today |
| B5 | **Project list carries state.** Runs in progress and last activity per project | F3 | small |
| B6 | **Project language and tenant defaults.** Write `config.language` from project Settings; a tenant defaults record (language, format, captions, spend cap); the resolve order of section 4 in one function | F7, F24, A6 | medium |
| B7 | **Integrations for every service.** Generalise `tenant_settings` and its resolve (tenant setting, then Railway variable) from the image provider to every key and default model; one `GET/PUT` per service | R6, F22 | medium–large; touches every client's key lookup |
| B8 | **Tenant-wide asset index.** A listing API per library with project, run and asset ID. Videos, voiceovers and scripts are artifacts indexed in Postgres per run (verify); footage sits in each run's manifest and AI images in each run's files and spend ledger, so they need either an index table written at acquisition/generation time or a backfill + write-through | R5, F25 | large; the biggest item |
| B9 | **Asset ID.** A stable, human-quotable ID per asset (verify what artifacts already have) | R5 | part of B8 |
| B10 | **Music from the library.** A run references a library track instead of uploading one | F20 | small–medium |
| B11 | **Use a library asset in a scene.** | M7 | medium; after B8 |
| B13 | **One pipeline; the voice source can change.** Today `voice_source` is fixed at run creation and selects one of two stage lists. The redesign sets it in the Script step and lets a run switch from the uploaded voiceover to a generated voice (discarding the storyboard, keeping the recording) or start the script again | Review round 1 | medium; verify what P14b's re-upload discard marker already covers |
| B12 | **Page routes.** `/project/<id>/…`, `/run/<id>/…`, `/library/…`, `/settings/…`, with redirects from `/project?id=`, `/studio#run/…` and `/settings` | A1 | small |

No change is needed for: language per run, the settings a run already stores, AI image generation, CapCut export.

## 8. Open questions for the review

1. **Idea ↔ run.** Today several ideas can be combined into one run. Kept in the prototype (tick several → "Start run"). Still wanted?
2. **Music & SFX as a fifth library** — added beyond R5. Keep?
3. **Videos library and CapCut.** A video uploaded back from CapCut and a server render of the same run are both listed, labelled by origin. Right?
4. **Project-level provider override** (image provider per project) — needed, or is tenant-level enough?
5. **Research and Publishing in the panel** — agreed places for P15 and P16?
