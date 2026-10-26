"""Erase one account's data (LEGAL-S1). Dry run by default — it prints what it WOULD remove and changes nothing.

Usage (against the database and bucket named in the environment, e.g. a DEV or PROD shell):
    python scripts/erase_tenant.py --email friend@example.com             # dry run
    python scripts/erase_tenant.py --tenant u_abc123 --execute           # asks you to type the tenant id first
    python scripts/erase_tenant.py --email friend@example.com --execute --yes   # no prompt (scripted)

See docs/RUNBOOK.md, "Erasing an account", for what is removed, what is kept anonymised and the checks to make.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

# Allow imports from the project root when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

from cf_platform.core.config import get_platform_settings
from cf_platform.core.db import get_pool
from cf_platform.core.erasure import ErasureRefused, ErasureReport, erase_tenant
from cf_platform.interfaces.dependencies import get_artifact_storage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description="Erase one tenant's data. Dry run unless --execute is given.")
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email", help="the account's e-mail address")
    who.add_argument("--tenant", help="the tenant id")
    parser.add_argument("--execute", action="store_true", help="really delete (default: dry run)")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation (with --execute)")
    return parser.parse_args(argv)


def settings_bucket() -> str:
    """The R2 bucket the script is pointed at (so a wrong environment is visible before --execute)."""
    return get_platform_settings().R2_BUCKET_NAME


def database_host() -> str:
    """The database host from DATABASE_URL, without credentials."""
    url = get_platform_settings().DATABASE_URL
    return (urlsplit(url).hostname or "(none)") if url else "(none)"


def format_report(report: ErasureReport) -> str:
    """The report as text for the operator."""
    mode = "DRY RUN — nothing was changed" if report.dry_run else "ERASED"
    lines = [
        f"{mode}",
        f"environment: bucket {settings_bucket()}, database host {database_host()}",
        f"tenant:      {report.tenant_id}",
        f"e-mail(s):   {', '.join(report.emails) or '(none)'}",
        f"runs:        {len(report.run_ids)}",
        f"R2 files:    {report.files}  (prefixes: {', '.join(report.prefixes[:3])}{' …' if len(report.prefixes) > 3 else ''})",
    ]
    lines += [f"  e.g. {key}" for key in report.sample_files]
    lines.append("rows:")
    lines += [f"  {table:<34} {count}" for table, count in report.rows.items()]
    lines.append(f"credit ledger is kept under the pseudonym {report.anonymised_as}")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    """Run the dry run, and the erase when --execute (and the confirmation) say so. Returns the exit code."""
    args = parse_args(argv)
    settings = get_platform_settings()
    pool = get_pool(settings.DATABASE_URL)
    if pool is None:
        print("DATABASE_URL is not set: there is nothing persistent to erase from.", file=sys.stderr)
        return 2
    await pool.open()
    storage = get_artifact_storage()
    try:
        report = await erase_tenant(pool, storage, tenant_id=args.tenant or "", email=args.email or "", dry_run=True)
        print(format_report(report))
        if not args.execute:
            print("\nNothing was changed. Add --execute to erase.")
            return 0
        if not args.yes and input(f"\nType the tenant id ({report.tenant_id}) to erase it: ").strip() != report.tenant_id:
            print("Not confirmed. Nothing was changed.")
            return 1
        report = await erase_tenant(pool, storage, tenant_id=report.tenant_id, dry_run=False)
        print("\n" + format_report(report))
        return 0
    except (ErasureRefused, LookupError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
