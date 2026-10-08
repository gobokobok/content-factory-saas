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
