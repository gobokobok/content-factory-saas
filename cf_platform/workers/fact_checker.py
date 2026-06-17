"""Fact-checker worker (P5-S3) — `script_drafts → factcheck_report`.

Reads the first draft from the `script_drafts` artifact produced by the Script
Writer, extracts specific factual claims, and verifies each via Anthropic's
built-in web_search_20260209 server-side tool (D053). Claude executes searches
on Anthropic's infrastructure; no client-side tool loop is required.

Control signal:
  "continue"  if  unverified_ratio <= unverified_threshold (default 0.3)
  "retry"     otherwise (graph will increment iteration and re-run the writer)

`unverified_ratio` is (refuted + unverifiable) / total_claims. If no claims
are found the ratio is 0.0 and the signal is always "continue".

`unverified_threshold` is read from `getattr(state, "unverified_threshold", 0.3)` so
the worker is forward-compatible with `IdeaToScriptState` (P5-S5) without
importing it.

Runs parallel to the Script Quality Scorer (P5-S2) per the execution plan — only
the first draft (index 0) is checked, since the scorer's best-draft selection
is not yet available at the time this worker executes.

Pure worker per D040/D056.
"""

import json
from datetime import datetime, timezone
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import ControlSignal, StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration
from cf_platform.workers.script_writer import ScriptDraftsArtifact

_FACT_CHECKER_PROMPT_V1 = """\
You are a fact-checker for "The Housing Equation", a data-driven YouTube Shorts \
channel about American housing economics.

You will receive a script draft. Extract every specific factual claim — statistics, \
percentages, dates, prices, named policies or programs, and specific numerical data — \
and verify each one using web search. Skip opinions, general trends stated without \
numbers, and rhetorical framing.

For each claim:
1. Identify the precise assertion
2. Search for authoritative sources (Federal Reserve, Census Bureau, HUD, NAR, \
academic papers, government data)
3. Assign a verdict: "supported", "refuted", or "unverifiable"
4. Record the best source URL (empty string if unverifiable)
5. Write a one-sentence note explaining your verdict

Return ONLY a JSON object with a "claims" array. No preamble, no markdown fences. \
Example:
{
  "claims": [
    {
      "claim": "The average American could afford a home after 3 years of savings in 1980",
      "verdict": "supported",
      "source": "https://fred.stlouisfed.org/...",
      "note": "Federal Reserve data confirms median home prices in 1980 were ~3x median household income."
    }
  ]
}\
"""

FACT_CHECKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_FACT_CHECKER_PROMPT_V1,
    model="claude-sonnet-4-6",
    sampling_params={},
)

_DEFAULT_UNVERIFIED_THRESHOLD = 0.3


class ClaimVerification(BaseModel):
    """Verification result for a single factual claim extracted from a script draft."""

    claim: str
    verdict: Literal["supported", "refuted", "unverifiable"]
    source: str
    note: str


class FactcheckReportArtifact(BaseModel):
    """Artifact body produced by the fact-checker worker."""

    idea_title: str
    draft_number: int
    claims: list[ClaimVerification]
    verified_count: int
    refuted_count: int
    unverifiable_count: int
    checked_at: datetime


def _build_user_message(idea_title: str, draft_number: int, script: str) -> str:
    """Compose the Claude user message from the idea title and a single script draft."""
    return f"Idea: {idea_title}\n\n--- Draft {draft_number} ---\n{script}"


def build_fact_checker_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a fact-checker WorkerNode bound to storage and the Anthropic API key.

    Reads the first draft from `state.artifacts["script_drafts"]` → calls Claude Sonnet
    with the built-in web_search_20260209 server-side tool → parses per-claim verdicts →
    returns `FactcheckReportArtifact`.

    Runs parallel to the Script Quality Scorer (P5-S2); checks draft index 0 since
    the scorer's best-draft selection is not yet available.

    Control signal is derived from (refuted + unverifiable) / total_claims compared
    against `getattr(state, "unverified_threshold", 0.3)`:
      "continue"  if ratio meets threshold (or no claims found)
      "retry"     otherwise

    Raises KeyError if `state.artifacts["script_drafts"]` is absent (Script Writer
    must run first). Raises ValueError if Claude returns no text block or
    non-JSON / malformed claim objects.
    """

    async def fact_checker(state: StageState) -> WorkerOutput:
        """Read first script draft, verify claims via web search, return FactcheckReportArtifact."""
        drafts_key = state.artifacts.get("script_drafts")
        if not drafts_key:
            raise KeyError(
                "state.artifacts['script_drafts'] is missing"
                " — run the Script Writer worker before Fact Checker"
            )

        _, body = await read_artifact(storage, drafts_key)
        drafts_artifact = ScriptDraftsArtifact.model_validate(body)

        # Always check the first draft — runs parallel to scorer; best draft unknown yet
        first_draft = drafts_artifact.drafts[0]
        user_message = _build_user_message(
            drafts_artifact.idea_title, first_draft.draft_number, first_draft.script
        )

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
        response = await client.messages.create(
            model=FACT_CHECKER_REGISTRATION.model,
            max_tokens=2048,
            system=FACT_CHECKER_REGISTRATION.prompt,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=[{"role": "user", "content": user_message}],
        )

        # Server-side tool responses may contain mixed content blocks (server_tool_use,
        # web_search_result, text) — extract only the final text block for JSON parsing
        text_blocks = [b for b in response.content if b.type == "text"]
        if not text_blocks:
            raise ValueError(
                "fact_checker@v1 returned no text block"
                " — Claude may not have produced a final JSON summary"
            )
        raw_text = strip_markdown_fences(text_blocks[-1].text)

        try:
            raw_report: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"fact_checker@v1 returned invalid JSON: {exc}"
                f"\nRaw response: {raw_text!r}"
            ) from exc

        claims = [ClaimVerification.model_validate(c) for c in raw_report.get("claims", [])]

        verified_count = sum(1 for c in claims if c.verdict == "supported")
        refuted_count = sum(1 for c in claims if c.verdict == "refuted")
        unverifiable_count = sum(1 for c in claims if c.verdict == "unverifiable")
        total = len(claims)

        unverified_ratio = (refuted_count + unverifiable_count) / total if total > 0 else 0.0
        unverified_threshold: float = getattr(
            state, "unverified_threshold", _DEFAULT_UNVERIFIED_THRESHOLD
        )
        control: ControlSignal = "continue" if unverified_ratio <= unverified_threshold else "retry"

        artifact = FactcheckReportArtifact(
            idea_title=drafts_artifact.idea_title,
            draft_number=first_draft.draft_number,
            claims=claims,
            verified_count=verified_count,
            refuted_count=refuted_count,
            unverifiable_count=unverifiable_count,
            checked_at=datetime.now(timezone.utc),
        )
        return WorkerOutput(artifact=artifact, control=control)

    return fact_checker
