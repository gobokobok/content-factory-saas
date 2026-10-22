# Content Factory: portfolio description

Draft text for LinkedIn and Upwork. Figures are taken from the repository on 2026-10-21 (commit history, test suite, DECISIONS.md, SECURITY.md). Anything not in the repo is marked as "your input".

---

## 1. LinkedIn: project entry (short, fits the "Projects" or "Featured" section)

**Content Factory: an AI video production platform (solo build, in production on DEV)**

I designed and built a platform that turns a topic into a finished vertical video. It finds trending ideas, writes and fact-checks a script, generates the voiceover, plans every scene against word-level timestamps, gets matching footage or AI images, and renders the final video with captions and music. A person approves each editorial decision along the way.

It started as a pipeline for a data-driven YouTube Shorts channel about American housing economics. It is now a multi-user product with Google sign-in, per-account isolation, prepaid credits and hard spend limits, so that other people can use it without being able to spend my API budget.

Stack: Python 3.11, FastAPI, LangGraph with a Postgres checkpointer, Claude API, Deepgram, ElevenLabs and Gemini TTS, kie.ai and OpenAI image generation, FFmpeg, Cloudflare R2, Postgres, Railway, GitHub Actions. Operator UI in plain HTML and JavaScript.

---

## 2. LinkedIn: post draft (in your voice, adjust freely)

I have spent the last five months building a video production pipeline, and the most useful lesson was not about AI.

The first version was a script that called a few APIs and ran FFmpeg. It worked. The problems started when I wanted anyone else to use it: one shared identity, no spend limits, and a failed voiceover that silently produced a bad video.

So most of the later work was ordinary engineering. Per-account isolation on the server, a credit ledger that places a hold before every paid call and refunds it if the call fails, start-up checks that refuse weak secrets, a restore procedure for the database, and a security audit with 23 findings that I fixed in priority order.

The AI parts are deliberately limited. Workers are pure functions, routing sits on the graph edges, and a human approves the script, the storyboard and the assets. A model never decides the next step on its own.

Current numbers: about 600 commits, around 3,400 automated tests, 120 written architecture decisions. The friends beta is the next step, after the live smoke tests.

The rule I kept: if you can draw the flowchart in advance, build it as a flow and use the model inside the steps.

---

## 3. Upwork: portfolio item

**Title:** AI Video Production Platform: topic to finished YouTube Short, with billing and multi-user accounts

**Role:** Sole developer, architect and product owner. Built with AI-assisted tooling under a documented engineering process.

**Duration:** May 2026 to present (about 5 months).

**The problem**
Producing a short, data-driven video takes hours of manual work: finding a topic, writing and checking the script, recording the voiceover, finding footage that matches each sentence, and editing. I wanted this to run as a repeatable pipeline where a person makes the editorial decisions and the system does the rest.

**What I built**
A web platform, deployed on Railway, that runs the full chain:

1. Topic discovery from Reddit, Google Trends and YouTube, with opportunity scoring and a ranked shortlist.
2. Script writing with a bounded fact-check, patch and re-score loop, plus hook generation and selection.
3. Voiceover from text-to-speech (ElevenLabs, Gemini) or an uploaded recording. Deepgram returns word-level timestamps, and the system checks the audio for the right language and for missing narration.
4. Storyboard generation with Claude. Scene cuts are placed on real speech boundaries, not on estimates.
5. Asset acquisition per scene: stock footage from Pexels and Pixabay with semantic re-ranking, Wikimedia portraits for named people, and AI image generation (kie.ai, OpenAI) with a consistent master style. A failed scene degrades instead of failing the whole run.
6. Rendering with FFmpeg: captions timed to the speech, music, motion, colour grade, 9:16 and 16:9 output. A second export path produces a CapCut project for manual finishing.
7. YouTube metadata (title, description, tags, pinned comment) drafted from the final script.

Every artifact (script, storyboard, asset manifest, render) is stored in Cloudflare R2 and indexed in Postgres, so any step can be inspected, retried or resumed. Each execution records the worker version, prompt version, model and sampling parameters.

**From internal tool to multi-user product**
The first version had one operator and one shared identity. To open it to a small group of users I added:

- Google sign-in, accounts, and two tiers (Basic and Super) checked on the server with a deny-by-default allow-list.
- Per-account data isolation across the database and the file storage, and encrypted per-user provider keys.
- A simplified "Creator" flow for non-technical users: write a story, pick a voice and characters, see the cost, get a video.
- A credit system. One credit equals one cent of provider cost. A hold is placed before each paid call and settled or refunded afterwards. Per-account hard limits stop overspending. Billing is behind a feature flag.
- Content moderation in two layers, with a log, for text and images from people I do not know.
- An owner view for top-ups and usage.

