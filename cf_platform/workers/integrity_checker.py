"""Integrity Checker worker (P5-S6) — `generated_script + merged_blueprint → integrity_report`.

Nodes [7] and [re_check] in the Blueprint IR pipeline (D058). Single Haiku call
that verifies the generated (or patched) script against the blueprint for
hallucinations, factual inconsistencies, and structural completeness.

Returns control="continue" on pass, "retry" on fail. The graph routes to
script_packager on "continue" and to the patch cycle on "retry".

Pure worker per D040/D056.
"""

import json
from typing import Any

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import (
    Blueprint,
    GeneratedScriptArtifact,
    IntegrityIssue,
    IntegrityReport,
)
from cf_platform.core.llm_utils import extract_json_object
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_INTEGRITY_CHECKER_PROMPT_V1 = """\
You are an integrity checker for short-form video scripts.

Given a script and the blueprint it was written from, check for:
1. Hallucinations — claims in the script that contradict or go beyond the blueprint's claims
2. Missing required evidence — items from required_evidence that are absent from the script
3. Hook presence — the blueprint's hook angle must appear near the start of the script
4. Structural completeness — the script must cover the blueprint's section topics

Return ONLY a JSON object (no markdown fences):
{
  "passed": <true if no medium/high severity issues found>,
  "issues": [
    {
      "description": "Brief description of the issue",
      "span": "verbatim excerpt from the script containing the issue (or null)",
      "severity": "low|medium|high"
    }
  ]
}

Rules:
- "passed" is true only when there are zero medium or high severity issues
- "passed" is false if any medium or high severity issue exists
- Minor style issues are "low" severity and do not affect "passed"
- An empty issues list means the script is fully compliant\
"""

INTEGRITY_CHECKER_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_INTEGRITY_CHECKER_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


def build_integrity_checker_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return an integrity checker WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['generated_script']  → GeneratedScriptArtifact
      state.artifacts['merged_blueprint']  → Blueprint

    Returns control='continue' on pass, 'retry' on fail.
    Raises KeyError if either artifact reference is absent.
    """

    async def integrity_checker(state: StageState) -> WorkerOutput:
        """Read script + blueprint, call Claude Haiku, return IntegrityReport."""
        script_key = state.artifacts.get("generated_script")
        if not script_key:
            raise KeyError(
                "state.artifacts['generated_script'] missing — "
                "script_generation must run before integrity_check"
            )
        bp_key = state.artifacts.get("merged_blueprint")
        if not bp_key:
            raise KeyError(
                "state.artifacts['merged_blueprint'] missing — "
                "blueprint_merge must run before integrity_check"
            )

        _, script_body = await read_artifact(storage, script_key)
        script_artifact = GeneratedScriptArtifact.model_validate(script_body)

        _, bp_body = await read_artifact(storage, bp_key)
        blueprint = Blueprint.model_validate(bp_body)

        user_message = _build_user_message(script_artifact.script, blueprint)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=60.0)
        response = await client.messages.create(
            model=INTEGRITY_CHECKER_REGISTRATION.model,
            max_tokens=1024,
            system=_INTEGRITY_CHECKER_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = extract_json_object(response.content[0].text)
        try:
            raw_dict: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"integrity_checker@v1 returned invalid JSON: {exc}\nRaw: {raw_text!r}"
            ) from exc

        raw_issues = raw_dict.get("issues", [])
        issues = [IntegrityIssue.model_validate(issue) for issue in raw_issues]
        passed = bool(raw_dict.get("passed", not issues))

        artifact = IntegrityReport(passed=passed, issues=issues)
        control = "continue" if passed else "retry"
        return WorkerOutput(artifact=artifact, control=control)  # type: ignore[arg-type]

    return integrity_checker


def _build_user_message(script: str, blueprint: Blueprint) -> str:
    """Compose the Claude user message from the script and blueprint."""
    parts = [
        "=== BLUEPRINT ===",
        f"Hook angle: {blueprint.hook_angle}",
        f"Claims: {json.dumps(blueprint.claims)}",
        f"Required evidence: {json.dumps(blueprint.required_evidence)}",
        "",
        "=== GENERATED SCRIPT ===",
        script,
        "",
        "Check the script against the blueprint and return the JSON integrity report.",
    ]
    return "\n".join(parts)
