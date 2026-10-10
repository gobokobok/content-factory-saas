# UX audit — today's flow and comparable tools

_Story P-UX3-S1 · drafted 2026-10-07 · closed 2026-10-11 · section 1 is the operator's feedback from six review rounds and the DEV smoke test (see below)_

**How this was made.** The current flow was audited by reading the page sources (`src/static/projects.html`, `project.html`, `settings.html`, `studio-v2.html`), the platform routes and the P12–P14b handovers. It was **not** walked live on DEV; the operator's walkthrough of the prototype is where that happens. The tool review is from public product pages and help centres (sources in section 4), summarised in our own words; none of the tools were used hands-on for this audit.

---

## 1. The operator's pain points

**Source.** The operator did not write a separate list; what they find hard was collected from what they said while reviewing the prototype (rounds 1–5, 2026-10-07, `REVIEW.md`) and while smoke-testing the built UI on DEV (round 6, 2026-10-10). Each row is their wording, shortened, tied to the screen it was about. Anything they did not say is not here: **which pages still feel "too crowded" was never named**, and nothing was recorded about the login page, Research or Publishing.

| # | Pain point | Screen | Became |
|---|-----------|--------|--------|
| P1 | The way into a run is chosen once, at creation: a run cannot start from a script and take a voiceover later, or the reverse | New run dialog, Studio | One five-step pipeline; the Script step chooses the source (D105) |
| P2 | Replacing an uploaded voiceover with a generated voice must not happen silently | Studio, Voice | Confirmation naming what is replaced and discarded |
| P3 | The new storyboard was missing on-screen text and sound effects, which must be definable, changeable and removable | Storyboard | Fields on the scene card |
| P4 | An action sits at the opposite side of the row from the thing it acts on (Edit on the right, the asset on the left) | Storyboard scene | Pencil on the asset |
| P5 | On-screen text must be an editable field, not text behind a button | Storyboard scene | Inline field |
| P6 | Pages are a little too crowded | several, not named | Fewer facts per row (round 1); remains open |
| P7 | Too little space between the left panel and the content, tables and fields sit too close; today's DEV spacing is the reference | every page | 72 px gutter |
| P8 | Breadcrumbs belong on the page background and must scroll with it; more air above and below them | every page | Crumbs on the page, 36 px each side |
| P9 | A line under the pipeline is noise; the pipeline should look like the one in policy-scout | Studio head | Arrow steps, one status dot |
| P10 | Changing a still from Stock image to Upload image and then picking another motion left a second, trembling motion on top | Storyboard scene, render | Zoom shake fixed in the renderer (D107) |
| P11 | A 16:9 pan moves in visible steps | render | Sub-pixel pans with a minimum travel (D107) |

---

What the operator has already asked for (2026-10-07), recorded as requirements rather than pain points:

| # | Request |
|---|---------|
| R1 | Primary flow: enter the portal → create or select a project → (if new) set it up → create an idea → start a run from the idea → run settings → the complete pipeline |
| R2 | A run can be started without an idea; the details are entered directly in the run |
| R3 | A left panel that is visible and foldable on every screen |
| R4 | The panel lists Projects, Libraries and Settings |
| R5 | Libraries are tenant-wide: Videos (all rendered), Audios (all voiceovers created or uploaded), Footage (all acquired images and videos), AI generations (all AI images). Every asset shows the run, the project and an asset ID, and can be downloaded |
| R6 | Tenant settings hold cross-project configuration: API keys and models for every service (Pixabay, Deepgram, Claude, …), defined once and used by projects and runs |

---

## 2. The current flow, screen by screen

Friction points are numbered `F#` and each names what it was observed in.

### 2.1 Login (`/login`)
A single password form. No friction found.

### 2.2 Project list (`/`)

What it does: lists projects (name, niche, run count); "+ New project" opens an inline form with name and niche.

| # | Friction | Observed in |
|---|----------|-------------|
| F1 | **No persistent navigation.** The top bar holds only "Settings" and "Log out". Every page rebuilds its own header, and the way back is a text link ("← All projects") | `projects.html`, `project.html`, `settings.html` each carry their own top bar and back link |
| F2 | **A new project asks for name and niche only.** Language, aspect ratio and entry mode are not asked, so the first run starts on defaults the operator did not choose | `projects.html` new-project form; `POST /platform/projects` body is `{name, niche}` |
| F3 | **A project row says nothing about its state** beyond a run count: no last activity, nothing in progress, nothing failed | `renderProjects()` |

