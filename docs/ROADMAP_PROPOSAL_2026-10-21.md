# Roadmap proposal — every backlog item placed (2026-10-21)

Companion to `docs/PRODUCT_REVIEW_2026-10-21.md`. Points are grooming estimates; refine at `/start-story`. Every sprint names what a person can touch at its end (D019). Nothing here is decided until the operator says so; the order of sprints 5–9 is the operator's call.

## Sprints

| # | Sprint | Pts | Stories | A person can touch |
|---|--------|-----|---------|--------------------|
| 1 | **P-BILL-1 close-out** (current) | 9 new + smokes | Merge the PR; AUTH-S0 (operator); AUTH-S10 (1); P-CORE-S11 (1); P-BILL-1 smoke; **BILL-F1** (2); **BILL-F2** (3); **LEGAL-S1** (4); scoped `/audit`; then `BILLING_ENABLED=true` | A friend is charged for a video, refused with a clear message when short, and reads a privacy notice. **Beta opens.** |
| 2 | **P-PLAT** | 15 | PLAT-S1 image model + price that follows it (5); PLAT-S2 instant voice samples (3); SCALE-S1 measure (3); MOTION-S1 spike (2); REF-S1 spike (2) | The owner picks the image model and every price follows; Listen plays in under a second; three written spike reports |
| 3 | **P-BILL-2** | 18 (22 with plans) | BILL2-S1 provider + checkout (4); S2 payment method and receipts (3); S4 consumer terms (2); S5 data export (3); S6 account deletion (3); S7 storage statement + AI disclosure (1); BILL-F4 gate the unbilled paid calls (2); S3 subscription plans (4, only if chosen) | A friend buys credits, sees the receipt, exports their data and deletes their account |
| 4 | **P-REF** | 12 | REF-S2 upload, storage, consent (4); REF-S3 reference-aware images + portrait (5); REF-S4 interface (3) | A user attaches their photo to a character; the video keeps their features in the master style |
| 5 | **P-SCALE1** | 11 | SCALE-S2 durable job queue (5); SCALE-S3 render workers (5); AUTH-F1 session purge (1) | Kill the server during a render: the job resumes and no credits are stranded; the user sees their place in the render queue |
| 6 | **P-SCALE2** | 17 | SCALE-S4 web tier and data path (3); SCALE-S5 provider backpressure (3); E54-S1 chunked voiceover (5); BILL-F3 token-accurate settling (3); SEC-S1 audit leftovers (3); fresh `/audit` | The load test at the agreed user count passes; a long script's voice is made in parallel. **`SIGNUP_OPEN` may be considered.** |
| 7 | **P-LANG** (EPIC 53) | ~13 | LANG-S1 script and storyboard prompts take a language (3); S2 voice per language, duration calibration, voice samples per language (2); S3 uploaded voiceover and Cyrillic word handling (2); S4 Cyrillic fonts in render, golden case, CapCut (3); S5 metadata in the language (1); S6 language shown in the interface (2) | A Russian run renders with Russian voice, captions and on-screen text |
| 8 | **P17** server-side Auto Advance (EPIC 48) | ~10 | P17-S1 confirm the server pipeline writes the same artifacts as the stage-by-stage flow (2); S2 which stages may run unattended and where it stops (2); S3 Auto Advance runs on the job queue (4); S4 keep the service awake while a run is active (1); S5 OpenAI direct as image fallback (D096) (1) | Start a run, close the tab, come back to a finished video |
| 9 | **P-API** (EPIC 63) | 16 (13 without webhooks) | API-S1 keys (3); S2 create video (5); S3 status + download (2); S4 reference lists + OpenAPI (1); S5 webhooks (3, if chosen); S6 docs + n8n example (2); scoped `/audit` | n8n makes a finished video and downloads it |
| 10 | **P-MOTION** (EPIC 64) | 19 + INT2-S1 | INT2-S1 settle the Integrations shape first (about 5, to size); MOTION-S2 `VideoProvider` (3); S3 director motion prompt + frames (4); S4 clip job, billing, caps (5); S5 render and CapCut with clips (4); S6 interface (3). Follow-up: S7 open to Basic (2) | A run with Motion on renders AI clips instead of camera moves on stills |
| 11 | **P16** publishing via n8n (EPIC 47) | ~10 | P16-S1 channels and per-run destinations (3); S2 `due` / `claim` / `result` endpoints and n8n key (3); S3 n8n YouTube workflow committed (2); S4 publish status in the Metadata step (2). Needs the Google API audit | Set a channel and time on a run; it appears on YouTube with its status in the interface |
| 12 | **P15** research (EPIC 46) | ~18 | P15-S1 trend research: existing adapters plus Google News (6); S2 competitor research ported from `content-researcher` (8); S3 tick results into the shortlist with evidence (2); S4 language and region (2). Open: X.com needs a paid-source decision | Run trend and competitor research in a project and tick results into the shortlist |

