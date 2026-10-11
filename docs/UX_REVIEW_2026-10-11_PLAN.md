# Plan — from the 2026-10-11 UI/UX review

**Source:** [UX_REVIEW_2026-10-11.md](UX_REVIEW_2026-10-11.md) (C1–C34). **Status:** APPROVED by the operator 2026-10-11 (scope, C19, C26 key rules, C32). Entered in BACKLOG_ACTIVE.md,
SPRINT.md, DECISIONS.md (D109). Sprint order changed to reach the **friends beta** first — see §3.

## 1. Findings grouped into epics

| Epic | Theme | Items |
|------|-------|-------|
| **A. Pipeline flow & polish** | Every step starts its own work and ends with Next; New Run modal is minimal; shell polish | C1, C2, C4, C5, C6–C11, C12–C14, C15–C17, C18, C20–C22, C28, C29, C33, C34 |
| **B. Visual source model & project assets** | Look vs image source; lock after storyboard; channel identity; reusable project characters | C19, C23, C24 (C18 ties in) |
| **C. Integrations v2** | Grouped blocks, several providers per block with a default, model choice | C25, C26, C27 |
| **D. Accounts, limits, payments** | Google sign-in, per-user limits and usage accounting, payments | C30, C31, C32 |

## 2. Proposed sprints

### P-UX4 — Pipeline flow and polish (Epic A, ~21 pts)

Human touchpoint: create a run from the new minimal modal and walk all five steps using only **Next**,
including switching Script mode after uploading a voiceover and generating a new voice over it.

| ID | Story | Covers | Pts |
|----|-------|--------|-----|
| UX4-S1 | Shell polish: remove burger, dropdown chevron padding, sidebar icon + persistent collapse state, remove divider above step buttons, storyboard uses standard content width | C1, C11, C17, C29, C33, C34 | 3 |
| UX4-S2 | New Run modal: Title, Language, Format, Style (Realistic/Animated) + "Add master visual prompt" sub-modal; no hint text; one "change later in Run Settings" note | C2, C4, C5 | 3 |
| UX4-S3 | Script step: "Generate from idea" first and collapsible, hidden in Paste mode; From-voiceover unchanged; ends with **Next** | C6–C10 | 3 |
| UX4-S4 | Voiceover step: pace and tone options live here; generate always allowed — an uploaded voiceover is a replaceable current asset, not a run type that blocks generation; Regenerate + Next | C12, C13, C14 | 5 |
| UX4-S5 | Storyboard step: note "parameters come from Run Settings"; warning that style is locked after generation; scene card layout (Merge with next bottom-right) | C15, C16, C18 | 2 |
| UX4-S6 | Video step: caption on/off + style at top, single source of truth shared with Run Settings; Render / Download for CapCut then Next | C20, C21, C22 | 3 |
| UX4-S7 | Library files named after the run title (display and download name) | C28 | 2 |

Order: S1 → S2 → S3 → S4 → S5 → S6; S7 independent. Risk: S4 touches `voice_source` (D106) — needs a
DECISIONS entry; "storyboard re-run invalidates assets" rule (memory) already exists for S5.

### P-PROJ1 — Visual source model and project-level settings (Epic B, ~13–16 pts)

Human touchpoint: set a channel identity and save a character in Project Settings; a new animated run's
storyboard reuses that character and the metadata reads in the channel's voice.

| ID | Story | Covers | Pts |
|----|-------|--------|-----|
| PROJ1-S1 | Split `visual_mode` into **look** (realistic / animated) and **image source** (stock / AI-generated); image source in Run Settings; locked after storyboard generation with an explicit "reset storyboard" | C19, C18 | 5 |
| PROJ1-S2 | Channel identity field in Project Settings, fed into metadata (description, tags) generation | C23 | 3 |
| PROJ1-S3 | Project assets: save characters/places at project level; promote a run asset to the project | C24 | 5 |
| PROJ1-S4 | Storyboard worker reads project assets and reuses them in the continuity bible | C24 | 3 |
| PROJ1-S5 | Realistic storyboard prompt v0.18: Visual Director method on the stock contract, Sonnet 5.5; side-by-side test v0.17 vs v0.18 on one real run before switching | C35 | 5 |