### 2.3 Project page (`/project?id=`)

What it does: one column with a hidden settings form, the shortlist of ideas, the list of runs, and a bar pinned to the bottom when ideas are ticked.

| # | Friction | Observed in |
|---|----------|-------------|
| F4 | **A run cannot start without an idea.** The only way to create a run is to tick shortlist ideas; the empty state says so. The API requires at least one idea | `RunFromShortlistRequest.item_ids` has `min_length=1`; contradicts R2 |
| F5 | **The two choices that shape a run are unlabeled dropdowns in a bottom bar.** Language and entry mode (generated or uploaded voice) appear only after ticking an idea, with a tooltip as the only explanation | `#run-language`, `#voice-source` in `.select-bar` |
| F6 | **Project settings are a hidden form on the same page**, opened by a small "Settings" button that sits one row below the tenant "Settings" link in the top bar. Two different things carry the same word | `toggleSettings()`; top-bar link to `/settings` |
| F7 | **The project's default language cannot be set.** New runs read `project.config.language`, but the settings form has no language field | `loadProject()` reads it; `saveSettings()` never writes it |
| F8 | **An idea cannot be edited**, only added or removed | no `PATCH` route for shortlist items |
| F9 | **A run row shows name, short ID, date and a four-value status.** Entry mode, language, the stage it is at, and whether a video exists are missing; there is no filter or search | `renderRuns()` |
| F10 | **Ideas and runs share one long column.** With a real shortlist the runs are below the fold, and the page is the only place both live | page layout, `max-width: 820px` |
| F11 | **Discovery has no home.** P15 (research) will add idea discovery and market analysis; the page has nowhere to put it except above the shortlist | page layout; P15 outline |

### 2.4 Studio — the run (`/studio#run/<id>/<stage>`)

What it does: a stage track across the top and one pane per stage. Generated voice: Settings → Script → Voice → Storyboard → Video → Metadata. Uploaded voice: Settings → Upload → Transcript → Storyboard → Video → Metadata.

| # | Friction | Observed in |
|---|----------|-------------|
| F12 | **Run settings are stage 1 of the pipeline**, so they read as a step that is finished and left behind. Aspect ratio must be right before acquisition, but nothing on later stages shows what was chosen or that changing it now costs a re-acquire | `pane-settings`; memory note "Run Settings UI — aspect ratio placement" |
| F13 | **The idea is typed up to three times.** It comes from the shortlist, is asked again as "Subject" in Settings, and again as "Idea" (plus "Niche", which the project already has) in the Script stage's Generate panel | `#settings-subject`, `#gen-idea`, `#gen-niche` |
| F14 | **Options have no consistent place.** Settings mixes a format choice, a file upload (music), a toggle with a dependent dropdown (captions) and two narration dropdowns. Script hides generation behind a collapsible panel. The scene edit dialog stacks three different actions (re-acquire with a new query, upload, AI generate) | `pane-settings`, `generate-toggle`, `#pencil-modal` |
| F15 | **Two render paths are three equal buttons.** "Render Video", "Download for CapCut" and "Upload video from CapCut" sit in one row, with a paragraph underneath explaining the CapCut path | `#render-cta`, `#capcut-hint` |
| F16 | **A placeholder option is on screen.** Visual style offers "Realistic" and a disabled "Animated — Soon" | `pane-settings` |
| F17 | **Regenerating the storyboard invalidates acquired assets**, and the operator has to know that | memory note "Storyboard re-run warning"; P14b added a discard marker for re-upload only |
| F18 | **Run facts are in a side panel behind "Details"** (created, aspect ratio, cost, project, ideas), not in the header | `#info-panel` |
| F19 | **Studio has its own run list** (the pre-P12 landing) next to the per-project run list | `#run-list` in `studio-v2.html` |
| F20 | **Music is uploaded per run.** There is a shared music library in storage and an SFX library endpoint, but the run asks for a file each time | `#music-dropzone`; `GET /platform/studio/sfx-library` |
| F21 | **Tenant Settings is not reachable from a run.** It is linked from the project pages only, so a missing image key found while generating means leaving the run | P14 handover: "linked from the project pages" |

### 2.5 Settings (`/settings`)

What it does: one card — AI image provider, model, API key.

