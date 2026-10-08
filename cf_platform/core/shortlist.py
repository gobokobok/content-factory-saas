"""Persistent project shortlist (Sprint P12, D094).

Each project has one shortlist of content ideas. Items are only ever added —
by hand now, by research from P15 — and only leave when the operator removes
one. Removal is a soft delete (`removed_at`), so a run created from an item
keeps a valid reference. Every item keeps its origin: discovery method, source,
evidence, KPIs, the date it was discovered and the research run it came from.

There is deliberately no bulk replace or clear on the repository: research adds
to the shortlist, it never rewrites it.

Persistence sits behind the `ShortlistRepository` Protocol (in-memory fallback
here, Postgres in postgres_project_repos.py). The functions below are pure
async and take their repository explicitly (D040).
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel

DiscoveryMethod = Literal["manual", "trend", "competitor"]


class ShortlistItemNotFoundError(Exception):
    """Raised when an item_id has no corresponding ShortlistItem in the repository."""


class ShortlistItemUnavailableError(Exception):
    """Raised when a run is requested from an item that is removed or in another project."""


class ShortlistItem(BaseModel):
    """One content idea on a project's shortlist, with where it came from."""

    item_id: str
    tenant_id: str
    project_id: str
    title: str
    summary: str = ""
    discovery_method: DiscoveryMethod
    source: str | None = None
    evidence: dict[str, Any] = {}
    kpis: dict[str, Any] = {}
    research_run_id: str | None = None
    discovered_at: datetime
    removed_at: datetime | None = None
    created_at: datetime


class ShortlistRepository(Protocol):
    """Persistence interface for shortlist items and their links to runs."""

    async def add(self, item: ShortlistItem) -> ShortlistItem:
        """Insert item. Returns the stored record."""
        ...

    async def get(self, item_id: str) -> ShortlistItem:
        """Return the item for item_id, removed or not. Raises ShortlistItemNotFoundError if absent."""
        ...

    async def list_for_project(self, project_id: str, include_removed: bool = False) -> list[ShortlistItem]:
        """Return project_id's items, most recently discovered first."""
        ...

    async def mark_removed(self, item_id: str, removed_at: datetime) -> ShortlistItem:
        """Set removed_at on the item. Raises ShortlistItemNotFoundError if absent."""
        ...

    async def update(self, item: ShortlistItem) -> ShortlistItem:
        """Overwrite the editable fields (title, summary, source, evidence) of an existing item."""
        ...

    async def link_run(self, run_id: str, item_ids: list[str]) -> None:
        """Record that run_id was created from item_ids, keeping their order."""
        ...

    async def items_for_run(self, run_id: str) -> list[ShortlistItem]:
        """Return the items run_id was created from, in the order they were selected."""
        ...

    async def run_counts(self, project_id: str) -> dict[str, int]:
        """Return {item_id: number of runs created from it} for project_id's items that have runs."""
        ...


class InMemoryShortlistRepository:
    """In-memory ShortlistRepository — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty store."""
        self._items: dict[str, ShortlistItem] = {}
        self._links: dict[str, list[str]] = {}

    async def add(self, item: ShortlistItem) -> ShortlistItem:
        """Insert item. Returns the stored record."""
        self._items[item.item_id] = item
        return item

    async def get(self, item_id: str) -> ShortlistItem:
        """Return the item for item_id, removed or not. Raises ShortlistItemNotFoundError if absent."""
        try:
            return self._items[item_id]
        except KeyError:
            raise ShortlistItemNotFoundError(f"Shortlist item not found: {item_id}") from None

    async def list_for_project(self, project_id: str, include_removed: bool = False) -> list[ShortlistItem]:
        """Return project_id's items, most recently discovered first."""
        items = [
            item
            for item in self._items.values()
            if item.project_id == project_id and (include_removed or item.removed_at is None)
        ]
        return sorted(items, key=lambda item: item.discovered_at, reverse=True)

    async def mark_removed(self, item_id: str, removed_at: datetime) -> ShortlistItem:
        """Set removed_at on the item. Raises ShortlistItemNotFoundError if absent."""
        item = await self.get(item_id)
        updated = item.model_copy(update={"removed_at": removed_at})
        self._items[item_id] = updated
        return updated

    async def update(self, item: ShortlistItem) -> ShortlistItem:
        """Overwrite the stored item. Raises ShortlistItemNotFoundError if absent."""
        await self.get(item.item_id)
        self._items[item.item_id] = item
        return item

    async def link_run(self, run_id: str, item_ids: list[str]) -> None:
        """Record that run_id was created from item_ids, keeping their order."""
        linked = self._links.setdefault(run_id, [])
        for item_id in item_ids:
            if item_id not in linked:
                linked.append(item_id)

    async def items_for_run(self, run_id: str) -> list[ShortlistItem]:
        """Return the items run_id was created from, in the order they were selected."""
        return [self._items[item_id] for item_id in self._links.get(run_id, []) if item_id in self._items]

    async def run_counts(self, project_id: str) -> dict[str, int]:
        """Return {item_id: number of runs created from it} for project_id's items that have runs."""
        counts: dict[str, int] = {}
        for item_ids in self._links.values():
            for item_id in item_ids:
                item = self._items.get(item_id)
                if item is not None and item.project_id == project_id:
                    counts[item_id] = counts.get(item_id, 0) + 1
        return counts