### P-INT1 — Integrations v2 (Epic C, ~13–16 pts)

Human touchpoint: add a second LLM provider with its own key, make it default, generate a script on it.

| ID | Story | Pts |
|----|-------|-----|
| INT1-S1 | Regroup Integrations into the five blocks | 2 |
| INT1-S2 | Provider-agnostic interface per block (LLM, TTS/transcription, image, stock, destination); today's providers wrapped as adapters | 5 |
| INT1-S3 | Multiple providers per block, own key each, one default, model per provider | 5 |
| INT1-S4 | Which provider/model a run used shown in run settings/cost log | 2 |

Open: key ownership (tenant vs user) — see D below; INT1 can ship at tenant level and move to per-user
once accounts exist.

### P-AUTH — Google sign-in and per-user accounts (Epic D, ~13 pts)

Pre-requisite: run `/audit` (never run; this sprint opens the platform to other people). Stories: Google
OAuth login and account creation, user ↔ tenant model, per-user keys and settings, roles (owner / member).

### P-BILL — Usage accounting, limits, payments (Epic D, ~16–21 pts)

Stories: complete usage ledger (video minutes, images, voice minutes, LLM tokens → one credit unit),
per-user credit balance and hard limits, "bring your own keys = no charge" mode, then the payment provider.
Recommended to split: **BILL-1** ledger + limits + manual top-up by the owner (usable right away with the
$10 colleague scenario), **BILL-2** online payments.

## 3. Order (revised to reach the friends beta first)

Operator goal: let acquaintances sign in with Google and make their first video of up to one minute.

`P-UX4 → /audit → P-AUTH → P-BILL-1 (credits, limits, manual top-up)  = FRIENDS BETA`
`→ P-PROJ1 → P-INT1 → P-BILL-2 (online payments) → P-LANG → P15 → P16 → P17`

Why: friends on the owner's keys need only login, accounts, and a credit limit; bring-your-own keys
(P-INT1), project assets (P-PROJ1) and payments are not on the shortest path. P-UX4 comes first because
first impressions depend on the flow the friends will click through. The `/audit` is a gate before opening
the platform to other people. Moving P-PROJ1 / P-LANG before the beta remains possible if preferred.

## 4. Recommendations on the open questions

**C19 — look vs image source.** Two independent settings. *Look* (realistic / animated) is the style the
prompts and master style use. *Image source* (stock / AI) decides which assets exist. Defaults: Realistic →
Stock, Animated → AI. All four combinations are valid: Realistic + AI (photoreal generated images),
Animated + Stock (works only where a stock source has illustrations — Pixabay yes, Pexels mostly no, so it
is a weaker path). Characters/places/continuity bible exist only when image source = AI. Both are locked once
a storyboard exists; unlocking = an explicit "reset storyboard" that clears assets (matches the existing
re-run warning).

**C32 — payments.** Start with **no payment provider**: BILL-1 gives credits the owner tops up by hand —
enough for friends and colleagues. For online payments choose between **Stripe Checkout** (prepaid credit
packs; most documentation, you handle VAT/tax) and a **merchant-of-record** such as Lemon Squeezy or Paddle
(takes the VAT/sales-tax burden, higher fee). If you will sell to customers in several countries, the
merchant-of-record is the simpler path; if it stays a small circle, manual top-ups are enough for a long
time. Prepaid credits, not subscriptions, also match your "$10 → 5 minutes of video" model.

## 5. Decisions taken (2026-10-11)

1. Scope approved. 2. Order revised as in §3 (beta first) — flagged to the operator. 3. Keys: project keys by
default, charged to the user's balance; a user's own key becomes their default automatically, with a
checkbox to keep the project default; with several own keys the user picks. 4. C19 as recommended.
5. C32: manual credits first, payment provider later.