| # | Friction | Observed in |
|---|----------|-------------|
| F22 | **One service of about eight is configurable.** Claude, the TTS provider, Deepgram, Pexels, Pixabay, Freesound and Replicate keys and models are Railway variables; changing one is a deploy-side action | `settings.html`; `ENV.md`; open item "rotate the Pixabay key" needs Railway access |
| F23 | **The back link always goes to "All projects"**, whichever page the operator came from | `.back` in `settings.html` |
| F24 | **No defaults at tenant level.** Language, aspect ratio and caption style exist per project and per run only | `tenant_settings` holds the image provider only |

### 2.6 Across screens

| # | Friction | Observed in |
|---|----------|-------------|
| F25 | **Nothing can be found across runs.** A rendered video, a voiceover or an acquired clip is reachable only by opening its run and the right stage. Replaced AI images stay in storage with no way to see them | P14 handover "a replaced AI image stays in R2"; no tenant-wide listing route |
| F26 | **Four pages, four copies of the styles and header.** The settings page's stylesheet still carries the comment "Project list". A navigation change means editing every file; Studio is one 189 KB file | page sources |
| F27 | **`docs/UI_GUIDELINES.md` describes a UI that no longer exists** (dark theme, `index.html` and `run.html`); the pages follow an unwritten "Monochrome Console" token set instead | guideline file vs. page sources |

---

## 3. Comparable tools

Seven products, each read for four questions: how work is structured, how ideation feeds production, how a multi-step pipeline with options is presented, and where settings and assets live.

| Tool | Structure of work | Ideation → production | Pipeline and options | Settings and assets |
|------|-------------------|-----------------------|----------------------|---------------------|
| **Opus Clip** | A project is created per source video and holds the clips cut from it; folders group projects in a workspace | None — starts from an existing long video | One submission, then a list of results to refine; options are picked up front as a brand template | Brand templates and a media/asset library at workspace level, reused by every project |
| **InVideo AI** | A flat list of videos in a workspace | A single prompt box is the entry point; no separate idea stage | After the prompt it asks a short series of questions (platform → sets aspect ratio, audience, look and feel), then produces a full draft; edits happen afterwards, by command or in an editor | Stock library built in; platform choice sets the format rather than a raw aspect-ratio field |
| **Pictory** | "My Projects" list; one project per video | Starts from a script, an idea, a URL or a recording — several entry modes on one start screen | A fixed left-to-right sequence of tabs (script → storyboard → visuals → audio → branding → export); the storyboard is the hub, and each scene can be split, reordered or have its visual replaced | Brand kits defined once and applied per project; own uploads kept in a library |
| **Descript** | Drive → workspaces → projects → compositions (versions of one piece inside a project) | None — starts from a recording | An editor, not a pipeline; the transcript is the editing surface | A drive-level Media Library: upload once, organise in folders, filter by type, add to any project. A project also has its own panel of everything used in it |
| **CapCut (web)** | A space holds drafts (projects) and cloud assets; team spaces for sharing | "Script to video" as one of several start tiles | An editor; the AI tools produce a draft that opens in it | Cloud storage per space for video, audio and images, separate from drafts |
| **vidIQ** | Organised around the channel, not around projects | The clearest ideation chain: daily ideas for the channel → keyword scores (volume, competition) → generate title, outline and script from the chosen idea; ideas can be saved for later | Each generator is a single form with a result to revise | Channel connection is the main setting |
| **Synthesia / HeyGen** | Left sidebar with projects/folders; one project per video | Start from a prompt, a document or a template | A scene-based editor; per-scene controls in a side panel | "Assets" in the left sidebar with Library and Brand kits; workspace settings hold members, API keys and integrations |

### What the review shows

1. **A persistent left sidebar with work, assets and settings as three groups** is the common shell (Synthesia, HeyGen, Descript, CapCut). The operator's R3–R4 is the mainstream pattern, not an unusual one.
2. **A tenant-level library next to a per-project view of the same assets** (Descript) answers "where is that clip" without opening a run. Pictory and Opus Clip have the library; Descript adds the two views.
3. **Reusable defaults are defined once and applied per project** — brand kits and templates in four of the seven. The equivalent here is tenant defaults → project settings → run.
4. **Several entry modes are presented as a choice on one start screen** (Pictory, CapCut), each with a line saying what it needs. None hides the choice in a dropdown.
5. **Ideation feeds production through a saved idea** (vidIQ): the idea carries its evidence, and "create from this" is one action on the idea. No tool forces an idea first; the prompt box (InVideo) is the idea-less path.
6. **Questions before a run are few and outcome-worded** (InVideo: "which platform", not "which aspect ratio"). Everything else has a default and is changed afterwards.
7. **The storyboard is the hub of a scripted pipeline** (Pictory): per-scene edits happen on the scene, global choices in tabs around it.
8. **No tool reviewed exposes third-party API keys to the user**, because they bundle the services. Bring-your-own-key is specific to this product; the nearest pattern is a workspace "Integrations" or "API" page, separate from creative defaults.