async def add_manual_item(
    tenant_id: str,
    project_id: str,
    title: str,
    repository: ShortlistRepository,
    *,
    summary: str = "",
    source: str | None = None,
    notes: str | None = None,
) -> ShortlistItem:
    """Add a hand-entered idea to project_id's shortlist and return it.

    `notes` is stored as `evidence["notes"]` — the same field research fills
    with why an idea is trending. Raises ValueError when title is blank.
    """
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("A shortlist item needs a title")
    now = datetime.now(UTC)
    clean_notes = (notes or "").strip()
    item = ShortlistItem(
        item_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        project_id=project_id,
        title=clean_title,
        summary=summary.strip(),
        discovery_method="manual",
        source=(source or "").strip() or None,
        evidence={"notes": clean_notes} if clean_notes else {},
        discovered_at=now,
        created_at=now,
    )
    return await repository.add(item)


async def update_item(
    project_id: str,
    item_id: str,
    repository: ShortlistRepository,
    *,
    title: str | None = None,
    summary: str | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> ShortlistItem:
    """Edit an idea's title, summary, source or notes; only the fields supplied change.

    An empty `source` or `notes` clears it. Raises ValueError for a blank title,
    ShortlistItemNotFoundError when the item is absent or belongs to another project,
    and ShortlistItemUnavailableError for an item removed from the shortlist.
    """
    item = await repository.get(item_id)
    if item.project_id != project_id:
        raise ShortlistItemNotFoundError(f"Shortlist item not found: {item_id}")
    if item.removed_at is not None:
        raise ShortlistItemUnavailableError(f"Shortlist item {item_id} was removed from the shortlist")
    changes: dict[str, Any] = {}
    if title is not None:
        if not title.strip():
            raise ValueError("A shortlist item needs a title")
        changes["title"] = title.strip()
    if summary is not None:
        changes["summary"] = summary.strip()
    if source is not None:
        changes["source"] = source.strip() or None
    if notes is not None:
        evidence = dict(item.evidence)
        if notes.strip():
            evidence["notes"] = notes.strip()
        else:
            evidence.pop("notes", None)
        changes["evidence"] = evidence
    return await repository.update(item.model_copy(update=changes))


async def remove_item(project_id: str, item_id: str, repository: ShortlistRepository) -> ShortlistItem:
    """Soft-remove item_id from project_id's shortlist. Idempotent.

    Raises ShortlistItemNotFoundError when the item does not exist or belongs
    to another project.
    """
    item = await repository.get(item_id)
    if item.project_id != project_id:
        raise ShortlistItemNotFoundError(f"Shortlist item not found: {item_id}")
    if item.removed_at is not None:
        return item
    return await repository.mark_removed(item_id, datetime.now(UTC))


async def resolve_items_for_run(
    project_id: str,
    item_ids: list[str],
    repository: ShortlistRepository,
) -> list[ShortlistItem]:
    """Return the items a new run in project_id may be created from, in the given order.

    Duplicate ids are collapsed. Raises ValueError when item_ids is empty,
    ShortlistItemNotFoundError for an unknown id, and ShortlistItemUnavailableError
    for an item that was removed or belongs to another project.
    """
    unique_ids = list(dict.fromkeys(item_ids))
    if not unique_ids:
        raise ValueError("A run is created from at least one shortlist item")
    items: list[ShortlistItem] = []
    for item_id in unique_ids:
        item = await repository.get(item_id)
        if item.project_id != project_id:
            raise ShortlistItemUnavailableError(f"Shortlist item {item_id} belongs to another project")
        if item.removed_at is not None:
            raise ShortlistItemUnavailableError(f"Shortlist item {item_id} was removed from the shortlist")
        items.append(item)
    return items


def build_idea_context(items: list[ShortlistItem]) -> dict[str, Any]:
    """Combine the selected items into the inputs idea-to-script takes.

    One item: its title is the idea and its summary the single supporting point.
    Several: the titles are joined into one idea title and each item contributes
    a "title — summary" supporting point, so every selected idea reaches the
    script writer. Returns {"idea_title": str, "supporting_points": list[str]}.
    """
    if not items:
        return {"idea_title": "", "supporting_points": []}
    if len(items) == 1:
        item = items[0]
        return {
            "idea_title": item.title,
            "supporting_points": [item.summary] if item.summary else [],
        }
    return {
        "idea_title": " + ".join(item.title for item in items),
        "supporting_points": [
            f"{item.title} — {item.summary}" if item.summary else item.title for item in items
        ],
    }
