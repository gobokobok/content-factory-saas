"""Model router — centralizes Claude model selection and per-call cost logging."""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import Settings

logger = logging.getLogger(__name__)

# Task type constants — use these instead of string literals at call sites
GENERATE = "generate"
VALIDATE = "validate"
SUMMARIZE = "summarize"
TRANSFORM = "transform"
REASON = "reason"

# Default model per task type — also used by call sites as fallback when no router is injected
DEFAULT_MODELS: dict[str, str] = {
    GENERATE: "claude-sonnet-4-6",
    VALIDATE: "claude-haiku-4-5-20251001",
    SUMMARIZE: "claude-haiku-4-5-20251001",
    TRANSFORM: "claude-haiku-4-5-20251001",
    REASON: "claude-sonnet-4-6",
}

# USD cost per input/output token for each known model
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "claude-haiku-4-5-20251001": (0.80 / 1_000_000, 4.00 / 1_000_000),
}


class ModelRouter:
    """Routes Claude API calls to the correct model per task type.

    Model strings come from Settings (ENV vars) so they can be overridden
    per-environment without code changes. Every call site logs model used,
    token counts, and a USD cost estimate via log_cost().
    """

    def __init__(self, settings: "Settings") -> None:
        """Build a router from validated Settings."""
        self._mapping: dict[str, str] = {
            GENERATE: settings.CLAUDE_MODEL,
            VALIDATE: settings.MODEL_VALIDATE,
            SUMMARIZE: settings.MODEL_SUMMARIZE,
            TRANSFORM: settings.MODEL_TRANSFORM,
            REASON: settings.MODEL_REASON,
        }

    def model_for(self, task: str) -> str:
        """Return the configured model string for the given task type."""
        model = self._mapping.get(task)
        if model is None:
            logger.warning(
                "ModelRouter: unknown task type '%s' — falling back to GENERATE model", task
            )
            return self._mapping[GENERATE]
        return model

    def log_cost(
        self, task: str, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Log a Claude API call (model, tokens, cost) and return the USD estimate."""
        in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
        if model not in PRICING:
            logger.warning(
                "ModelRouter: no pricing data for model '%s' — cost logged as $0.00", model
            )
        cost_usd = round(input_tokens * in_rate + output_tokens * out_rate, 8)
        logger.info(
            "Claude call: task=%s model=%s input_tokens=%d output_tokens=%d cost_usd=$%.8f",
            task,
            model,
            input_tokens,
            output_tokens,
            cost_usd,
        )
        return cost_usd
