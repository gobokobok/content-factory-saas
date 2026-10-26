"""Price calibration report (BILL-F3): what the platform charges and reserves, against what the providers billed.

``worker_executions.cost_usd`` and the token columns are never filled (the LLM and TTS clients return text
only), so the database holds no measured cost for LLM, TTS or render calls. What it does hold is *how many*
paid actions ran: every one has a ``usage_entries`` row with the estimate it reserved. The report therefore
works from counts: the operator reads the provider invoices for the same window, passes them as ``--bill kind=USD``,
and gets the implied cost per action beside the configured estimate. Image actions are reported from the actual
cost the image ledger settled at, when the entry has one.
"""

from dataclasses import dataclass, field
from typing import Any

KINDS = ("llm", "tts", "transcription", "image", "render")
# The ENV estimate each kind is reserved at when it has no exact price.
ESTIMATE_SETTING = {
    "llm": "EST_LLM_CALL_USD",
    "tts": "EST_TTS_CALL_USD",
    "transcription": "EST_TRANSCRIPTION_USD",
    "render": "EST_RENDER_USD",
}
HEADROOM = 1.25  # suggested estimate = implied cost x this, so a dearer-than-average action is still covered


@dataclass
class KindRow:
    """One action kind over the window."""

    kind: str
    actions: int = 0  # entries that ran to completion (settled)
    refunded: int = 0
    reserved_usd: float = 0.0  # sum of the estimates the settled entries reserved
    actual_usd: float = 0.0  # sum of actual_usd where the entry carries one
    with_actual: int = 0
    billed_usd: float | None = None  # from --bill
    implied_per_action: float | None = None
    configured_per_action: float | None = None
    suggested_per_action: float | None = None
    notes: list[str] = field(default_factory=list)


def summarise(entries: list[dict[str, Any]], bills: dict[str, float], settings: Any) -> list[KindRow]:
    """Fold usage entries (dicts with kind, status, raw_cost_usd, actual_usd) into one KindRow per kind."""
    rows = {kind: KindRow(kind) for kind in KINDS}
    for entry in entries:
        row = rows.get(entry["kind"])
        if row is None:
            continue
        if entry["status"] == "refunded":
            row.refunded += 1
        elif entry["status"] in ("settled", "metered", "exempt"):
            row.actions += 1
            row.reserved_usd += float(entry["raw_cost_usd"] or 0)
            if entry.get("actual_usd") is not None:
                row.actual_usd += float(entry["actual_usd"])
                row.with_actual += 1
    for kind, row in rows.items():
        name = ESTIMATE_SETTING.get(kind)
        if name:
            row.configured_per_action = float(getattr(settings, name, 0) or 0)
        elif row.actions:
            row.configured_per_action = row.reserved_usd / row.actions
        if kind in bills:
            row.billed_usd = bills[kind]
            if row.actions:
                row.implied_per_action = bills[kind] / row.actions
                row.suggested_per_action = round(row.implied_per_action * HEADROOM, 4)
            else:
                row.notes.append("no actions in the window — nothing to divide the bill by")
        if row.configured_per_action is not None and row.configured_per_action <= 0:
            row.notes.append("configured price is 0: this action is refused for non-owners (BILL-F3)")
        if row.implied_per_action and row.configured_per_action and row.implied_per_action > row.configured_per_action:
            row.notes.append("the providers charged MORE per action than is reserved — raise the estimate")
        if kind == "llm" and row.actions:
            row.notes.append("one 'llm' action is a call of any size: a long script or storyboard costs more than a short one")
    return list(rows.values())


def format_report(rows: list[KindRow], settings: Any, days: int, runs: int) -> str:
    """The report as plain text."""
    lines = [
        f"Price calibration — last {days} days, {runs} runs",
        f"credits: markup x{getattr(settings, 'CREDIT_MARKUP', '?')}, 1 credit = ${getattr(settings, 'CREDIT_VALUE_USD', '?')}; "
        f"daily bound ${getattr(settings, 'CAP_DAILY_SPEND_USD', '?')} per tenant",
        f"images: resolution {getattr(settings, 'IMAGE_RESOLUTION', '?')}, default ${getattr(settings, 'IMAGE_COST_USD', '?')}, "
        f"per model {getattr(settings, 'IMAGE_MODEL_COSTS_USD', {})}",
        "",
        f"{'kind':<14}{'actions':>8}{'refunded':>9}{'reserved $':>11}{'actual $':>10}{'billed $':>10}{'implied/act':>12}{'config/act':>11}{'suggest':>9}",
    ]
    for r in rows:
        def f(value: float | None, digits: int = 4) -> str:
            return "-" if value is None else f"{value:.{digits}f}"
        lines.append(
            f"{r.kind:<14}{r.actions:>8}{r.refunded:>9}{r.reserved_usd:>11.2f}"
            f"{(f(r.actual_usd, 2) if r.with_actual else '-'):>10}{f(r.billed_usd, 2):>10}"
            f"{f(r.implied_per_action):>12}{f(r.configured_per_action):>11}{f(r.suggested_per_action):>9}"
        )
    for r in rows:
        lines += [f"  {r.kind}: {note}" for note in r.notes]
    lines += [
        "",
        "Not measured: worker_executions.cost_usd and the token columns are never filled, so LLM, TTS and render cost",
        "comes from the provider invoices. Pass them with --bill llm=12.40 --bill tts=3.10 (same window) to get the",
        "implied cost per action; set EST_* near the suggestion and keep CREDIT_MARKUP above 1.0 for the margin.",
    ]
    return "\n".join(lines)


async def fetch_entries(pool: Any, days: int) -> tuple[list[dict[str, Any]], int]:
    """The owner-excluded usage entries of the last `days` days, and how many distinct runs they cover."""
    sql = (
        "SELECT kind, status, raw_cost_usd, actual_usd, run_id FROM usage_entries "
        "WHERE created_at >= now() - make_interval(days => %s) AND status <> 'exempt'"
    )
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (days,))
            fetched = await cur.fetchall()
    entries = [
        {"kind": k, "status": st, "raw_cost_usd": raw, "actual_usd": actual, "run_id": run_id}
        for k, st, raw, actual, run_id in fetched
    ]
    return entries, len({e["run_id"] for e in entries if e["run_id"]})
