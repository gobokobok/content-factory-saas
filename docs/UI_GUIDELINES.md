# Operator UI Guidelines — Content Factory

## Principles
- **Functional over decorative.** Operator needs information and controls, not aesthetics.
- **No frameworks.** Plain HTML + vanilla JS only.
- **Status at a glance.** Every run's step status visible without scrolling.
- **Fail loud.** Errors surface immediately, never hidden.

## Structure

### Pages
- `index.html` — run list, new run creation
- `run.html` — run detail: step status, controls, log viewer

### Served by
FastAPI static file mount: `GET /` → `src/static/index.html`

## Step status display

Each pipeline step is displayed as a row:

```
[Step Name]    [●  complete]    [Run ▶]
[Step Name]    [✕  failed  ]    [Retry ↺]   [▼ logs]
[Step Name]    [○  pending ]    [Run ▶]  (disabled if upstream not complete)
```

- Green dot = complete
- Red X = failed
- Grey circle = pending
- Run button disabled until all upstream steps are complete
- Retry button visible only on failed steps

## Log viewer
- Collapsible per step — closed by default, open on failed steps
- Content: `run_log.txt` section for that step
- Refreshes on the status poll interval (every 10 seconds)
- Monospace font, scroll within fixed height container

## Voiceover upload
- File picker: `.mp3` only
- Upload button enabled only after file selected
- Progress indicator during upload
- Clear confirmation message on success

## Run creation
- Single text input for slug
- Slug validation: lowercase, hyphens only, no spaces
- Real-time format hint below input
- Submit creates run and navigates to run detail page

## Color/style
- Dark background (#0f0f0f or similar)
- Monospace or technical sans-serif font
- Status colors: green (#22c55e), red (#ef4444), grey (#6b7280)
- Minimal borders, no gradients, no animations
