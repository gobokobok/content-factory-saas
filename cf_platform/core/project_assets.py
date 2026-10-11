"""Project assets — recurring characters, places and objects saved at project level (P-PROJ1, EPIC 57).

A project is one channel. A mascot or a recurring place appears in every animated
run, so it is saved once on the project and the storyboard worker reuses it instead
of inventing a new one each time. Assets live in the project's `config["assets"]`
list; no migration is needed (the config is a JSON document).

A run's continuity entry and a project asset relate by **copy**, not by link:
promoting an entry copies its name, kind and description; editing the project asset
changes later runs only, and a finished run keeps what it was made with.

The asset `id` is a lowercase snake_case slug of its name. It doubles as the
continuity id in a run's bible, which is how the worker's answer is matched back to
the asset it reused.
"""

import re
from datetime import UTC, datetime
from typing import Any

ASSET_KINDS = ("character", "prop", "setting")
MAX_ASSETS = 40
MAX_NAME_CHARS = 80
MAX_DESCRIPTION_CHARS = 1200
CONFIG_KEY = "assets"

_ID_CLEAN = re.compile(r"[^a-z0-9_]+")


class ProjectAssetError(ValueError):
    """Raised for an asset that cannot be saved; the message is safe to show the operator."""


class ProjectAssetNotFoundError(ProjectAssetError):
    """Raised when an asset id is not in the project."""


def slug(name: str) -> str:
    """Lowercase snake_case id for an asset name; '' when nothing usable is left."""
    return _ID_CLEAN.sub("_", str(name or "").strip().lower()).strip("_")


def list_assets(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The project's assets, oldest first; entries that are not well-formed are skipped."""
    raw = (config or {}).get(CONFIG_KEY)
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("id") and item.get("description"):
            out.append(item)
    return out


def _clean(kind: str, name: str, description: str) -> tuple[str, str, str]:
    """Validate and trim the three fields; ProjectAssetError names the first problem."""
    name, description = (name or "").strip(), (description or "").strip()
    if kind not in ASSET_KINDS:
        raise ProjectAssetError(f"Kind must be one of {list(ASSET_KINDS)}.")
    if not name:
        raise ProjectAssetError("Give the asset a name.")
    if len(name) > MAX_NAME_CHARS:
        raise ProjectAssetError(f"The name is limited to {MAX_NAME_CHARS} characters.")
    if not slug(name):
        raise ProjectAssetError("The name needs at least one letter or digit.")
    if not description:
        raise ProjectAssetError("Describe the asset — the description is what keeps it the same in every image.")
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise ProjectAssetError(f"The description is limited to {MAX_DESCRIPTION_CHARS} characters.")
    return kind, name, description


def _unique_id(base: str, taken: set[str]) -> str:
    """`base`, or `base_2`, `base_3`… — the first id not in `taken`."""
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def add_asset(
    config: dict[str, Any] | None,
    *,
    kind: str,
    name: str,
    description: str,
    source_run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new config, the asset) with the asset appended. Config is not mutated."""
    kind, name, description = _clean(kind, name, description)
    assets = list_assets(config)
    if len(assets) >= MAX_ASSETS:
        raise ProjectAssetError(f"A project holds at most {MAX_ASSETS} assets.")
    asset = {
        "id": _unique_id(slug(name), {a["id"] for a in assets}),
        "kind": kind,
        "name": name,
        "description": description,
        "source_run_id": source_run_id,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return {**(config or {}), CONFIG_KEY: [*assets, asset]}, asset


def update_asset(
    config: dict[str, Any] | None,
    asset_id: str,
    *,
    kind: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new config, the asset) with the given fields changed. The id never changes."""
    assets = list_assets(config)
    for i, asset in enumerate(assets):
        if asset["id"] != asset_id:
            continue
        k, n, d = _clean(
            kind if kind is not None else asset.get("kind", ""),
            name if name is not None else asset.get("name", ""),
            description if description is not None else asset.get("description", ""),
        )
        updated = {**asset, "kind": k, "name": n, "description": d}
        assets[i] = updated
        return {**(config or {}), CONFIG_KEY: assets}, updated
    raise ProjectAssetNotFoundError(f"No asset {asset_id!r} in this project.")


def remove_asset(config: dict[str, Any] | None, asset_id: str) -> dict[str, Any]:
    """Return the new config without the asset. Runs already made with it keep their copy."""
    assets = list_assets(config)
    kept = [a for a in assets if a["id"] != asset_id]
    if len(kept) == len(assets):
        raise ProjectAssetNotFoundError(f"No asset {asset_id!r} in this project.")
    return {**(config or {}), CONFIG_KEY: kept}


def prompt_block(config: dict[str, Any] | None) -> str:
    """The assets as the storyboard worker's message section; '' when the project has none."""
    assets = list_assets(config)
    if not assets:
        return ""
    lines = [f'- id "{a["id"]}" ({a.get("kind", "prop")}) {a.get("name", "")}: {a["description"]}' for a in assets]
    return (
        "PROJECT ASSETS — recurring subjects of this channel, already designed. When the narration "
        "needs a character, place or object that is one of these, put it in `continuity` with EXACTLY "
        "that id and use it in the scenes' `entities`; its description is fixed and added in code, so "
        "do not rewrite it and do not invent a second version of it. Use only the assets the narration "
        "needs — an unused asset is simply left out.\n" + "\n".join(lines)
    )


def apply_to_continuity(
    continuity: list[dict[str, Any]], config: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Make every continuity entry that carries a project asset's id exactly that asset.

    The model is asked not to rewrite an asset; this enforces it. Name, kind and
    description are replaced by the project's and the entry is marked with
    `project_asset_id`. Entries that are not project assets are returned unchanged.
    """
    by_id = {a["id"]: a for a in list_assets(config)}
    out: list[dict[str, Any]] = []
    for entry in continuity:
        asset = by_id.get(str(entry.get("id") or ""))
        if asset is None:
            out.append(entry)
            continue
        out.append({
            **entry,
            "kind": asset.get("kind", entry.get("kind", "prop")),
            "name": asset.get("name", entry.get("name", "")),
            "description": asset["description"],
            "project_asset_id": asset["id"],
        })
    return out
