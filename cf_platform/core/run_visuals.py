"""What a run's visuals are made from, read from its settings.json (P-AN1, D108).

`settings.json` is the only channel from the run settings drawer to the workers
(the same file the voice worker reads its narration settings from). A missing or
unreadable file is the stock default — a stale file must never break a step.
"""

import logging
from dataclasses import dataclass
from typing import Any

from cf_platform.core.ai_images import resolve_master_style
from cf_platform.core.artifact_manager import ArtifactStorage

_logger = logging.getLogger(__name__)

_VALID_ASPECTS = ("9:16", "16:9", "1:1")
_VISUAL_MODES = ("stock", "ai_animation")


@dataclass(frozen=True)
class RunVisuals:
    """A run's visual settings, resolved."""

    visual_mode: str = "stock"
    # The run's style, else the project's ai_image_style, else None.
    master_style: str | None = None
    # The project's ai_image_style alone — what a stock-mode run puts in front of a prompt (D104).
    project_style: str | None = None
    aspect_ratio: str | None = None
    # The run's own AI image cap from the Generate all dialog; None = tenant default.
    spend_cap_usd: float | None = None

    @property
    def is_animation(self) -> bool:
        """True when every scene of the run is a generated image."""
        return self.visual_mode == "ai_animation"


def settings_key(run_id: str) -> str:
    """R2 key of a run's settings.json."""
    return f"runs/{run_id}/settings.json"


async def read_run_settings(storage: ArtifactStorage, run_id: str) -> dict[str, Any]:
    """The run's stored settings.json as a dict; {} when absent or unreadable (never raises)."""
    try:
        data = await storage.get_json(settings_key(run_id))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def project_config_for_run(runs: Any, projects: Any, run_id: str) -> dict[str, Any]:
    """The config of the run's project; {} when the run or project cannot be read (never raises)."""
    if runs is None or projects is None:
        return {}
    try:
        run = await runs.get(run_id)
        project = await projects.get(run.project_id)
    except Exception:
        _logger.debug("run_visuals: no project config for run %s", run_id, exc_info=True)
        return {}
    return dict(project.config or {})


def visuals_from(settings: dict[str, Any], project_config: dict[str, Any] | None) -> RunVisuals:
    """Resolve RunVisuals from a settings.json dict and the project's config."""
    mode = settings.get("visual_mode")
    aspect = settings.get("aspect_ratio")
    cap = settings.get("image_spend_cap_usd")
    try:
        cap = float(cap) if cap is not None else None
    except (TypeError, ValueError):
        cap = None
    return RunVisuals(
        visual_mode=mode if mode in _VISUAL_MODES else "stock",
        master_style=resolve_master_style(settings.get("master_style"), project_config),
        project_style=resolve_master_style(None, project_config),
        aspect_ratio=aspect if aspect in _VALID_ASPECTS else None,
        spend_cap_usd=cap if cap is not None and cap >= 0 else None,
    )


async def load_run_visuals(
    storage: ArtifactStorage, run_id: str, runs: Any = None, projects: Any = None
) -> RunVisuals:
    """Read and resolve a run's visual settings (never raises)."""
    settings = await read_run_settings(storage, run_id)
    return visuals_from(settings, await project_config_for_run(runs, projects, run_id))


async def save_run_spend_cap(storage: ArtifactStorage, run_id: str, cap_usd: float) -> None:
    """Store the run's own AI image cap in settings.json, leaving every other setting as it is."""
    settings = await read_run_settings(storage, run_id)
    settings["image_spend_cap_usd"] = round(float(cap_usd), 2)
    await storage.put_json(settings_key(run_id), settings)
