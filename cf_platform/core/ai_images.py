"""Pure helpers for per-scene AI image generation (P14, D104).

Prompt assembly and the per-run spend ledger. The ledger is one JSON file in the
run's R2 folder, `runs/{run_id}/ai_spend.json`, appended to on every paid
generation — including ones whose image the operator later replaces — so the cap
counts what was actually spent, not what is currently on screen.
"""

from datetime import UTC, datetime
from typing import Any

from cf_platform.core.artifact_manager import ArtifactStorage


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


def ensure_under_cap(ledger: dict[str, Any], cost_per_image_usd: float, cap_usd: float) -> None:
    """Raise SpendCapReachedError when one more image would exceed the cap."""
    spent = float(ledger.get("total_usd", 0.0))
    if spent + cost_per_image_usd > cap_usd + 1e-9:
        raise SpendCapReachedError(
            f"This run has spent ${spent:.2f} of its ${cap_usd:.2f} AI image cap — "
            "another image would go over it. Raise IMAGE_RUN_SPEND_CAP_USD or use stock for this scene."
        )


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
