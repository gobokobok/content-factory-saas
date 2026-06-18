"""Narrative Lens worker (P5-S7) — `merged_blueprint + evaluation → narrative_lens`.

Node [4] in the Blueprint IR pipeline, inserted between blueprint_merge and
hook_generation. Translates verified blueprint facts into storytelling angles
(identity, contrarian, philosophical, emotional) that the hook generator and
script generator use to move the script from 95% rational toward 70/30.

STRICT CONTRACT (D059 — Narrative Lens Worker Contract):
  This worker MUST NOT invent any fact, number, statistic, study, brand,
  country, timeline, or comparison. It receives only the verified claims
  and corrections from the blueprint + evaluation and may only reframe those
  existing facts into narrative dimensions. It owns storytelling; the
  Fact Checker/Evaluator owns truth (D060 — Information Ownership Principle).

Model: Haiku (cheap transformation node — ~$0.005/run).
Pure worker per D040/D056.
"""

import json
from typing import Any

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import Blueprint, EvaluationArtifact, NarrativeLens
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_NARRATIVE_LENS_PROMPT_V1 = """\
You are a narrative strategist — not a researcher. Your only job is to translate \
verified facts into emotionally resonant storytelling angles.

STRICT CONTRACT — YOU MUST FOLLOW THIS EXACTLY:
- DO NOT invent any fact, number, statistic, study, brand, country, timeline, or comparison.
- DO NOT introduce any entity or claim not present in the provided verified facts.
- Every angle you write must be derivable EXCLUSIVELY from the facts listed in the user message.
- Reframing means finding the human meaning in an existing fact — not adding new facts.
- Use hedged language ("often", "can", "tends to") when generalising — never state new absolutes.

You will receive a list of verified claims and corrections from a fact-checked blueprint.
Produce four storytelling angles and a short list of narrative devices, all grounded
in those facts.

Return ONLY a JSON object. No preamble, no markdown fences:
{
  "identity_angle": "who is this story really about — a cultural or behavioural reframing",
  "contrarian_angle": "what common belief the verified facts quietly disprove",
  "philosophical_angle": "the deeper principle or mindset shift these facts point to",
  "emotional_angle": "the human feeling or relatable truth these facts evoke",
  "story_devices": ["narrative technique 1", "narrative technique 2", "narrative technique 3"]
}\
"""

NARRATIVE_LENS_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_NARRATIVE_LENS_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


def build_narrative_lens_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a narrative lens WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['merged_blueprint'] → Blueprint (for claims + required_evidence)
      state.artifacts['evaluation']       → EvaluationArtifact (for factual_corrections)

    Passes ONLY verified claims to the LLM — no signals, no raw research, no context
    outside the verified blueprint (D059). Makes one Haiku call.

    Raises KeyError if either artifact reference is absent.
    Raises ValueError on JSON parse failure.
    """

    async def narrative_lens(state: StageState) -> WorkerOutput:
        """Read verified claims, call Claude Haiku, return NarrativeLens artifact."""
        bp_key = state.artifacts.get("merged_blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['merged_blueprint'] missing — "
                "blueprint_merge must run before narrative_lens"
            )
        eval_key = state.artifacts.get("evaluation")
        if not eval_key:
            raise KeyError(
                "state.artifacts['evaluation'] missing — "
                "evaluation must run before narrative_lens"
            )

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        _, eval_body = await read_artifact(storage, eval_key)
        evaluation = EvaluationArtifact.model_validate(eval_body)

        user_message = _build_user_message(blueprint, evaluation)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=60.0)
        response = await client.messages.create(
            model=NARRATIVE_LENS_REGISTRATION.model,
            max_tokens=1024,
            system=_NARRATIVE_LENS_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = extract_json_object(response.content[0].text)
        try:
            raw: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"narrative_lens@v1 returned invalid JSON: {exc}\nRaw: {raw_text!r}"
            ) from exc

        artifact = NarrativeLens(
            identity_angle=raw.get("identity_angle", ""),
            contrarian_angle=raw.get("contrarian_angle", ""),
            philosophical_angle=raw.get("philosophical_angle", ""),
            emotional_angle=raw.get("emotional_angle", ""),
            story_devices=raw.get("story_devices", []),
        )
        return WorkerOutput(artifact=artifact)

    return narrative_lens


def _build_user_message(blueprint: Blueprint, evaluation: EvaluationArtifact) -> str:
    """Compose the Claude user message — only verified facts, no raw signals (D059)."""
    parts = ["=== VERIFIED CLAIMS (your only source material) ==="]
    for i, claim in enumerate(blueprint.claims, start=1):
        parts.append(f"{i}. {claim}")

    if evaluation.factual_corrections:
        parts.append("")
        parts.append("=== CORRECTIONS (replace any conflicting claims above) ===")
        for i, correction in enumerate(evaluation.factual_corrections, start=1):
            parts.append(f"{i}. {correction}")

    if blueprint.required_evidence:
        parts.append("")
        parts.append("=== REQUIRED EVIDENCE ITEMS ===")
        for item in blueprint.required_evidence:
            parts.append(f"- {item}")

    parts.append("")
    parts.append(
        "Produce four storytelling angles and narrative devices grounded EXCLUSIVELY "
        "in the facts above. No new facts."
    )
    return "\n".join(parts)