**Engineering quality**
- About 38,000 lines of application code and 49,000 lines of tests. Around 3,400 automated tests run in CI on every push.
- Two environments: push to `main` deploys to DEV, a git tag deploys to PROD. PROD only ever receives a tagged commit.
- 121 written architecture decisions (ADR style), including reversals and the reason for them.
- A versioned prompt log: each revision of the storyboard prompt is tied to a failure I observed.
- A security audit of my own system (23 findings, ranked for the moment strangers get access). I fixed the high and medium items: legacy routes off by default, start-up refusal on weak secrets, bounded paid-call parameters, chunked uploads with early abort, log redaction for signed URLs and tokens, a non-root container with a pinned base image, and a migration lock with a health check.
- A written backup and restore procedure for Postgres and R2.
- Sprint-based delivery with a "human touchpoint" rule: every sprint ends with something a non-technical person can use.
- Strangler-fig migration: the original pipeline kept running while the new platform replaced it one stage at a time, through a one-way adapter.

**Key technical choices**
- LangGraph for orchestration, with durable Postgres checkpoints so a run can pause at a human gate and resume later. Workers are pure and stateless. Loop bounds and routing live on the graph edges, not inside workers.
- FastAPI with thin routes and pure async step functions, so the pipeline can run without an HTTP request.
- Plain HTML and JavaScript for the UI, by decision, to avoid a frontend build step.
- Paid image generation behind a provider interface, so a second provider can be added with its own key.
- Fault isolation: without a database the original pipeline still runs.

**Tools and technologies**
Python 3.11, FastAPI, Pydantic v2, LangGraph, PostgreSQL, psycopg, Claude API, OpenAI API, Deepgram, ElevenLabs, Gemini, kie.ai, Replicate, Pexels, Pixabay, Freesound, Wikimedia, FFmpeg, sentence-transformers, Cloudflare R2 (S3 API), Google OAuth, Railway, Docker, GitHub Actions, pytest.

**Skills to tag on Upwork**
Python, FastAPI, AI/LLM integration, LangGraph, prompt engineering, video automation, FFmpeg, PostgreSQL, API integration, SaaS development, Stripe-ready billing design, authentication and OAuth, test automation, CI/CD, technical documentation.

---

## 4. Shorter Upwork profile blurb (about 90 words)

I build AI automation that runs in production, not demos. My main project is a platform that turns a topic into a finished video: script writing with fact-checking, voiceover, word-accurate storyboards, footage and image generation, and FFmpeg rendering, with a person approving each editorial step. I took it from a single-operator tool to a multi-user product with Google sign-in, per-account isolation, a credit ledger and spend limits. Python, FastAPI, LangGraph, Postgres, about 3,400 automated tests, and a written decision record for every architectural choice.

---

## 5. Short LinkedIn "About" or headline lines

- Builds AI automation pipelines for production: Python, FastAPI, LangGraph, LLM APIs.
- Solo-built an AI video platform: topic to finished video, with billing, accounts and hard spend limits.

---

## Notes before you publish

Check these, because a client or recruiter may ask:

1. **Be clear about how it was built.** The repo itself says it was developed solo with AI-assisted tooling. Say so. It is true, it is common, and it is safer than being asked. What you can claim honestly: you designed the architecture, wrote the decisions, set the process and reviewed and ran the result.
2. **Status.** The friends beta has not opened. P-BILL-1 (credits) is built on a branch, its pull request is not merged, and nothing has run on DEV. Two live smoke tests (AUTH-S10 and P-CORE-S11) are still open. PROD is on an older version (v0.24.0) on purpose. The text above says "in production on DEV" and "built". Do not write "launched" or "paying users".
3. **No revenue or audience numbers.** The repo has none. If the YouTube channel has views, subscribers or videos published, add them from your own data (your input).
4. **The README is out of date.** It says "93 test files", "65+ decisions" and "27 workers". The repo now has 148 test files, 121 decisions and 38 worker modules. Update the README before you link to it. It also lists Telegram as an interface, but Telegram has been dormant since D093.
5. **Repository visibility.** The README badge points to `gobokobok/content-factory-saas`. If you link it in a portfolio, check that it is public and that no private data is in it. The audit found no secrets in the history, but the Pixabay key leak in the DEV logs is still open as an operator action.
6. **Screenshots.** `docs/screenshots/01-settings.png` to `06-metadata.png` are ready to use as portfolio images. A 30 to 60 second screen recording of one run would help more than any text.
