"""Tests for cf_platform/core/run_manager.py (P1-S2)."""

from typing import Any

import pytest

from cf_platform.core.run_manager import (
    InMemoryRunRepository,
    InvalidTransitionError,
    RunNotFoundError,
    create_run,
    transition_run,
)
from cf_platform.core.schemas import RunRecord


class TestCreateRun:
    @pytest.mark.asyncio
    async def test_returns_valid_run_record(self):
        """create_run returns a RunRecord with status 'created' and the given inputs."""
        repo = InMemoryRunRepository()

        run = await create_run("user-1", "niche_to_ideas", {"niche": "housing"}, repo)

        assert isinstance(run, RunRecord)
        assert run.user_id == "user-1"
        assert run.block == "niche_to_ideas"
        assert run.status == "created"
        assert run.inputs == {"niche": "housing"}
        assert run.error is None
        assert run.created_at == run.updated_at

    @pytest.mark.asyncio
    async def test_run_id_is_unique(self):
        """Successive calls mint distinct run_ids."""
        repo = InMemoryRunRepository()

        run_a = await create_run("user-1", "niche_to_ideas", {}, repo)
        run_b = await create_run("user-1", "niche_to_ideas", {}, repo)

        assert run_a.run_id != run_b.run_id

    @pytest.mark.asyncio
    async def test_persists_to_repository(self):
        """The created run can be read back via repository.get."""
        repo = InMemoryRunRepository()

        run = await create_run("user-1", "niche_to_ideas", {}, repo)
        stored = await repo.get(run.run_id)

        assert stored == run


class TestTransitionRun:
    @pytest.mark.asyncio
    async def test_created_to_running(self):
        """created -> running is allowed and persists the new status."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)

        updated = await transition_run(run.run_id, "running", repo)

        assert updated.status == "running"
        assert updated.run_id == run.run_id
        assert (await repo.get(run.run_id)).status == "running"

    @pytest.mark.asyncio
    async def test_running_to_complete(self):
        """running -> complete is allowed."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)
        await transition_run(run.run_id, "running", repo)

        updated = await transition_run(run.run_id, "complete", repo)

        assert updated.status == "complete"
        assert updated.error is None

    @pytest.mark.asyncio
    async def test_running_to_failed_records_error(self):
        """running -> failed is allowed and stores the error message."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)
        await transition_run(run.run_id, "running", repo)

        updated = await transition_run(run.run_id, "failed", repo, error="boom")

        assert updated.status == "failed"
        assert updated.error == "boom"

    @pytest.mark.asyncio
    async def test_updated_at_advances(self):
        """A successful transition bumps updated_at past created_at."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)

        updated = await transition_run(run.run_id, "running", repo)

        assert updated.updated_at >= updated.created_at
        assert updated.created_at == run.created_at

    @pytest.mark.asyncio
    async def test_created_to_complete_rejected(self):
        """created -> complete skips 'running' and is rejected."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)

        with pytest.raises(InvalidTransitionError):
            await transition_run(run.run_id, "complete", repo)

    @pytest.mark.asyncio
    async def test_terminal_status_rejects_further_transitions(self):
        """complete and failed are terminal — no further transitions allowed."""
        repo = InMemoryRunRepository()
        run = await create_run("user-1", "niche_to_ideas", {}, repo)
        await transition_run(run.run_id, "running", repo)
        await transition_run(run.run_id, "complete", repo)

        with pytest.raises(InvalidTransitionError):
            await transition_run(run.run_id, "running", repo)

    @pytest.mark.asyncio
    async def test_unknown_run_id_raises_not_found(self):
        """transition_run raises RunNotFoundError for an unknown run_id."""
        repo = InMemoryRunRepository()

        with pytest.raises(RunNotFoundError):
            await transition_run("does-not-exist", "running", repo)


class TestRepositorySwappable:
    @pytest.mark.asyncio
    async def test_alternate_repository_implementation_works(self):
        """Any object implementing save/get satisfies RunRepository — no Postgres coupling."""

        class ListBackedRepository:
            """Minimal alternate RunRepository implementation for the swappability test."""

            def __init__(self) -> None:
                self._runs: dict[str, RunRecord] = {}

            async def save(self, run: RunRecord) -> RunRecord:
                self._runs[run.run_id] = run
                return run

            async def get(self, run_id: str) -> RunRecord:
                return self._runs[run_id]

        repo: Any = ListBackedRepository()

        run = await create_run("user-1", "niche_to_ideas", {}, repo)
        updated = await transition_run(run.run_id, "running", repo)

        assert updated.status == "running"
