"""Tests for P-AN1-S6: Nano Banana on kie.ai and the per-model image cost.

kie.ai is replaced with httpx.MockTransport; nothing here touches a network.
Request and response shapes follow kie.ai's own documentation for
`nano-banana-2-1` (docs.kie.ai/market/google/nanobanana-2-1, checked 2026-10-11).
"""

import json

import httpx
import pytest

from cf_platform.core.ai_images import model_cost_usd
from cf_platform.core.config import PlatformSettings
from cf_platform.core.image_provider import ImageGenerationError, KieImageProvider
from cf_platform.core.tenant_settings import (
    InMemoryTenantSettingsRepository,
    public_image_settings,
    save_image_settings,
)
from tests.cf_platform.p13_helpers import RUN_ID
from tests.cf_platform.pan1_helpers import animation_env

JPG = b"\xff\xd8\xff-fake-jpeg"
MODEL = "nano-banana-2-1"


def _provider(handler, resolution: str = "1K") -> KieImageProvider:
    """A KieImageProvider for Nano Banana 2.1 whose network is `handler`."""
    return KieImageProvider(
        "kie-secret-key", MODEL, resolution=resolution, poll_interval_s=0, timeout_s=5,
        transport=httpx.MockTransport(handler),
    )


def _kie(seen: dict, *, state: str = "success", fail_msg: str = ""):
    """A kie.ai stand-in: createTask, recordInfo, then the result download."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/jobs/createTask":
            seen["create"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 200, "msg": "success", "data": {"taskId": "nb1"}})
        if request.url.path == "/api/v1/jobs/recordInfo":
            data = {"taskId": "nb1", "model": MODEL, "state": state}
            if state == "success":
                data["resultJson"] = json.dumps({"resultUrls": ["https://cdn.kie.example/out/nb1.jpg"]})
            else:
                data.update(failCode="501", failMsg=fail_msg)
            return httpx.Response(200, json={"code": 200, "msg": "success", "data": data})
        seen["download"] = str(request.url)
        seen["download_auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=JPG, headers={"content-type": "image/jpeg"})
    return handler


class TestNanoBananaRequest:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("aspect", ["9:16", "16:9"])
    async def test_the_request_names_the_model_and_carries_prompt_aspect_and_resolution(self, aspect):
        seen: dict = {}
        image = await _provider(_kie(seen)).generate("a quiet street", aspect)
        assert seen["create"] == {
            "model": MODEL,
            "input": {"prompt": "a quiet street", "aspect_ratio": aspect, "resolution": "1K"},
        }
        # the model's default output is jpg: the stored file follows the download's type
        assert (image.data, image.content_type, image.ext) == (JPG, "image/jpeg", ".jpg")
        assert seen["download"] == "https://cdn.kie.example/out/nb1.jpg" and seen["download_auth"] is None

    @pytest.mark.asyncio
    async def test_the_resolution_setting_is_passed_through(self):
        seen: dict = {}
        await _provider(_kie(seen), resolution="2K").generate("p", "9:16")
        assert seen["create"]["input"]["resolution"] == "2K"

    @pytest.mark.asyncio
    async def test_a_failed_task_is_reported_with_kies_reason(self):
        with pytest.raises(ImageGenerationError, match="content policy"):
            await _provider(_kie({}, state="fail", fail_msg="content policy")).generate("p", "9:16")


class TestModelCost:
    def test_a_model_in_the_table_uses_its_own_price(self):
        assert model_cost_usd("nano-banana-2-1", {"nano-banana-2-1": 0.02}, 0.03) == 0.02

    def test_any_other_model_or_a_bad_entry_uses_the_general_estimate(self):
        assert model_cost_usd("gpt-image-2-text-to-image", {"nano-banana-2-1": 0.02}, 0.03) == 0.03
        assert model_cost_usd("m", None, 0.03) == 0.03
        assert model_cost_usd(None, {"": 0.5}, 0.03) == 0.5
        assert model_cost_usd("m", {"m": "free"}, 0.03) == 0.03
        assert model_cost_usd("m", {"m": -1}, 0.03) == 0.03

    def test_the_default_table_prices_nano_banana_at_1k(self):
        fields = PlatformSettings.model_fields
        assert fields["IMAGE_MODEL_COSTS_USD"].default == {"nano-banana-2-1": 0.02}
        assert fields["IMAGE_RUN_SPEND_CAP_MAX_USD"].default == 10.0 and fields["IMAGE_JOB_CONCURRENCY"].default == 3

    def test_the_price_table_can_come_from_the_environment_as_json(self, monkeypatch):
        for key in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
            monkeypatch.setenv(key, "x")
        monkeypatch.setenv("IMAGE_MODEL_COSTS_USD", '{"nano-banana-2-1": 0.03, "other": 0.1}')
        assert PlatformSettings(_env_file=None).IMAGE_MODEL_COSTS_USD == {"nano-banana-2-1": 0.03, "other": 0.1}


class TestSelectedModel:
    @pytest.mark.asyncio
    async def test_the_model_is_a_tenant_setting_and_settings_show_its_price(self):
        from types import SimpleNamespace

        from cryptography.fernet import Fernet

        settings = SimpleNamespace(
            SETTINGS_ENCRYPTION_KEY=Fernet.generate_key().decode(), IMAGE_PROVIDER="kie", KIE_API_KEY="k",
            OPENAI_API_KEY="", KIE_IMAGE_MODEL="gpt-image-2-text-to-image", OPENAI_IMAGE_MODEL="gpt-image-1",
            IMAGE_MODEL_COSTS_USD={"nano-banana-2-1": 0.02}, IMAGE_COST_USD=0.03,
        )
        repo = InMemoryTenantSettingsRepository()
        await save_image_settings(repo, "t", settings, provider="kie", model=MODEL)
        public = await public_image_settings(repo, "t", settings)
        assert public["model"] == MODEL
        assert public["model_costs_usd"] == {"nano-banana-2-1": 0.02} and public["default_cost_usd"] == 0.03

    def test_estimate_cap_and_ledger_use_the_selected_models_price(self, monkeypatch):
        """With Nano Banana selected the spend display, the plan and the ledger count 0.02, not IMAGE_COST_USD."""
        with animation_env(monkeypatch, cost=0.5) as env:
            env.settings.KIE_IMAGE_MODEL = MODEL
            env.settings.IMAGE_MODEL_COSTS_USD = {MODEL: 0.02}
            run = f"/platform/studio/runs/{RUN_ID}"
            spend = env.client.get(f"{run}/ai-spend").json()
            assert (spend["cost_per_image_usd"], spend["model"]) == (0.02, MODEL)
            plan = env.client.get(f"{run}/images/plan").json()
            assert (plan["cost_per_image_usd"], plan["estimated_cost_usd"], plan["affordable"]) == (0.02, 0.06, 3)
            r = env.client.post(f"{run}/scenes/1/generate", json={"prompt": "p"})
            assert r.json()["spend"]["spent_usd"] == 0.02
            import asyncio

            ledger = asyncio.run(env.storage.get_json(f"runs/{RUN_ID}/ai_spend.json"))
            assert ledger["generations"][0]["model"] == MODEL and ledger["generations"][0]["cost_usd"] == 0.02
