"""Pure helpers for AI image generation (P14, D104; Animation mode P-AN1, D108).

Prompt assembly (stock mode: project style then prompt; Animation mode: scene
prompt, bible descriptions, fixed lines, master style, aspect phrase), the
per-model cost estimate and the per-run spend ledger. The ledger is one JSON file in the
run's R2 folder, `runs/{run_id}/ai_spend.json`, appended to on every paid
generation — including ones whose image the operator later replaces — so the cap
counts what was actually spent, not what is currently on screen.
"""

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from cf_platform.core.artifact_manager import ArtifactStorage

_logger = logging.getLogger(__name__)

# Fixed lines of every Animation-mode image prompt (D108). The operator's sample
# images came back with letterbox bars, panel borders and stray lettering; the
# "keep the lower part calm" line produced a dark band, so it is only added where
# a scene really has on-screen text, and says what the area must NOT become.
FIXED_LINE_NO_TEXT = "No readable text, letters or numerals anywhere in the image."
FIXED_LINE_FULL_BLEED = (
    "Full-bleed image that fills the whole frame edge to edge: "
    "no borders, no letterbox bars, no panel frame."
)
FIXED_LINE_OVERLAY = (
    "Keep the lower part of the frame calm and low in detail, as a natural continuation "
    "of the scene (not a dark band or a blank strip), so text can be placed over it later."
)
ASPECT_PHRASES = {"9:16": "Vertical 9:16.", "16:9": "Horizontal 16:9.", "1:1": "Square 1:1."}


class SpendCapReachedError(Exception):
    """Raised when one more image would take a run past its spend cap."""


def spend_key(run_id: str) -> str:
    """R2 key of a run's AI spend ledger."""
    return f"runs/{run_id}/ai_spend.json"


def build_prompt(style: str | None, prompt: str) -> str:
    """Return the text sent to the provider: the project's optional style, then the scene prompt."""
    style = (style or "").strip()
    prompt = prompt.strip()
    return f"{style}\n\n{prompt}" if style else prompt


def resolve_master_style(run_style: str | None, project_config: dict[str, Any] | None) -> str | None:
    """The master style of a run's images: the run's own, else the project's `ai_image_style`, else None."""
    own = (run_style or "").strip()
    if own:
        return own
    inherited = (project_config or {}).get("ai_image_style")
    return inherited.strip() if isinstance(inherited, str) and inherited.strip() else None


def _entry_field(entry: Any, field: str) -> str:
    """Read a continuity entry's field whether it is a model or a plain dict."""
    value = entry.get(field) if isinstance(entry, dict) else getattr(entry, field, "")
    return str(value or "").strip()


def entity_lines(entities: Iterable[str] | None, continuity: Iterable[Any] | None) -> list[str]:
    """One line per bible entry a scene uses: its name, then its description verbatim.

    Order follows the scene's `entities`. An id that is not in the bible is skipped
    with a warning — a prompt must never fail on a stale reference.
    """
    by_id = {_entry_field(entry, "id"): entry for entry in continuity or []}
    lines: list[str] = []
    for entity_id in entities or []:
        entry = by_id.get(str(entity_id))
        if entry is None:
            _logger.warning("build_animation_prompt: unknown continuity id %r ignored", entity_id)
            continue
        description = _entry_field(entry, "description")
        if not description:
            continue
        name = _entry_field(entry, "name")
        lines.append(f"{name[:1].upper()}{name[1:]}: {description}" if name else description)
    return lines


def build_animation_prompt(
    scene_prompt: str | None,
    *,
    entities: Iterable[str] | None = None,
    continuity: Iterable[Any] | None = None,
    has_overlay: bool = False,
    master_style: str | None = None,
    aspect_ratio: str | None = None,
) -> str:
    """Assemble the text sent to the image model for an Animation-mode scene (D108).

    Order: the scene's own prompt → the descriptions of the bible entries it uses,
    verbatim → the fixed lines (no text; full bleed; the calm lower part only when
    the scene has on-screen text) → the master style → the aspect phrase. Every
    part but the fixed lines is optional. Because the style and the bible are added
    here and not stored in the scene, both can change without regenerating the
    storyboard, and they are identical on every image.
    """
    parts: list[str] = []
    prompt = (scene_prompt or "").strip()
    if prompt:
        parts.append(prompt)
    parts.extend(entity_lines(entities, continuity))
    fixed = [FIXED_LINE_NO_TEXT, FIXED_LINE_FULL_BLEED]
    if has_overlay:
        fixed.append(FIXED_LINE_OVERLAY)
    parts.append(" ".join(fixed))
    style = (master_style or "").strip()
    if style:
        parts.append(style)
    phrase = ASPECT_PHRASES.get(aspect_ratio or "")
    if phrase:
        parts.append(phrase)
    return "\n\n".join(parts)


