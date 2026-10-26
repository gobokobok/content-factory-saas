"""Compare what a paid action is reserved at with what the providers billed (BILL-F3). Read-only.

Usage (against the database named in the environment):
    python scripts/cost_report.py --days 30
    python scripts/cost_report.py --days 30 --bill llm=12.40 --bill tts=3.10 --bill render=0

The owner's own (exempt) actions are left out: they are not charged. See cf_platform/core/cost_report.py.
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from cf_platform.core.config import get_platform_settings
from cf_platform.core.cost_report import KINDS, fetch_entries, format_report, summarise
from cf_platform.core.db import get_pool


def parse_bills(values: list[str]) -> dict[str, float]:
    """Turn ["llm=12.4", "tts=3"] into {"llm": 12.4, "tts": 3.0}; SystemExit on a bad entry."""
    bills: dict[str, float] = {}
    for value in values:
        kind, _, amount = value.partition("=")
        if kind not in KINDS:
            raise SystemExit(f"--bill {value!r}: the kind must be one of {', '.join(KINDS)}")
        try:
            bills[kind] = float(amount)
        except ValueError:
            raise SystemExit(f"--bill {value!r}: the amount must be a number") from None
        if bills[kind] < 0:
            raise SystemExit(f"--bill {value!r}: the amount cannot be negative")
    return bills


async def main(argv: list[str] | None = None) -> int:
    """Print the report. Returns the exit code."""
    parser = argparse.ArgumentParser(description="Compare reserved prices with provider bills.")
    parser.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    parser.add_argument("--bill", action="append", default=[], help="a provider invoice for the window, kind=USD (repeatable)")
    args = parser.parse_args(argv)
    bills = parse_bills(args.bill)
    settings = get_platform_settings()
    pool = get_pool(settings.DATABASE_URL)
    if pool is None:
        print("DATABASE_URL is not set: there is no ledger to read.", file=sys.stderr)
        return 2
    await pool.open()
    try:
        entries, runs = await fetch_entries(pool, args.days)
    finally:
        await pool.close()
    print(format_report(summarise(entries, bills, settings), settings, args.days, runs))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