Reviews: `/sprint-review` is due when P-BILL-1 closes, then every two sprints. Audits: scoped `/audit` at sprint 1; fresh `/audit` in sprint 6 (before public sign-up, after payments and photos exist); a scoped one at sprint 9 for the API.

## Not in a sprint

| Item | Status | Suggestion |
|------|--------|-----------|
| EPIC 65: STYLE-S1 evaluation harness (5), S2 style pack registry (5), S3 Documentary (3), S4 Movie (3), S5 Manga (8) | unplaced, analysis only | S1 when a second style is wanted or a prompt change needs measuring; it also runs the never-run v0.17 vs v0.18 comparison. S2 before any new style pack. S5 only after S1's evidence |
| E50-S1 word anchors (5), S2 click-a-word interface (3), S3 curated SFX library (5) | low | Sound effects are off by default; wait until users ask |
| P8-S7 vision media scorer (3) | low | Delete at the next grooming unless someone asks; the beta runs on AI images |
| INT2-S1 Integrations rework | candidate | Placed as the first item of P-MOTION; it also holds the own-key exemption (D123 point 4) |
| INT1-S6 move script, storyboard and fact-check workers onto `LLMClient` | candidate | When a second thinking-model provider is wanted |
| Library "use in a scene", long-form animation | unplaced | Keep; not asked for by users yet |
| Attach a project asset to an existing run's bible | candidate | Low; take it if users keep asking |
| Delete the pre-P12 import, `pipeline.html` and legacy routes | candidate | Small cleanup (2); do it in sprint 6 with the audit |
| Captions take words from the Deepgram transcript (misheard word reaches the video) | candidate | Covered for uploaded voiceovers by the transcript editor; generated voice is the exposed case. Revisit with LANG-S3 |
| "Suggest prompt" button for a scene | **done** | Built as "Write with the director" in P-LITE (`write-prompt`); delete the candidate |
| Character reference image (D108 deferral) | **now EPIC 66** | Sprint 4 |
| Parked by D099: P11-S2 motion presets, P11-S3 sub-scene asset timeline, format tracks, analytics and attribution | parked | Leave parked; P11-S2 overlaps MOTION |

## Operator actions (not stories)

- AUTH-S0: set the `PROD_URL` GitHub variable; record the first restore drill in `docs/RUNBOOK.md` (F1).
- Choose the female Creator voice and set `CREATOR_VOICE_FEMALE`.
- Rotate the Pixabay key on DEV; check the DEV log for `key=REDACTED`.
- Set `IMAGE_RESOLUTION=2K` and the Nano Banana price to 0.03 until PLAT-S1 removes the need.
- Google API audit application (needed for P16, long lead time).
- Choose the seller and controller details (LEGAL-S1, BILL2-S1) and the payment provider.
- PROD release stays your call.

## Decisions waiting

Listed in the review, section 7: subscription vs credit packs; the scope of the image-model setting; legal minimum before the beta; the order of sprints 7–10; the API's request shape and webhooks; real motion's default; face-photo route, audience and children's photos.
