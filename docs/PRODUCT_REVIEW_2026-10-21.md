# Product review — 2026-10-21

Written at the backlog grooming that followed P-AUTH, P-CORE and the P-BILL-1 build. It reads the repository (SPRINT.md, BACKLOG_ACTIVE.md, DONE.md, the code behind each new request); it does not read DEV or PROD. Where a claim rests on something not seen, it says so.

## 1. Where the product stands

- A signed-in friend can write or paste a script, pick a named voice and characters, get an animated storyboard, generate images, render and download (P-LITE, smoke passed). The owner has the whole Studio in the same design (P-CORE, smoke partial).
- Accounts, isolation, deny-by-default gating, caps and moderation are on DEV (P-AUTH, smoke partial: only the owner's sign-in was tried).
- Billing — ledger, credits, holds, 402, owner top-up, the Creator's balance — is **built on `claude/p-bill-1`, not merged, never run on DEV** (3393 tests, 17 against a real Postgres). `BILLING_ENABLED` is off.
- Open smokes: **1 DEFERRED** (P-BILL-1) and **2 PARTIAL** (AUTH-S10, P-CORE-S11). All three belong to P-BILL-1 and none is clearing yet. The "friends beta" opens when they are done.

## 2. What is strong

- The delivery rules hold: every sprint has a smoke list, gates are server-side with snapshot tests, isolation has its own suite, billing was reviewed and fixed before merge (one close per hold, debit and entry in one transaction, a mutation check on the refund guard).
- Cost is bounded in layers (per-run image cap, per-tenant daily USD, per-tenant credits, render slots), so a bug costs money slowly rather than quickly.
- The animation path is already shaped for the next features: the Visual Director writes a `motion_note` per scene, scenes have `asset_strategy` / `asset_tier`, the image side is behind an `ImageProvider` interface with a price table, and the renderer already places video clips on a timeline.

## 3. Risks, most serious first

| # | Risk | Evidence | What to do |
|---|------|----------|-----------|
| 1 | **People can be charged for nothing, or locked out while having spent nothing.** | BILL-F2: several paths settle, then do work that can fail (script, metadata, single image, director 409). BILL-F1: a refund gives credits back but not the day's USD reservation, so a tenant whose actions fail reaches `CAP_DAILY_SPEND_USD` at zero spend. Both were left out of the PR review fix on purpose and sit at the bottom of BACKLOG_ACTIVE.md as `backlog`. | Raise both to **high** and make them a gate for `BILLING_ENABLED`. A friend who is charged for a failed video does not come back. |
| 2 | **Personal data is already collected with no privacy notice and no way to delete it.** | Google sign-in stores name, e-mail and `sub`; `prompt_log` stores users' prompts; scripts, voices and images sit in R2. `terms.html` is 3 KB ("Before you start"). SECURITY.md and the backlog contain no GDPR line; the P-BILL-2 stub says only "legal pages … at the latest". The feature the beta is built around is a bedtime story, so minors are plausible users. | Split the legal work: a **minimum before the beta** (privacy notice, terms rewrite, sub-processor list, a written erasure procedure) and the full set in P-BILL-2. See LEGAL-S1. |
| 3 | **The money path has never met a real provider.** | P-BILL-1 handover, "Not verified": no provider called, no DEV run, the real credits per video unseen. LLM and voice are charged at flat estimates, not actual tokens or characters. The image price table is keyed by model only, while the real price depends on resolution; CLAUDE.md already records that published videos need `IMAGE_RESOLUTION=2K` and a 0.03 entry, so today's estimate is low by a third for those. | The P-BILL-1 smoke, then the markup check against one real video. PLAT-S1 fixes the price key. |
| 4 | **Work lives inside the web process.** | Background jobs are FastAPI `BackgroundTasks` / `asyncio` tasks; renders run FFmpeg in the same container behind `RENDER_MAX_CONCURRENT=2`; a restart loses running jobs and leaves holds open until the owner presses "Give back stuck holds"; Auto-advance runs in the browser tab; PROD sleeps when idle. This is fine for a friends beta and cannot carry 100 people, or an API caller that closes its connection. | SCALE-S1 measures first; SCALE-S2..S4 move jobs and renders out of the web process. Gate `SIGNUP_OPEN` on the load test, not on a date. |
| 5 | **Provider quotas, not our code, may be the first ceiling.** | Every Basic account shares the owner's keys (Gemini TTS, kie.ai, Anthropic, Deepgram). Their rate limits at 100 concurrent users are not recorded anywhere in the repository. | SCALE-S1 asks each provider for its limits and records them in `docs/PERF.md`. |
| 6 | **There is no way to tell whether a prompt change is better.** | The v0.17 vs v0.18 storyboard side-by-side was never run; the default never switched. Style paths (Manga, Documentary) multiply this problem. | STYLE-S1 builds a small evaluation harness before any new path. |
| 7 | **The operator-action list is long and old.** | AUTH-S0 (`PROD_URL`), the first restore drill (F1), Pixabay key rotation, the female voice, `IMAGE_RESOLUTION=2K`. None blocks DEV; several block "real users". | Listed in CLAUDE.md; consider doing the three that are 5-minute jobs in one sitting. |

Not a risk, by choice: PROD stays on v0.24.0 until DEV is complete and smoke tested.

## 4. Your requests against what exists

| Request | Status in the repository | Where it went |
|---------|-------------------------|---------------|
| Add a payment method | P-BILL-2 stub only ("Stripe vs a merchant of record") | **BILL2-S1..S3** (EPIC 59) |
| Terms of use and GDPR | A 3 KB terms page and a terms-acceptance row (AUTH-S9). No privacy notice, retention, export or deletion | **LEGAL-S1** (before the beta), **BILL2-S4..S7** |
| Platform setting for the image model, costs follow | Half built: the owner already picks a provider and model per tenant in Integrations, and Basic accounts use the owner's choice (`resolve_image_config`). Missing: a plain platform-level setting, and a price that follows model **and resolution** everywhere | **PLAT-S1** (EPIC 61) |
| Pre-generated 5 s samples per voice on Cloudflare | Half built: `/platform/creator/voice-samples/{voice}` stores a sample in R2 after the first request. Not seen why a click still takes 5–10 s: either the first request per voice is what you hear, or the stored-file check fails quietly (it is wrapped in `except Exception: pass`) and the sample is re-made each time | **PLAT-S2** (EPIC 61): measure, pre-generate at deploy, serve the file |
| Platform API for n8n | New. P16 is the other direction (n8n pulls finished videos to publish) and P17 (server-side Auto Advance) is its prerequisite | **EPIC 63** (API-S1..S6) |
| Animated video with real motion (first/last frame + motion prompt) | New. The director's `motion_note` and the video-clip render path exist; the generation, provider, timing and pricing do not | **EPIC 64** (MOTION-S1..S7) |
| Speed, 100 users, later 1000 | New as a story set. Only the old May page-load fix exists (`docs/PERF.md`) | **EPIC 62** (SCALE-S1..S5) |
| Multiple paths by style | New | **EPIC 65** (STYLE-S1..S5), unplaced, for later analysis |
| A photo of yourself as a character's reference, kept in the master style (added later the same day) | New. Characters are text only today and the image providers take no input image; reference images were deferred in D108 | **EPIC 66** (REF-S1..S4); spike in P-PLAT, build in P-REF |
| Custom-trained LLM for Manga | A question, not a story | Section 6 below; recorded in STYLE-S1 |

## 5. Suggested order and gates

1. **P-BILL-1 close-out**: merge, AUTH-S10, P-CORE-S11, the scoped `/audit`, the P-BILL-1 smoke, **plus BILL-F1, BILL-F2 and LEGAL-S1**, then `BILLING_ENABLED=true` — the beta opens.
2. **P-PLAT** (~15, new): PLAT-S1, PLAT-S2, SCALE-S1 (measure), MOTION-S1 and REF-S1 (the two model spikes). All small, and the last three settle numbers the later sprints need.
3. **P-BILL-2** (~16, was ~8; ~20 if subscription plans are chosen): payments, full legal.
4. **P-REF** (~12): character reference photos (EPIC 66). A face photo is personal data, so it follows LEGAL-S1 and, for self-service deletion and export, BILL2-S5/S6. It is the most visible user feature on the list; if you want it sooner, run it with `CHARACTER_PHOTOS_ENABLED` open to Super only.
5. **P-SCALE1** (~16): durable jobs, render workers, the load test. **Gate: `SIGNUP_OPEN` stays unset until the load test passes at the agreed number of users.**
6. **P-LANG** (unchanged, tbd).
7. **P17 + P-API** (~10 + ~16, ~13 without webhooks): server-side Auto Advance, then the API on top of it. P16 (publishing) pairs naturally with these.
8. **P-MOTION** (~21, plus the 2-point spike in P-PLAT).
9. **P15** Research.

Steps 4, 6, 7 and 8 are the judgement calls: P-LANG was set ahead of everything on 2026-10-11; if the API and real motion are worth more to you now, they can move ahead of it. The order above keeps the earlier decision.

## 6. Custom-trained model for Manga — recommendation (log only, not for now)

Short answer: **do not train a model yet; build the thing that tells you whether training would help.**

1. **Most of "manga-ness" is not in the director model.** The look comes from the image model (line work, screentone, character consistency) and the motion comes from the renderer (panel moves, reveals). The director LLM decides shot grammar and pacing. Training the LLM fixes the smallest of the three.
2. **Use the cheap levers first, in this order**: a per-path director prompt with a written style bible; 6–10 annotated exemplars in the prompt (prompt-cached, so the cost stays low); a retrieval set of short "storytelling pattern" cards (reveal beats, reaction shots, pacing) pulled per script segment; an evaluation harness (fixed scripts, a rubric, side-by-side scoring) so each change is measured. Only if these plateau, consider fine-tuning.
3. **Fine-tuning the Claude models**: availability has been narrow (historically a small Claude model on Amazon Bedrock). Check what is offered when this is picked up; do not plan around it. The alternative is an open-weight model with LoRA, which needs a few thousand good script→storyboard pairs and usually loses to Sonnet on long structured output. It is worth it only if per-call cost becomes the problem.
4. **Training data is a legal question before it is a technical one.** Training on commercial manga is a copyright and licensing risk (the EU text-and-data-mining exception can be opted out of, and publishers do). Prefer craft notes written by a person, public-domain or licensed works, or commissioned examples. Avoid naming living artists in style prompts. Get legal advice before any training on third-party works.
5. **Start collecting the signal now, cheaply**: for each run, keep the director's storyboard next to the version the user finally rendered. That edit history is the best training and evaluation data this product will ever have — and it needs a line in the terms and privacy notice (LEGAL-S1 includes it).

## 7. Decisions needed from you

1. **Subscription or credit packs?** You wrote "basic subscription". Today's design (D114, D123) is prepaid credits. Plans with a monthly fee change the payment provider choice (recurring billing, failed-payment handling) and the P-BILL-2 size.
2. **Image model**: chosen by the owner for everybody (Basic included), or does Super choose per project / run? And "OpenAI" means which model — `gpt-image-1` direct, or `gpt-image-2` through kie.ai?
3. **Legal minimum before the beta**: agree it moves ahead of P-BILL-2 (LEGAL-S1)? Also: who is the seller and data controller (company, sole trader)? The terms, the privacy notice and the VAT treatment all need it, and the repository cannot answer it.
4. **Order of P-LANG vs P-MOTION vs the API** (section 5).
5. **API shape**: is `script` required, or may a caller send an idea and a length and let the platform write the script? And should the platform call back (webhook) when a video is done, or is polling enough for n8n?
6. **Real motion and cost**: cost per scene is much higher than a still. Default off, with a run toggle and per scene opt-in — agreed?
7. **Face photos (EPIC 66)**: portrait-first (one stylised portrait you approve, then used for the scenes) is my recommendation over sending the photo with every scene — agreed? Open to Basic or Super first? Are photos of children allowed at launch (bedtime stories make it likely)? The safe default is no, until you have legal advice.

I am not a lawyer. Every legal story ends with a human review of the final text.
