"""Patch Generator worker (P5-S6) — `generated_script + integrity_report → patches`.

Node [8] in the Blueprint IR pipeline (D058). Single Haiku call that produces
minimal, targeted Patch instructions — NOT a full script rewrite. Each Patch
specifies a verbatim span to find in the script and a replacement string.

patch_generator is only called when integrity_check fails.

Pure worker per D040/D056.
"""

import json
from datetime import UTC, datetime
from typing import Any

import anthropic

from cf_platform.core.artifact_manager import ArtifactStorage, read_artifact
from cf_platform.core.idea_to_script_schemas import (
    GeneratedScriptArtifact,
    IntegrityReport,
    Patch,
    PatchSetArtifact,
)
from cf_platform.core.llm_utils import strip_markdown_fences
from cf_platform.core.schemas import StageState, WorkerNode, WorkerOutput
from cf_platform.core.worker_registry import WorkerRegistration

_PATCH_GENERATOR_PROMPT_V1 = """\
You are a script editor generating minimal surgical edits to fix integrity issues.

Given a script and a list of integrity issues, produce the smallest set of targeted \
patches that resolve medium and high severity issues. Each patch modifies only the \
affected span — never rewrite the entire script.

Return ONLY a JSON array of patch objects (no markdown fences):
[
  {
    "operation": "replace",
    "target": "verbatim text from the script to find (must be exact)",
    "replacement": "corrected replacement text"
  }
]

Allowed operations:
  "replace" — replace `target` with `replacement`
  "delete"  — remove `target` (omit `replacement` or set null)
  "insert"  — insert `replacement` immediately after `target`

Rules:
- `target` must be an exact verbatim substring of the script (copy-paste carefully)
- Only fix medium and high severity issues; ignore low severity
- If no fixes are needed, return an empty array: []
- Keep each patch minimal — change only the specific problematic phrase\
"""

PATCH_GENERATOR_REGISTRATION = WorkerRegistration(
    worker_version="1.0.0",
    prompt_version="v1",
    prompt=_PATCH_GENERATOR_PROMPT_V1,
    model="claude-haiku-4-5",
    sampling_params={},
)


def build_patch_generator_worker(
    storage: ArtifactStorage,
    anthropic_api_key: str,
) -> WorkerNode:
    """Return a patch generator WorkerNode bound to storage and the Anthropic API key.

    Reads:
      state.artifacts['generated_script']  → GeneratedScriptArtifact
      state.artifacts['integrity_report']  → IntegrityReport

    Makes one Haiku call; returns an empty PatchSetArtifact on JSON parse failure
    rather than raising, since an empty patch set is a safe no-op for apply_patch.
    Raises KeyError if either artifact reference is absent.
    """

    async def patch_generator(state: StageState) -> WorkerOutput:
        """Read script + integrity_report, call Claude Haiku, return PatchSetArtifact."""
        script_key = state.artifacts.get("generated_script")
        if not script_key:
            raise KeyError(
                "state.artifacts['generated_script'] missing — "
                "script_generation must run before patch_generation"
            )
        report_key = state.artifacts.get("integrity_report")
        if not report_key:
            raise KeyError(
                "state.artifacts['integrity_report'] missing — "
                "integrity_check must run before patch_generation"
            )

        _, script_body = await read_artifact(storage, script_key)
        script_artifact = GeneratedScriptArtifact.model_validate(script_body)

        _, report_body = await read_artifact(storage, report_key)
        integrity_report = IntegrityReport.model_validate(report_body)

        # Filter to only medium/high severity issues for the LLM
        actionable = [
            issue for issue in integrity_report.issues
            if issue.severity in ("medium", "high")
        ]

        if not actionable:
            artifact = PatchSetArtifact(patches=[], generated_at=datetime.now(UTC))
            return WorkerOutput(artifact=artifact)

        user_message = _build_user_message(script_artifact.script, actionable)

        client = anthropic.AsyncAnthropic(api_key=anthropic_api_key, timeout=60.0)
        response = await client.messages.create(
            model=PATCH_GENERATOR_REGISTRATION.model,
            max_tokens=1024,
            system=_PATCH_GENERATOR_PROMPT_V1,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = strip_markdown_fences(response.content[0].text)
        patches: list[Patch] = []
        try:
            raw_list: list[Any] = json.loads(raw_text)
            patches = [Patch.model_validate(p) for p in raw_list]
        except (json.JSONDecodeError, Exception):
            # Safe fallback: empty patch set; apply_patch will be a no-op
            patches = []

        artifact = PatchSetArtifact(
            patches=patches,
            generated_at=datetime.now(UTC),
        )
        return WorkerOutput(artifact=artifact)

    return patch_generator


def _build_user_message(script: str, issues: list) -> str:
    """Compose the Claude user message from the script and actionable issues."""
    issue_lines = []
    for i, issue in enumerate(issues, start=1):
        span = f' (span: "{issue.span}")' if issue.span else ""
        issue_lines.append(f"{i}. [{issue.severity.upper()}]{span} {issue.description}")

    parts = [
        "=== SCRIPT ===",
        script,
        "",
        "=== ISSUES TO FIX ===",
        "\n".join(issue_lines),
        "",
        "Generate the minimal patch set and return the JSON array.",
    ]
    return "\n".join(parts)
