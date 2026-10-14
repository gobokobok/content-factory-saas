# Operator UI Guidelines — Content Factory

Rewritten 2026-10-08 (D105). The earlier version described the legacy `index.html` / `run.html` UI.

## Principles
- **Functional over decorative.** The operator needs information and controls.
- **No frameworks.** Plain HTML + vanilla JS only (CLAUDE.md hard constraint).
- **Status at a glance.** A run's step status is visible without scrolling.
- **Fail loud.** Errors surface immediately, never hidden.
- **Ask little, inherit the rest.** A form asks the few things that shape the result; everything else comes from Settings → Defaults, then the project, and can be changed later.
- **Name what a change costs.** Before an action discards work (regenerating a storyboard, replacing an uploaded voiceover, changing a format after acquisition), say what is lost and ask.

## Structure
- **Shell** (`src/static/ui/shell.js`, `shell.css`): one foldable left panel — Projects, Libraries (Videos, Audio, Footage, AI generations, Music & SFX), Settings (Integrations, Defaults); the open project expands to Overview / Ideas / Runs / Settings. Breadcrumbs sit on the page background (no bar), scroll with the page, and are the first line of every page. The panel starts folded in a run; on a phone it is a drawer.
- **Shared styles** (`ui/app.css`): tokens and components for the project, library and settings pages. Studio keeps its own stylesheet and uses only `ui/shell.css`.
- **Pages:** `/` projects · `/project?id=&tab=` overview, ideas, runs, settings · `/studio#run/<id>/<step>` the run · `/library?kind=` · `/settings?tab=integrations|defaults` · `/legacy` the old pipeline UI.
- **Spacing:** 72 px between the panel and the content (48 px under 1100 px wide, 16 px on a phone); 36 px above the breadcrumbs and between them and the title.

## The run
- Five steps in one row of arrow-shaped blocks, all one colour, the current one darker, one status dot each: grey not started, amber in progress or next, green done, red failed. No rule under them.
- Run facts as chips under the title: voice, language, format, where the run is.
- **Run settings** are a drawer available from every step, not a step.
- **Options rule for a step:** the few defaults inline, the rest under "Options", per-scene overrides on the scene.
- **Storyboard:** one card per scene — asset with a pencil on its corner, voiceover words (click one to split), asset type, on-screen text as an inline field (empty removes it), sound effect, "Merge with next". Two views: Storyboard and Script (one paragraph per scene; moving the blank lines moves the boundaries).

## The Creator pages (`/create`, D117)
The simplified flow for beta users. Its design is the reviewed mockup `docs/mockups/studio-beta-ui.html`; when the two disagree, the mockup is the reference for layout and D114 / D117 for scope. Files: `src/static/creator.html` (markup and styles), `src/static/ui/creator.js`.
- **Layout.** The working column (780 px) is centred on the screen. The left panel (244 px) and the right panel (328 px) float over the page and never push the column; only on a window too narrow to keep it centred does an open panel push it. A collapsed left panel disappears completely — only its expand button stays, top left.
- **One rhythm on every screen:** breadcrumb row, title row, 28 px, content. On a run the step bar is the first content and the step's own content starts 44 px below it.
- **Steps** are a four-segment bar across the column: the current segment in the accent, finished ones in ink, the rest grey.
- **Top right, three separate icons:** settings, details, information. Information is rightmost and on every screen; the other two only inside a run. One panel shows one of them; clicking outside closes it.
- **Buttons sit on the left** of a step's footer; counts and other facts sit on the right. The action that starts work is a filled accent button; "Next →" is outlined in the accent and disabled until the step is done.
- **Lists are cards**, not rows with rules between them: page background, one border, rounded corners.
- **A scene card** is short: the image fills its height with a pencil in the corner; scene number, time range (bold) and duration (accent); the voiceover; small chips for what is set (characters, on-screen text, motion). Clicking the card opens its settings inside it; the pencil opens the image dialog.
- **Fields are quiet:** rounded, a light border, the page background.
- **Colour:** the DEV tokens with a deeper accent `#2743C9`. No green or amber: done is ink, in progress is the accent, red is for errors only.
- **Long actions** show a running line under the buttons; a failure is a red line that says what failed and what is safe, with Retry. An action that costs money shows the estimate and asks first; one that discards work says what is lost and asks first.

## Settings fields
Every inheritable field shows where its value comes from ("Inherited from Settings → Defaults: English") and, once changed, "Overridden for this project" with a reset link.

## Color/style
- Light "Monochrome Console": background #FAFAFA, surfaces white, ink #121215, one accent #2E45EC; green #12805C, amber #E5A50A for in-progress, red #D92D20 for errors only.
- Schibsted Grotesk and Fragment Mono. Minimal borders, no gradients.

## File downloads

**Never use `<a href="..." download="filename">` for cross-origin URLs.** The `download` attribute is silently ignored when the `href` points to a different origin (presigned R2 URLs). Fetch the file, make a blob URL and click an anchor made for it:

```js
async function downloadFile(btn, url, filename) {
  const label = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Downloading…';
  try {
    const blob = await fetch(url).then(r => r.blob());
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
  } catch (e) { alert('Download failed: ' + e.message); }
  finally { btn.disabled = false; btn.textContent = label; }
}
```
This applies to every rendered video, voiceover, library asset and any artifact served by a presigned URL.


## One application page (P-CORE, D121)

`/create` is the only application page. Super-only screens are drawn by `ui/core.js` (Projects, project, Libraries, Integrations, Defaults) and run controls by `ui/core-run.js`; they are loaded only for an effective Super session, so a Basic page never contains them. A new Super feature is a screen or a control there, using the page's tokens and classes (`.btn`, `.field`, `.run-item`, `.core-card`). The server gates every call; hiding a control is not protection. File downloads still go through a blob (see "File downloads").
