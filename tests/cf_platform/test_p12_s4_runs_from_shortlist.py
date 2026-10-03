"""Tests for P12-S4: create a content run from shortlist item(s).

Covers:
- build_idea_context: one item, several items, items without a summary
- POST /platform/projects/{id}/runs with 1 and with 2 items: run row, links, name
- Unknown, removed and other-project item ids are rejected; an empty selection is a 422
- Links readable from the run (GET /platform/studio/runs/{run_id}/context) and counted per item
- A removed item stays resolvable from a run created before its removal
- POST /platform/blocks/idea-to-script with run_id: keeps the run id, uses the project
  niche, does not mark the run complete; unknown run_id is a 404; omitting it still mints a run
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from cf_platform.core.artifact_manager import InMemoryArtifactStorage
from cf_platform.core.config import PlatformSettings, get_platform_settings
from cf_platform.core.shortlist import ShortlistItem, build_idea_context
from cf_platform.interfaces.dependencies import get_artifact_storage, get_graph_checkpointer
from cf_platform.workers.script_packager import ScriptArtifact
from src.main import app
from tests.cf_platform.p12_helpers import p12_env

_BLOCKS = "cf_platform.interfaces.routes.blocks"


def _item(title: str, summary: str = "") -> ShortlistItem:
    """Build a ShortlistItem with just a title and summary."""
    now = datetime.now(UTC)
    return ShortlistItem(
        item_id=title, tenant_id="operator", project_id="p1", title=title, summary=summary,
        discovery_method="manual", discovered_at=now, created_at=now,
    )


class TestBuildIdeaContext:
    def test_single_item(self):
        """One item: its title is the idea, its summary the supporting point."""
        context = build_idea_context([_item("Why rents rise", "Supply fell")])
        assert context == {"idea_title": "Why rents rise", "supporting_points": ["Supply fell"]}

    def test_single_item_without_summary(self):
        """No summary means no supporting points, not an empty string."""
        assert build_idea_context([_item("Why rents rise")])["supporting_points"] == []

    def test_several_items_are_combined(self):
        """Titles are joined and every item contributes a 'title — summary' point."""
        context = build_idea_context([_item("Rents", "Supply fell"), _item("Zoning")])
        assert context["idea_title"] == "Rents + Zoning"
        assert context["supporting_points"] == ["Rents — Supply fell", "Zoning"]

    def test_no_items(self):
        """An empty selection yields an empty context rather than raising."""
        assert build_idea_context([]) == {"idea_title": "", "supporting_points": []}


class TestCreateRunFromShortlist:
    def test_one_item(self):
        """A run created from one item sits in the project, named after the idea, linked to it."""
        with p12_env() as env:
            pid = env.create_project()
            item_id = env.add_item(pid, "Why rents rise", summary="Supply fell")

            r = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item_id]})
            assert r.status_code == 201
            run = r.json()
            assert run["name"] == "Why rents rise" and run["status"] == "created"

            assert [x["run_id"] for x in env.client.get(f"/platform/projects/{pid}/runs").json()] == [run["run_id"]]

            context = env.client.get(f"/platform/studio/runs/{run['run_id']}/context").json()
            assert [i["item_id"] for i in context["items"]] == [item_id]
            assert context["idea_title"] == "Why rents rise"
            assert context["supporting_points"] == ["Supply fell"]
            assert context["project"]["project_id"] == pid
            assert context["project"]["niche"] == "housing economics"

    def test_two_items_combined_in_selection_order(self):
        """Two items: both linked, in the order selected, with a combined idea context."""
        with p12_env() as env:
            pid = env.create_project()
            first = env.add_item(pid, "Rents", summary="Supply fell")
            second = env.add_item(pid, "Zoning")

            r = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [second, first, second]})
            assert r.status_code == 201
            context = env.client.get(f"/platform/studio/runs/{r.json()['run_id']}/context").json()
            assert [i["item_id"] for i in context["items"]] == [second, first]  # duplicate collapsed
            assert context["idea_title"] == "Zoning + Rents"
            assert context["supporting_points"] == ["Zoning", "Rents — Supply fell"]

    def test_item_run_counts(self):
        """One item can feed several runs; each item reports how many."""
        with p12_env() as env:
            pid = env.create_project()
            used = env.add_item(pid, "Used twice")
            unused = env.add_item(pid, "Unused")
            for _ in range(2):
                assert env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [used]}).status_code == 201

            counts = {i["item_id"]: i["run_count"] for i in env.client.get(f"/platform/projects/{pid}/shortlist").json()}
            assert counts == {used: 2, unused: 0}

    def test_unknown_item_rejected(self):
        """An unknown item id is a 404 and no run is created."""
        with p12_env() as env:
            pid = env.create_project()
            r = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": ["nope"]})
            assert r.status_code == 404
            assert env.client.get(f"/platform/projects/{pid}/runs").json() == []

    def test_removed_item_rejected(self):
        """A removed item is a 409 — even alongside a valid one — and no run is created."""
        with p12_env() as env:
            pid = env.create_project()
            good = env.add_item(pid, "Good")
            removed = env.add_item(pid, "Removed")
            env.client.delete(f"/platform/projects/{pid}/shortlist/{removed}")

            r = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [good, removed]})
            assert r.status_code == 409
            assert env.client.get(f"/platform/projects/{pid}/runs").json() == []

    def test_other_projects_item_rejected(self):
        """An item from another project cannot seed a run here."""
        with p12_env() as env:
            mine = env.create_project("Mine")
            theirs = env.create_project("Theirs")
            foreign = env.add_item(theirs, "Their idea")
            assert env.client.post(f"/platform/projects/{mine}/runs", json={"item_ids": [foreign]}).status_code == 409

    def test_empty_selection_rejected(self):
        """A run needs at least one item: an empty or missing list is a 422."""
        with p12_env() as env:
            pid = env.create_project()
            assert env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": []}).status_code == 422
            assert env.client.post(f"/platform/projects/{pid}/runs", json={}).status_code == 422

    def test_link_survives_item_removal(self):
        """Removing an item later does not break the run that was created from it."""
        with p12_env() as env:
            pid = env.create_project()
            item_id = env.add_item(pid, "Why rents rise")
            run_id = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item_id]}).json()["run_id"]
            env.client.delete(f"/platform/projects/{pid}/shortlist/{item_id}")

            context = env.client.get(f"/platform/studio/runs/{run_id}/context").json()
            assert [i["item_id"] for i in context["items"]] == [item_id]
            assert context["items"][0]["removed_at"] is not None

    def test_context_of_unknown_run_is_404(self):
        """A run with no row (pre-P12, not yet imported) has no context."""
        with p12_env() as env:
            assert env.client.get("/platform/studio/runs/nope/context").status_code == 404


class _IdeaToScriptHarness:
    """Stubs the idea-to-script graph so the route's run handling can be tested in isolation."""

    def __init__(self) -> None:
        """Prepare the patches and the captured-call slots."""
        self.states: list = []
        self.thread_ids: list[str] = []

    def __enter__(self) -> "_IdeaToScriptHarness":
        """Install the dependency overrides and patches."""
        platform_settings = PlatformSettings.model_construct(ANTHROPIC_API_KEY="sk-ant-fake", DATABASE_URL="")
        self._overrides = {
            get_platform_settings: lambda: platform_settings,
            get_artifact_storage: lambda: InMemoryArtifactStorage(),
            get_graph_checkpointer: lambda: MemorySaver(),
        }
        app.dependency_overrides.update(self._overrides)

        async def _run_graph(graph, state, thread_id):
            self.states.append(state)
            self.thread_ids.append(thread_id)
            result = MagicMock()
            result.artifacts = {"script": "users/operator/runs/x/script/script@v1.json"}
            result.iteration = 1
            return result

        script = ScriptArtifact(
            idea_title="t", niche="n", script="A generated script.", word_count=3, generated_at=datetime.now(UTC)
        )
        self._patches = [
            patch(f"{_BLOCKS}.build_idea_to_script_graph", return_value=MagicMock()),
            patch(f"{_BLOCKS}.run_graph", side_effect=_run_graph),
            patch(f"{_BLOCKS}.read_artifact", AsyncMock(return_value=(None, script.model_dump(mode="json")))),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Remove the patches and dependency overrides."""
        for p in self._patches:
            p.stop()
        for dependency in self._overrides:
            app.dependency_overrides.pop(dependency, None)


class TestIdeaToScriptIntoExistingRun:
    @pytest.mark.asyncio
    async def test_generates_into_the_run_with_project_niche(self):
        """With run_id the script lands in that run and the project's niche is used."""
        with p12_env() as env, _IdeaToScriptHarness() as harness:
            pid = env.create_project("Housing", "housing economics")
            item_id = env.add_item(pid, "Why rents rise", summary="Supply fell")
            run_id = env.client.post(f"/platform/projects/{pid}/runs", json={"item_ids": [item_id]}).json()["run_id"]

            r = env.client.post(
                "/platform/blocks/idea-to-script",
                json={"idea_title": "Why rents rise", "run_id": run_id, "supporting_points": ["Supply fell"]},
            )
            assert r.status_code == 200, r.text
            assert r.json()["run_id"] == run_id
            assert r.json()["script"] == "A generated script."

            state = harness.states[0]
            assert state.run_id == run_id
            assert state.inputs["niche"] == "housing economics"
            assert state.inputs["supporting_points"] == ["Supply fell"]

            run = await env.runs.get(run_id)
            assert run.status == "running"  # not 'complete' — a script is not a finished video
            assert run.project_id == pid
            assert len(await env.runs.list_runs()) == 1  # no second run was minted

    def test_regenerating_uses_a_fresh_checkpoint_thread(self):
        """A second generation into the same run works and never reuses a checkpoint thread."""
        with p12_env() as env, _IdeaToScriptHarness() as harness:
            pid = env.create_project()
            run_id = env.client.post(
                f"/platform/projects/{pid}/runs", json={"item_ids": [env.add_item(pid)]}
            ).json()["run_id"]
            for _ in range(2):
                r = env.client.post("/platform/blocks/idea-to-script", json={"idea_title": "x", "run_id": run_id})
                assert r.status_code == 200, r.text
            assert len(set(harness.thread_ids)) == 2
            assert all(thread_id.startswith(f"{run_id}:idea_to_script:") for thread_id in harness.thread_ids)

    def test_request_niche_wins_over_project_niche(self):
        """A niche typed for this generation overrides the project's."""
        with p12_env() as env, _IdeaToScriptHarness() as harness:
            pid = env.create_project("Housing", "housing economics")
            run_id = env.client.post(
                f"/platform/projects/{pid}/runs", json={"item_ids": [env.add_item(pid)]}
            ).json()["run_id"]
            env.client.post("/platform/blocks/idea-to-script", json={"idea_title": "x", "run_id": run_id, "niche": "rents"})
            assert harness.states[0].inputs["niche"] == "rents"

    def test_unknown_run_id_is_404(self):
        """An unknown run_id is a 404 and the graph is never run."""
        with p12_env() as env, _IdeaToScriptHarness() as harness:
            r = env.client.post("/platform/blocks/idea-to-script", json={"idea_title": "x", "run_id": "nope"})
            assert r.status_code == 404
            assert harness.states == []

    @pytest.mark.asyncio
    async def test_without_run_id_still_mints_a_run(self):
        """Omitting run_id keeps the pre-P12 behaviour: a new run in the default project, completed."""
        with p12_env() as env, _IdeaToScriptHarness() as harness:
            r = env.client.post("/platform/blocks/idea-to-script", json={"idea_title": "x"})
            assert r.status_code == 200, r.text
            run = await env.runs.get(r.json()["run_id"])
            assert (run.block, run.status, run.project_id) == ("idea_to_script", "complete", "default")
            assert harness.thread_ids == [run.run_id]