def model_cost_usd(model: str | None, model_costs: dict[str, float] | None, default_cost_usd: float) -> float:
    """The estimated price of one image on `model`: its entry in the price table, else the default.

    The table is IMAGE_MODEL_COSTS_USD (model id → dollars). A model without an
    entry, or with one that is not a non-negative number, costs IMAGE_COST_USD.
    """
    try:
        cost = float((model_costs or {})[model or ""])
    except (KeyError, TypeError, ValueError):
        return float(default_cost_usd)
    return cost if cost >= 0 else float(default_cost_usd)


async def read_spend(storage: ArtifactStorage, run_id: str) -> dict[str, Any]:
    """Return the run's ledger; an empty one when nothing was generated yet.

    A missing or unreadable ledger counts as empty: it is created by the first
    generation, and a read failure must not block the operator.
    """
    try:
        ledger = await storage.get_json(spend_key(run_id))
    except Exception:
        return {"total_usd": 0.0, "generations": []}
    ledger.setdefault("generations", [])
    ledger["total_usd"] = round(sum(g.get("cost_usd", 0.0) for g in ledger["generations"]), 4)
    return ledger


def spend_summary(ledger: dict[str, Any], cost_per_image_usd: float, cap_usd: float) -> dict[str, Any]:
    """The numbers Studio shows: spent, cap, remaining, count and the per-image estimate."""
    spent = float(ledger.get("total_usd", 0.0))
    return {
        "spent_usd": round(spent, 4),
        "cap_usd": cap_usd,
        "remaining_usd": round(max(cap_usd - spent, 0.0), 4),
        "images": len(ledger.get("generations", [])),
        "cost_per_image_usd": cost_per_image_usd,
    }


def ensure_under_cap(
    ledger: dict[str, Any], cost_per_image_usd: float, cap_usd: float, reserved_usd: float = 0.0
) -> None:
    """Raise SpendCapReachedError when one more image would exceed the cap.

    `reserved_usd` is what generations already under way will cost once they
    finish — it keeps several parallel generations from each passing the check.
    """
    spent = float(ledger.get("total_usd", 0.0))
    if spent + reserved_usd + cost_per_image_usd > cap_usd + 1e-9:
        raise SpendCapReachedError(
            f"This run has spent ${spent:.2f} of its ${cap_usd:.2f} AI image cap — "
            "another image would go over it. Raise the cap for this run in Generate all images, "
            "or the default in Settings → Defaults."
        )


def effective_spend_cap(run_cap_usd: float | None, default_cap_usd: float, max_cap_usd: float) -> float:
    """The cap a run generates under: its own cap when set, else the tenant default.

    A run's own cap is never above IMAGE_RUN_SPEND_CAP_MAX_USD; the tenant default
    is the operator's own setting and is used as it is.
    """
    if run_cap_usd is None:
        return float(default_cap_usd)
    return max(0.0, min(float(run_cap_usd), float(max_cap_usd)))


async def record_spend(
    storage: ArtifactStorage,
    run_id: str,
    *,
    scene: str,
    cost_usd: float,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Append one generation to the run's ledger and return the updated ledger."""
    ledger = await read_spend(storage, run_id)
    ledger["generations"].append({
        "scene": scene,
        "cost_usd": cost_usd,
        "provider": provider,
        "model": model,
        "at": datetime.now(UTC).isoformat(),
    })
    ledger["total_usd"] = round(sum(g["cost_usd"] for g in ledger["generations"]), 4)
    await storage.put_json(spend_key(run_id), ledger)
    return ledger
