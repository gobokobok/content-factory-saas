"""Pipeline step orchestration helpers.

Routes call summarize_step after every update_run_log to keep run_log.txt
in sync with current pipeline status via Haiku.
"""

import logging

from src.config import Settings
from src.log_summarizer import write_run_log_summary
from src.storage import R2Client

logger = logging.getLogger(__name__)


def summarize_step(run_id: str, storage: R2Client, settings: Settings) -> None:
    """Write a Haiku-generated summary to run_log.txt after a step update.

    Always non-fatal — errors are caught inside write_run_log_summary and logged
    as warnings. No pipeline step is ever blocked by a summarizer failure.
    """
    write_run_log_summary(run_id, storage, settings.ANTHROPIC_API_KEY)
