# UI / UX Guideline — "Monochrome Console"

A portable design language, extracted from the Content Factory Studio (DEV, October 2026). Use it as the brief for any project that should look and feel the same: a web app, a personal-brand page, a slide deck.

**How to use:** give this file to Claude at the start of a project ("follow this guideline") and name the medium (app / page / slides). Sections 1–8 are the core. Section 9 adapts it to a landing page, section 10 to slides.

---

## 1. Character

Quiet, precise, tool-like. A light page, near-black ink, **one** blue accent, thin borders, generous space. It looks like a well-made instrument: nothing decorative, everything legible.

| Do | Don't |
|---|---|
| One accent colour, used for the thing to act on | Gradients, glows, drop-shadow stacks |
| Hairline borders and whitespace to group | Heavy dividers, boxed-in sections |
| Short sentences, plain words | Marketing voice, exclamation marks |
| Show state honestly (running, failed, done) | Hide errors, fake progress |

## 2. Principles

1. **Functional over decorative.** Every element gives information or a control.
2. **One thing at a time.** One column, one primary action per screen.
3. **Status at a glance.** The reader sees where they are and what is next without scrolling.
4. **Fail loud, and say what is safe.** An error says what failed and what was *not* lost, with a retry.
5. **Name the cost.** Before an action that spends money or discards work, say what it costs or loses and ask.
6. **Ask little, inherit the rest.** Forms ask only what shapes the result; everything else has a default that can be changed later.
7. **Chrome stays out of the way.** Navigation and tools are lighter than content.

## 3. Tokens

```css
:root{
  /* surface */
  --bg:#FAFAFA;          /* page, and also cards and fields: no white-on-grey */
  --bg-soft:#F0F0F2;     /* hover fill, chips, placeholders */
  /* lines */
  --border:#E7E7E9;
  --border-strong:#B4B4BA;
  /* ink */
  --text:#121215;
  --ink-sub:#55555C;
  --muted:#8B8B92;
  --faint:#B4B4BA;
  /* accent */
  --accent:#2743C9;
  --accent-h:#1D35A6;    /* hover */
  --accent-soft:#ECEFFB; /* selected / active fill */
  --accent-ring:rgba(39,67,201,.26); /* focus ring */
  /* semantic: use sparingly */
  --red:#D92D20;         /* errors only */
  --ok:#12805C;          /* only where "done" must be green (rare) */
  --warn:#E5A50A;        /* only where "in progress" must be amber (rare) */
  /* type */
  --font:'Schibsted Grotesk',system-ui,sans-serif;
  --mono:'Fragment Mono',ui-monospace,monospace;
  /* shape */
  --r:8px; --r-sm:6px; --r-pill:999px;
}
```

**Colour rules**
- Status without extra colours: **done = ink** (`--text`), **in progress = accent**, **not started = grey** (`--border-strong`), **failed = red**. Reach for green and amber only if the audience truly needs them.
- Accent means "this is interactive or current". Never use it as decoration.
- Error surface: border `#F3C7C3`, fill `#FEF1F0`, text `#8A1C13`.
- Dark mode (if needed): invert the ink and surface tokens, keep the accent hue, lighten it to ≈ `#6F86F5`; re-check contrast.

**Google Fonts:** `Schibsted+Grotesk:wght@400;500;600;700` and `Fragment+Mono`.

## 4. Typography

| Role | Size / weight | Notes |
|---|---|---|
| Page title (h1) | 24 / 700, `letter-spacing:-.02em`, line-height 1.25 | one per screen |
| Body | 14 / 400, line-height 1.5 | |
| Field label | 12 / 600, `--muted` | above the field |
| Button | 13 / 600 | |
| Meta, hints | 12–12.5 / 400–500, `--muted` | counts, facts, helper text |
| Section label | Mono 10, uppercase, `letter-spacing:.08em`, `--faint` | e.g. "RECENT", "LIBRARIES" |
| Numbers, times, IDs | Mono 10–11 | step numbers, durations, timecodes |

Body is `-webkit-font-smoothing:antialiased`. Tight negative tracking on headings only. No more than 3 sizes on one screen.

## 5. Layout

- **One working column**, 780 px max, centred on the viewport. Side panels *float over* the page (fixed, with a soft shadow) and never push the column.
- **Page padding:** 72 px top, 24 px sides, 120 px bottom. 16 px sides on a phone.
- **One vertical rhythm on every screen:** breadcrumb row → title row → **28 px** → content. After a step bar: **44 px**.
- **Spacing scale:** 4 · 6 · 8 · 12 · 16 · 20 · 28 · 44 · 72.
- **Footer of a step:** buttons on the **left**, counts and facts on the **right** (`margin-left:auto`), hint text fills the space between.
- **Top right:** icon-only toggles for settings / details / info. Information is rightmost and on every screen.
- **Breakpoints:** < 1100 px reduce the panel gutter; on a phone the left panel becomes a drawer.

## 6. Components