---

## 4. Patterns to adopt, mistakes to avoid

### Adopt

| # | Pattern | Traced to |
|---|---------|-----------|
| A1 | One shell: a foldable left panel with Projects, Libraries, Settings, present on every screen | F1, F23, F26 · finding 1 · R3, R4 |
| A2 | The open project expands in the panel (Overview, Ideas, Runs, Settings), so pages replace the single long column and P15/P16 get a slot | F10, F11 · finding 1 |
| A3 | "New run" is one dialog reachable from an idea or on its own: title, entry mode as labelled cards, language, format | F4, F5, F13 · findings 4, 5, 6 · R2 |
| A4 | Run settings are a panel available from every step, with the run's key facts (mode, language, format) always in the header; a setting that can no longer change safely says what changing it costs | F12, F17, F18 · memory note on aspect ratio |
| A5 | One rule for step options: the few defaults inline, the rest under "Options", per-scene overrides on the scene | F14 · finding 7 |
| A6 | Settings inherit tenant → project → run; an overridden value is marked and can be reset | F7, F24 · finding 3 |
| A7 | Tenant "Integrations": every service's key and default model in one place; projects choose a provider, never a key | F21, F22 · finding 8 · R6 |
| A8 | Tenant-wide libraries by asset type, each asset labelled with project, run and ID, downloadable; the same assets filtered by project inside a project | F20, F25 · finding 2 · R5 |
| A9 | A render path is a choice between two described options, each with its own next steps | F15 · finding 4 |
| A10 | Lists show state: a project row shows what is in progress; a run row shows mode, language and the step it is at | F3, F9 |

### Avoid

| # | Mistake | Traced to |
|---|---------|-----------|
| M1 | A settings wall before first use. Ask the three or four things that shape a run; default the rest | F2 · finding 6 · the operator's step 3 |
| M2 | Asking for the same fact twice (idea, niche) | F13 |
| M3 | Showing options that do not exist yet | F16 |
| M4 | The same word for two scopes ("Settings" for tenant and project on one screen) | F6 |
| M5 | A second navigation competing with the pipeline: in a run, the left panel folds so the steps keep the width | F19 · finding 7 |
| M6 | An editor-style free canvas. The product is a pipeline with checkpoints; the tools that are editors (Descript, CapCut) solve a different problem, and CapCut is already the hand-off for that | finding 7; D100 |
| M7 | A library that is only an archive. Design the "use in a scene" action now even if it is built later | finding 2 |

---

## Sources

- Opus Clip — pricing and feature list: https://www.opus.pro/pricing
- InVideo AI — workflow walkthroughs: https://www.freevisuals.net/post/how-to-use-invideo-ai-the-complete-step-by-step-workflow-for-creators · https://primalvideo.com/guides/best-ai-video-generator-invideo-review/
- Pictory — academy guides: https://pictory.ai/academy/how-to-turn-an-idea-into-a-video-with-pictory-ai · https://pictory.ai/academy/how-to-create-training-videos-with-pictory-ai
- Descript — help centre: https://help.descript.com/hc/en-us/articles/13535123897485 (projects and compositions) · https://help.descript.com/hc/en-us/articles/43448763539213 (Media Library) · https://help.descript.com/descript-tour/drive-view
- CapCut — https://capcut.com/tools/media-asset-management · https://www.capcut.com/resource/collaborate-on-capcut-online/
- vidIQ — https://vidiq.com/ai-script-generator/ · https://vidiq.com/blog/post/5-challenges-youtube-creators-face/
- Synthesia — https://docs.synthesia.io/docs/assets · https://help.synthesia.io/en/articles/9046610-how-do-i-create-a-synthesia-brand-kit
- HeyGen — https://community.heygen.com/public/resources/how-to-manage-projects-and-drafts-in-heygen
