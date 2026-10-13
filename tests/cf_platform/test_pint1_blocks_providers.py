"""P-INT1: blocks and providers (S1, S2), several providers with a default and a model (S3), run provider view (S4)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from cf_platform.core import providers as pv
from cf_platform.core.llm import AnthropicLLM, LLMError, OpenAILLM, build_llm_client
from cf_platform.core.tenant_settings import InMemoryTenantSettingsRepository, TenantSettings
from cf_platform.interfaces.dependencies import get_tenant_settings_repository
from src.main import app

TENANT = "operator"


def platform(**kw) -> SimpleNamespace:
    """Platform settings with every key empty unless given."""
    base = dict(ANTHROPIC_API_KEY="", GEMINI_API_KEY="", DEEPGRAM_API_KEY="", OPENAI_API_KEY="", KIE_API_KEY="",
                PEXELS_API_KEY="", PIXABAY_API_KEY="", YOUTUBE_API_KEY="", IMAGE_PROVIDER="kie",
                KIE_IMAGE_MODEL="kie-default", OPENAI_IMAGE_MODEL="oa-default", OPENAI_LLM_MODEL="gpt-4.1-mini",
                SETTINGS_ENCRYPTION_KEY="x")
    base.update(kw)
    return SimpleNamespace(**base)


# ── S1 / S2: the registry ────────────────────────────────────────────────


class TestRegistry:
    def test_five_blocks_with_the_expected_providers(self):
        assert [b.block_id for b in pv.BLOCKS] == ["llm", "audio", "image", "stock", "destination"]
        by_block = {b.block_id: [p.provider_id for p in b.providers] for b in pv.BLOCKS}
        assert by_block["llm"] == ["anthropic", "openai_llm"]
        assert by_block["audio"] == ["gemini", "deepgram"] and by_block["image"] == ["kie", "openai_image"]
        assert by_block["stock"] == ["pexels", "pixabay"] and by_block["destination"] == ["youtube"]

    def test_every_provider_points_at_a_real_key_service(self):
        from cf_platform.core.integrations import SERVICE_IDS

        assert all(p.service_id in SERVICE_IDS for p in pv.PROVIDERS)

    def test_unknown_names_are_refused(self):
        with pytest.raises(pv.UnknownProviderError):
            pv.get_block("nope")
        with pytest.raises(pv.UnknownProviderError):
            pv.get_provider("nope")


# ── S3: defaults and models ──────────────────────────────────────────────


class TestChoices:
    @pytest.mark.asyncio
    async def test_the_default_is_the_first_provider_with_a_key_until_one_is_chosen(self):
        repo = InMemoryTenantSettingsRepository()
        only_openai = platform(OPENAI_API_KEY="sk-o")
        assert (await pv.resolve_block(repo, TENANT, only_openai, "llm"))["provider_id"] == "openai_llm"
        both = platform(OPENAI_API_KEY="sk-o", ANTHROPIC_API_KEY="sk-a")
        assert (await pv.resolve_block(repo, TENANT, both, "llm"))["provider_id"] == "anthropic"
        await pv.set_block_choice(repo, TENANT, both, "llm", default="openai_llm")
        chosen = await pv.resolve_block(repo, TENANT, both, "llm")
        assert chosen["provider_id"] == "openai_llm" and chosen["model"] == "gpt-4.1-mini" and chosen["api_key"] == "sk-o"

    @pytest.mark.asyncio
    async def test_a_model_is_saved_per_provider_and_can_be_reset(self):
        repo = InMemoryTenantSettingsRepository()
        s = platform(OPENAI_API_KEY="sk-o")
        await pv.set_block_choice(repo, TENANT, s, "llm", model=("openai_llm", "gpt-4.1"))
        await pv.set_block_choice(repo, TENANT, s, "llm", model=("anthropic", "claude-sonnet-4-6"))
        row = await repo.get(TENANT)
        assert pv.model_for(pv.get_provider("openai_llm"), row, s) == "gpt-4.1"
        assert pv.model_for(pv.get_provider("anthropic"), row, s) == "claude-sonnet-4-6"
        await pv.set_block_choice(repo, TENANT, s, "llm", model=("openai_llm", ""))
        assert pv.model_for(pv.get_provider("openai_llm"), await repo.get(TENANT), s) == "gpt-4.1-mini"

    @pytest.mark.asyncio
    async def test_the_image_choice_is_the_p14_setting_so_the_two_views_agree(self):
        repo = InMemoryTenantSettingsRepository()
        s = platform(KIE_API_KEY="k", OPENAI_API_KEY="o")
        await pv.set_block_choice(repo, TENANT, s, "image", default="openai_image")
        row = await repo.get(TENANT)
        assert row.image_provider == "openai" and row.image_model is None
        from cf_platform.core.tenant_settings import resolve_image_config

        assert (await resolve_image_config(repo, TENANT, s)).provider == "openai"
        await pv.set_block_choice(repo, TENANT, s, "image", model=("openai_image", "gpt-image-1"))
        assert (await repo.get(TENANT)).image_model == "gpt-image-1"

    @pytest.mark.asyncio
    async def test_refusals(self):
        repo, s = InMemoryTenantSettingsRepository(), platform()
        with pytest.raises(pv.UnknownProviderError, match="not in"):
            await pv.set_block_choice(repo, TENANT, s, "llm", default="kie")
        with pytest.raises(pv.UnknownProviderError, match="cannot be a default"):
            await pv.set_block_choice(repo, TENANT, s, "destination", default="youtube")
        with pytest.raises(pv.UnknownProviderError, match="searched together"):
            await pv.set_block_choice(repo, TENANT, s, "stock", default="pixabay")
        with pytest.raises(pv.UnknownProviderError, match="no model"):
            await pv.set_block_choice(repo, TENANT, s, "stock", model=("pexels", "x"))

    @pytest.mark.asyncio
    async def test_the_public_view_never_carries_a_key(self):
        repo = InMemoryTenantSettingsRepository()
        await repo.save(TenantSettings(tenant_id=TENANT, api_keys={"openai": {"encrypted": "SECRET-TOKEN", "hint": "abcd"}}))
        view = await pv.public_blocks(repo, TENANT, platform(ANTHROPIC_API_KEY="sk-a"))
        text = str(view)
        assert "SECRET-TOKEN" not in text and "sk-a" not in text
        llm = next(b for b in view["blocks"] if b["block_id"] == "llm")
        openai = next(p for p in llm["providers"] if p["provider_id"] == "openai_llm")
        assert openai["key_source"] == "tenant" and openai["key_hint"] == "abcd" and openai["wired"] == "partial"
        anthropic = next(p for p in llm["providers"] if p["provider_id"] == "anthropic")
        assert anthropic["is_default"] is True and anthropic["key_source"] == "env"


# ── the LLM adapters ─────────────────────────────────────────────────────


class TestAdapters:
    @pytest.mark.asyncio
    async def test_openai_posts_a_chat_completion_and_returns_the_text(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        with patch("cf_platform.core.llm.httpx.AsyncClient", lambda **kw: real(transport=transport, **kw)):
            text = await OpenAILLM("sk-test").complete("SYS", "USER", model="gpt-4.1-mini", max_tokens=64)
        assert text == "hello" and seen["auth"] == "Bearer sk-test"
        assert seen["body"]["model"] == "gpt-4.1-mini" and seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}

    @pytest.mark.asyncio
    async def test_openai_errors_are_readable_and_never_carry_the_key(self):
        transport = httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}}))
        real = httpx.AsyncClient
        with patch("cf_platform.core.llm.httpx.AsyncClient", lambda **kw: real(transport=transport, **kw)):
            with pytest.raises(LLMError) as exc:
                await OpenAILLM("sk-SECRET").complete("s", "u", model="m", max_tokens=8)
        assert "401" in str(exc.value) and "sk-SECRET" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_anthropic_adapter_joins_text_blocks(self):
        client = MagicMock()
        client.messages.create = AsyncMock(return_value=MagicMock(content=[
            MagicMock(type="thinking", text="x"), MagicMock(type="text", text="ans")]))
        with patch("cf_platform.core.llm.anthropic.AsyncAnthropic", return_value=client):
            assert await AnthropicLLM("k").complete("s", "u", model="m", max_tokens=8) == "ans"

    def test_the_factory(self):
        assert isinstance(build_llm_client("openai_llm", "k"), OpenAILLM)
        assert isinstance(build_llm_client("anthropic", "k"), AnthropicLLM)
        with pytest.raises(LLMError):
            build_llm_client("kie", "k")


# ── the routes and the metadata worker choosing its provider ─────────────


class TestRoutes:
    def _client(self, repo):
        from src.config import Settings, get_settings
        from tests.cf_platform.p12_helpers import VALID_ENV

        from cf_platform.core.config import get_platform_settings

        app.dependency_overrides[get_tenant_settings_repository] = lambda: repo
        app.dependency_overrides[get_settings] = lambda: Settings.model_validate(VALID_ENV)
        app.dependency_overrides[get_platform_settings] = lambda: platform()
        return TestClient(app)

    def teardown_method(self):
        from cf_platform.core.config import get_platform_settings
        from src.config import get_settings

        app.dependency_overrides.pop(get_tenant_settings_repository, None)
        app.dependency_overrides.pop(get_settings, None)
        app.dependency_overrides.pop(get_platform_settings, None)

    def test_get_and_put_blocks(self):
        client = self._client(InMemoryTenantSettingsRepository())
        view = client.get("/platform/tenant/blocks").json()
        assert [b["block_id"] for b in view["blocks"]] == ["llm", "audio", "image", "stock", "destination"]
        r = client.put("/platform/tenant/blocks/llm", json={"default": "openai_llm", "model": {"provider": "openai_llm", "model": "gpt-4.1"}})
        assert r.status_code == 200
        llm = next(b for b in r.json()["blocks"] if b["block_id"] == "llm")
        o = next(p for p in llm["providers"] if p["provider_id"] == "openai_llm")
        assert o["is_default"] is True and o["model"] == "gpt-4.1"
        assert client.put("/platform/tenant/blocks/llm", json={"default": "kie"}).status_code == 422
        assert client.put("/platform/tenant/blocks/zzz", json={"default": "kie"}).status_code == 422

    def test_metadata_runs_on_the_default_provider(self):
        from datetime import UTC, datetime

        from cf_platform.core.artifact_manager import InMemoryArtifactStorage
        from cf_platform.core.config import get_platform_settings
        from cf_platform.interfaces.dependencies import get_artifact_storage, get_effective_platform_settings
        from cf_platform.workers.script_packager import ScriptArtifact

        repo, storage = InMemoryTenantSettingsRepository(), InMemoryArtifactStorage()
        asyncio.run(pv.set_block_choice(repo, TENANT, platform(), "llm", default="openai_llm"))
        from cf_platform.core.artifact_manager import write_artifact
        from cf_platform.core.schemas import LineageEnvelope

        asyncio.run(write_artifact(
            storage,
            ScriptArtifact(idea_title="Rents", niche=None, script="Rents rose.", word_count=2, status="ok",
                           generated_at=datetime.now(UTC)),
            name="script", stage="script", run_id="r1", user_id="operator",
            lineage=LineageEnvelope(run_id="r1", worker="script", worker_version="1", prompt_version="v1",
                                    model="none", created_at=datetime.now(UTC)),
        ))
        s = platform(OPENAI_API_KEY="sk-o", ANTHROPIC_API_KEY="sk-a")
        calls = {}

        class FakeLLM:
            async def complete(self, system, user, *, model, max_tokens):
                calls["model"], calls["user"] = model, user
                return '{"title": "T", "description": "D", "tags": ["a"]}'

        from src.config import Settings, get_settings
        from tests.cf_platform.p12_helpers import VALID_ENV

        from cf_platform.core.projects import InMemoryProjectRepository
        from cf_platform.core.run_manager import InMemoryRunRepository
        from cf_platform.interfaces.dependencies import PLATFORM_USER_ID, get_project_repository, get_run_repository

        runs, projects = InMemoryRunRepository(), InMemoryProjectRepository(PLATFORM_USER_ID)
        overrides = {
            get_run_repository: lambda: runs, get_project_repository: lambda: projects,
            get_settings: lambda: Settings.model_validate(VALID_ENV),
            get_tenant_settings_repository: lambda: repo, get_artifact_storage: lambda: storage,
            get_effective_platform_settings: lambda: s, get_platform_settings: lambda: s,
        }
        app.dependency_overrides.update(overrides)
        try:
            with patch("cf_platform.interfaces.routes.workers.build_llm_client", lambda pid, key: FakeLLM()):
                r = TestClient(app).post("/platform/workers/metadata", json={"run_id": "r1"})
            assert r.status_code == 200, r.text
            assert calls["model"] == "gpt-4.1-mini" and "Rents rose." in calls["user"]
            # a default without a key is a readable 409, not a crash
            s2 = platform(ANTHROPIC_API_KEY="sk-a")
            app.dependency_overrides[get_effective_platform_settings] = lambda: s2
            app.dependency_overrides[get_platform_settings] = lambda: s2
            r = TestClient(app).post("/platform/workers/metadata", json={"run_id": "r1"})
            assert r.status_code == 409 and "has no key" in r.json()["detail"]
        finally:
            for dep in overrides:
                app.dependency_overrides.pop(dep, None)

    def test_the_run_provider_view_reads_lineage_and_current_defaults(self):
        from tests.cf_platform.p13_helpers import RUN_ID, p13_env

        with p13_env() as env:
            repo = InMemoryTenantSettingsRepository()
            app.dependency_overrides[get_tenant_settings_repository] = lambda: repo
            from cf_platform.core.config import get_platform_settings

            app.dependency_overrides[get_platform_settings] = lambda: platform(ANTHROPIC_API_KEY="k")
            try:
                data = env.client.get(f"/platform/studio/runs/{RUN_ID}/providers").json()
            finally:
                app.dependency_overrides.pop(get_platform_settings, None)
        assert any(m["step"] == "Storyboard" and m["model"] for m in data["made_with"])
        blocks = {d["block"] for d in data["defaults_now"]}
        assert {"Thinking models", "Image generation", "Stock acquisition"} <= blocks