**Buttons** (38 px high; 30 px small), radius 6, 1 px border.
- *Primary* — filled accent, white text. The action that starts work. **One per screen.**
- *Next / continue* — outlined in accent, accent text; disabled until the step is done.
- *Default* — border only; hover: soft fill.
- When a button is disabled, say why in a hint beside it ("Add a voiceover first").

**Fields** — quiet: page background, 1 px `--border`, radius 10, padding 9×14, 13/500. Hover: `--border-strong`. Focus: accent border + 3 px `--accent-ring`. Textarea line-height 1.65.

**Inherited fields** — always show the source: "Inherited from Defaults: English"; once changed: "Overridden for this project" with a reset link.

**Cards, not rows.** Lists are cards: page background, 1 px border, radius 8, 8 px gap. Hover: darker border + `0 2px 8px rgba(18,18,21,.05)`. No rule lines between rows.

**Chips** — pill, 11.5/500, `--ink-sub` on `--bg-soft`, 1 px border. They show what is set (voice, format, language) — never actions.

**Segmented control** — pill container, active segment `--accent-soft` + accent text. **Switch** — 38×22, accent when on.

**Step bar** — N equal segments with a 3 px top border: current = accent, finished = ink, rest = grey; a mono step number above the label.

**Side panel** — 244 px (left, navigation) / 328 px (right, details). Nav item: 13/500, hover soft fill, active = `--accent-soft` + accent. Lighter, thinner (1.35 stroke) icons for panel chrome than for content.

**Modal** — 520 px max, radius 12, padding 22×24, shadow `0 16px 48px rgba(18,18,21,.16)`.

**Drop zone / empty state** — 1 px *dashed* `--border-strong`, radius 8, muted text that says what to do.

**Progress** — a 4 px bar on `--border`; long actions show a running line under the buttons.

**Icons** — outline, 1.5 stroke, 16–18 px, `currentColor`.

## 7. Interaction & states

- Transitions 120–150 ms, panels 220 ms `cubic-bezier(.4,0,.2,1)`. No bounce, no parallax.
- Hover is a border or fill change, never a movement (exception: a 2 px arrow nudge on list rows).
- Every action has four states: idle → running (line + disabled button) → done (quiet confirmation) → failed (red line: what failed, what is safe, Retry).
- Destructive or costly actions: say the cost or loss, ask once, then act. Never confirm harmless actions.
- Click on a card to open its settings inside it; a small icon on the corner for the secondary action.
- Cross-origin file downloads: fetch → blob URL → anchor (`download` is ignored cross-origin).

## 8. Copy

- Sentence case everywhere. Buttons are verbs: "Generate voiceover", "Add scene".
- Say the result, not the mechanism: "Voiceover ready · 0:42", not "Job 8f3 completed".
- Errors: *what failed* + *what is safe* + *what to do*. No blame, no codes in the headline.
- Empty states say the next action in one line.

---

## 9. Adapting to a personal-brand page

Same tokens, more air, more type.

- Column 720–780 px; hero title 40–56 px / 700, tracking −.03em; body 17–18 / 1.6.
- Structure: name + one-line positioning → 3 proof points (mono labels, big numbers) → selected work as **cards** → short about → one contact action.
- One primary button ("Get in touch"), repeated at most twice. Everything else is a text link in accent.
- Section labels in mono caps (`WORK`, `ABOUT`, `CONTACT`); sections separated by 96 px space, not lines.
- Photography: black-and-white or desaturated, rounded 8, never full-bleed collage. No sliders, no carousels, no animation on scroll beyond a 150 ms fade.
- Mobile first: single column, 16 px gutters, tap targets ≥ 44 px.

## 10. Adapting to slides (16:9)

- Canvas `--bg`, ink `--text`; accent only for **one** emphasised word, number or shape per slide.
- Title 40 / 700 left-aligned at the top; one idea per slide; ≤ 25 words of body.
- Left margin 96 px, content width ≤ 1100 px of 1920; lots of empty space on the right is fine.
- Numbers are the hero: 120+ px, bold, with a mono caption beneath (`REVENUE · Q3`).
- Lists become cards or a 3-column grid with 1 px borders; no bullets with custom icons.
- Diagrams: 1.5 px strokes, ink lines, accent for the path that matters, grey for context.
- Footer: mono 12 px, `--faint` — deck name left, page number right.
- Transitions: none or a plain fade.

## 11. Checklist before shipping

- [ ] One primary action on the screen, in accent, bottom-left of the step.
- [ ] Only one accent colour; red only on errors.
- [ ] Lists are cards; no stacked divider lines.
- [ ] Every disabled button explains itself.
- [ ] Every costly or destructive action names its cost and asks.
- [ ] Focus rings are visible; text contrast ≥ 4.5:1 (`--muted` only on `--bg`, 12 px+ semibold or larger for labels).
- [ ] Works at 375 px wide with no horizontal scroll.
- [ ] No gradients, no decorative shadows, no more than 3 text sizes.
