"""Tests for P12-S3: persistent shortlist — table, API.

Covers:
- add_manual_item / remove_item domain functions (happy path + blank title, wrong project)
- Routes: add / list / remove; removed items leave the default list but stay resolvable by id
- Items of another project are not returned
- No route replaces or clears a shortlist in bulk (D094)
- PostgresShortlistRepository SQL shape against a mocked pool
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cf_platform.core.postgres_project_repos import PostgresShortlistRepository
from cf_platform.core.shortlist import (
    InMemoryShortlistRepository,
    ShortlistItem,
    ShortlistItemNotFoundError,
    add_manual_item,
    remove_item,
)
from src.main import app
from tests.cf_platform.p12_helpers import p12_env


def _mock_pool(fetchone=None, fetchall=None):
    """Build a MagicMock AsyncConnectionPool whose cursor returns fetchone/fetchall."""
    cursor = AsyncMock()
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    conn = MagicMock()
    conn.cursor.return_value.__aenter__.return_value = cursor
    conn.cursor.return_value.__aexit__.return_value = None
    conn.commit = AsyncMock()
    pool = MagicMock()
    pool.closed = False
    pool.connection.return_value.__aenter__.return_value = conn
    pool.connection.return_value.__aexit__.return_value = None
    return pool, cursor, conn


class TestShortlistFunctions:
    @pytest.mark.asyncio
    async def test_add_manual_item_records_origin(self):
        """A hand-entered idea is stored as 'manual' with its source, notes and discovery date."""
        repo = InMemoryShortlistRepository()
        item = await add_manual_item(
            "operator", "p1", "  Why rents rise  ", repo, summary="A look at supply", source="a report", notes="timely"
        )
        assert item.title == "Why rents rise"
        assert item.discovery_method == "manual"
        assert item.source == "a report"
        assert item.evidence == {"notes": "timely"}
        assert item.kpis == {} and item.research_run_id is None
        assert item.tenant_id == "operator" and item.discovered_at is not None

    @pytest.mark.asyncio
    async def test_add_manual_item_rejects_blank_title(self):
        """A blank title raises ValueError and nothing is stored."""
        repo = InMemoryShortlistRepository()
        with pytest.raises(ValueError):
            await add_manual_item("operator", "p1", "  ", repo)
        assert await repo.list_for_project("p1") == []

    @pytest.mark.asyncio
    async def test_remove_is_soft_and_idempotent(self):
        """Removing hides the item from the default list but keeps it resolvable by id."""
        repo = InMemoryShortlistRepository()
        item = await add_manual_item("operator", "p1", "Idea", repo)
        removed = await remove_item("p1", item.item_id, repo)
        assert removed.removed_at is not None
        assert await repo.list_for_project("p1") == []
        assert (await repo.get(item.item_id)).title == "Idea"
        assert [i.item_id for i in await repo.list_for_project("p1", include_removed=True)] == [item.item_id]
        assert (await remove_item("p1", item.item_id, repo)).removed_at == removed.removed_at

    @pytest.mark.asyncio
    async def test_remove_from_wrong_project_raises(self):
        """An item cannot be removed through another project."""
        repo = InMemoryShortlistRepository()
        item = await add_manual_item("operator", "p1", "Idea", repo)
        with pytest.raises(ShortlistItemNotFoundError):
            await remove_item("p2", item.item_id, repo)
        assert (await repo.get(item.item_id)).removed_at is None


class TestShortlistRoutes:
    def test_add_and_list(self):
        """POST adds an item; GET lists it with its origin fields and a zero run count."""
        with p12_env() as env:
            pid = env.create_project()
            item_id = env.add_item(pid, "Why rents rise", summary="Supply", source="a report", notes="timely")

            items = env.client.get(f"/platform/projects/{pid}/shortlist").json()
            assert len(items) == 1
            item = items[0]
            assert item["item_id"] == item_id
            assert (item["title"], item["summary"], item["source"]) == ("Why rents rise", "Supply", "a report")
            assert item["discovery_method"] == "manual"
            assert item["evidence"] == {"notes": "timely"}
            assert item["discovered_at"] and item["run_count"] == 0

    def test_blank_title_rejected(self):
        """A missing or whitespace-only title is a 422."""
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.post(f"/platform/projects/{pid}/shortlist", json={"title": ""}).status_code == 422
            assert env.client.post(f"/platform/projects/{pid}/shortlist", json={"title": "   "}).status_code == 422

    def test_remove_excludes_from_list_but_stays_resolvable(self):
        """DELETE soft-removes: gone from the list, still readable by id with removed_at set."""
        with p12_env() as env:
            pid = env.create_project()
            keep = env.add_item(pid, "Keep")
            drop = env.add_item(pid, "Drop")

            assert env.client.delete(f"/platform/projects/{pid}/shortlist/{drop}").status_code == 204
            assert [i["item_id"] for i in env.client.get(f"/platform/projects/{pid}/shortlist").json()] == [keep]

            r = env.client.get(f"/platform/projects/{pid}/shortlist/{drop}")
            assert r.status_code == 200
            assert r.json()["removed_at"] is not None

    def test_remove_unknown_item_is_404(self):
        """Removing an item that does not exist is a 404."""
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.delete(f"/platform/projects/{pid}/shortlist/nope").status_code == 404

    def test_other_projects_items_not_returned(self):
        """A project's shortlist never shows, resolves or removes another project's items."""
        with p12_env() as env:
            mine = env.create_project("Mine")
            theirs = env.create_project("Theirs")
            foreign = env.add_item(theirs, "Their idea")
            env.add_item(mine, "My idea")

            assert [i["title"] for i in env.client.get(f"/platform/projects/{mine}/shortlist").json()] == ["My idea"]
            assert env.client.get(f"/platform/projects/{mine}/shortlist/{foreign}").status_code == 404
            assert env.client.delete(f"/platform/projects/{mine}/shortlist/{foreign}").status_code == 404
            assert len(env.client.get(f"/platform/projects/{theirs}/shortlist").json()) == 1

    def test_unknown_project_is_404(self):
        """Shortlist routes on an unknown project are a 404."""
        with p12_env() as env:
            assert env.client.get("/platform/projects/nope/shortlist").status_code == 404
            assert env.client.post("/platform/projects/nope/shortlist", json={"title": "x"}).status_code == 404

    def test_no_bulk_replace_or_clear(self):
        """Nothing replaces or clears the whole shortlist: PUT/PATCH/DELETE on the collection are 405."""
        with p12_env() as env:
            pid = env.create_project()
            env.add_item(pid)
            url = f"/platform/projects/{pid}/shortlist"
            assert env.client.put(url, json=[]).status_code == 405
            assert env.client.patch(url, json=[]).status_code == 405
            assert env.client.delete(url).status_code == 405
            assert len(env.client.get(url).json()) == 1

    def test_shortlist_routes_are_exactly_the_five_expected(self):
        """The shortlist surface is list, add, read-one, edit-one, remove-one — nothing bulk (D094)."""
        found = {
            (method.upper(), path)
            for path, operations in app.openapi()["paths"].items()
            if "/shortlist" in path
            for method in operations
        }
        base = "/platform/projects/{project_id}/shortlist"
        assert found == {
            ("GET", base),
            ("POST", base),
            ("GET", base + "/{item_id}"),
            ("PATCH", base + "/{item_id}"),
            ("DELETE", base + "/{item_id}"),
        }


class TestPostgresShortlistRepository:
    def _item(self) -> ShortlistItem:
        """Build a sample ShortlistItem."""
        now = datetime.now(UTC)
        return ShortlistItem(
            item_id="i1", tenant_id="operator", project_id="p1", title="Idea",
            discovery_method="manual", discovered_at=now, created_at=now,
        )

    @pytest.mark.asyncio
    async def test_add_inserts_one_row(self):
        """add() issues a single INSERT INTO shortlist_items and commits."""
        pool, cursor, conn = _mock_pool()
        item = self._item()
        assert await PostgresShortlistRepository(pool).add(item) == item
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO shortlist_items" in sql
        assert params[:4] == ("i1", "operator", "p1", "Idea")
        conn.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_excludes_removed_by_default(self):
        """list_for_project filters removed_at IS NULL unless include_removed is set."""
        pool, cursor, _ = _mock_pool(fetchall=[])
        repo = PostgresShortlistRepository(pool)
        await repo.list_for_project("p1")
        assert "removed_at IS NULL" in cursor.execute.call_args[0][0]
        await repo.list_for_project("p1", include_removed=True)
        assert "removed_at IS NULL" not in cursor.execute.call_args[0][0]

    @pytest.mark.asyncio
    async def test_mark_removed_is_an_update_not_a_delete(self):
        """mark_removed sets removed_at with an UPDATE; a missing row raises."""
        item = self._item()
        row = (
            item.item_id, item.tenant_id, item.project_id, item.title, item.summary, item.discovery_method,
            item.source, item.evidence, item.kpis, item.research_run_id, item.discovered_at,
            datetime.now(UTC), item.created_at,
        )
        pool, cursor, _ = _mock_pool(fetchone=row)
        removed = await PostgresShortlistRepository(pool).mark_removed("i1", datetime.now(UTC))
        sql = cursor.execute.call_args[0][0]
        assert "UPDATE shortlist_items SET removed_at" in sql and "DELETE" not in sql
        assert removed.removed_at is not None

        pool, _, _ = _mock_pool(fetchone=None)
        with pytest.raises(ShortlistItemNotFoundError):
            await PostgresShortlistRepository(pool).mark_removed("missing", datetime.now(UTC))

    @pytest.mark.asyncio
    async def test_link_run_inserts_one_link_per_item_in_order(self):
        """link_run writes (run_id, item_id, position) per item, ignoring duplicates."""
        pool, cursor, _ = _mock_pool()
        await PostgresShortlistRepository(pool).link_run("r1", ["a", "b"])
        calls = [call.args for call in cursor.execute.call_args_list]
        assert [params for _, params in calls] == [("r1", "a", 0), ("r1", "b", 1)]
        assert all("ON CONFLICT (run_id, item_id) DO NOTHING" in sql for sql, _ in calls)
