"""The retention job (LEGAL-S1): delete what the privacy notice says is deleted.

* ``prompt_log`` rows older than ``PROMPT_LOG_RETENTION_DAYS`` (0 keeps them for ever)
* sessions that expired or were revoked, and sign-in states left over from an abandoned sign-in (AUTH-F1)

It runs once at start-up and then every ``RETENTION_JOB_INTERVAL_HOURS`` (0 turns it off). A failure is
logged and never stops the app: the next run tries again.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from cf_platform.core.accounts import AccountStore
from cf_platform.core.moderation import PromptLog

_logger = logging.getLogger(__name__)

# A sign-in that was not finished within a day will never be: the state is single use and short-lived.
OAUTH_STATE_MAX_AGE = timedelta(days=1)


async def run_retention(
    prompt_log: PromptLog,
    accounts: AccountStore,
    *,
    prompt_log_days: int,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run one pass and return how many rows each rule removed."""
    moment = now or datetime.now(UTC)
    removed = {"prompt_log": 0, "sessions": 0, "oauth_states": 0}
    if prompt_log_days > 0:
        removed["prompt_log"] = await prompt_log.purge_older_than(moment - timedelta(days=prompt_log_days))
    removed["sessions"], removed["oauth_states"] = await accounts.purge_expired(moment, OAUTH_STATE_MAX_AGE)
    return removed


async def retention_loop(settings: Any, prompt_log: PromptLog, accounts: AccountStore) -> None:
    """Run the retention pass now and then every RETENTION_JOB_INTERVAL_HOURS, until cancelled."""
    hours = int(settings.RETENTION_JOB_INTERVAL_HOURS)
    if hours <= 0:
        return
    while True:
        try:
            removed = await run_retention(prompt_log, accounts, prompt_log_days=int(settings.PROMPT_LOG_RETENTION_DAYS))
            _logger.info("retention: removed %s", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("retention: a pass failed — it will be tried again")
        await asyncio.sleep(hours * 3600)
