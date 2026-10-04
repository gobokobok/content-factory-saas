"""Image generation behind one small interface (P14, D096, D104).

`ImageProvider.generate(prompt, aspect_ratio)` returns the image bytes. Two
implementations, plain `httpx`, no new dependency beyond what the project has:

- `KieImageProvider` — kie.ai's asynchronous market API: create a task, poll it,
  download the result URL.
- `OpenAIImageProvider` — OpenAI's images endpoint, which answers in one request.

The provider, model and key come from the tenant's settings or the Railway ENV
fallback (cf_platform/core/tenant_settings.py). Error messages never include a key.
"""

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

KIE_BASE_URL = "https://api.kie.ai"
OPENAI_BASE_URL = "https://api.openai.com"
IMAGE_PROVIDERS = ("kie", "openai")

# OpenAI takes a pixel size, not an aspect ratio.
_OPENAI_SIZES = {"9:16": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}


class ImageGenerationError(Exception):
    """Raised when a provider cannot produce an image; the message is safe to show the operator."""


@dataclass
class ImageResult:
    """One generated image: its bytes plus the type to store it under."""

    data: bytes
    content_type: str = "image/png"
    ext: str = ".png"


class ImageProvider(Protocol):
    """What the Studio generate route needs from an image provider."""

    name: str

    async def generate(self, prompt: str, aspect_ratio: str) -> ImageResult:
        """Return one image for `prompt`; raise ImageGenerationError on any failure."""
        ...


def _ext_for(content_type: str) -> str:
    """File extension for an image content type, defaulting to .png."""
    return {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(content_type, ".png")


class KieImageProvider:
    """kie.ai market API: POST createTask, poll recordInfo, GET the result URL."""

    name = "kie"

    def __init__(
        self,
        api_key: str,
        model: str,
        resolution: str = "1K",
        timeout_s: float = 180.0,
        poll_interval_s: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store credentials and tunables; `transport` lets tests replace the network."""
        self._api_key = api_key
        self._model = model
        self._resolution = resolution
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._transport = transport

    async def generate(self, prompt: str, aspect_ratio: str) -> ImageResult:
        """Create a task, wait for it to finish and download the first result image."""
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(
            base_url=KIE_BASE_URL, headers=headers, timeout=60.0, transport=self._transport
        ) as client:
            task_id = await self._create_task(client, prompt, aspect_ratio)
            url = await self._wait_for_result(client, task_id)
        return await self._download(url)

    async def _create_task(self, client: httpx.AsyncClient, prompt: str, aspect_ratio: str) -> str:
        """POST /api/v1/jobs/createTask and return the task id."""
        body = {
            "model": self._model,
            "input": {"prompt": prompt, "aspect_ratio": aspect_ratio, "resolution": self._resolution},
        }
        payload = await self._json(await client.post("/api/v1/jobs/createTask", json=body))
        task_id = (payload.get("data") or {}).get("taskId")
        if not task_id:
            raise ImageGenerationError("kie.ai did not return a task id.")
        return task_id

    async def _wait_for_result(self, client: httpx.AsyncClient, task_id: str) -> str:
        """Poll recordInfo until the task succeeds; return the first result URL."""
        deadline = time.monotonic() + self._timeout_s
        while True:
            payload = await self._json(
                await client.get("/api/v1/jobs/recordInfo", params={"taskId": task_id})
            )
            data = payload.get("data") or {}
            state = data.get("state")
            if state == "success":
                try:
                    urls = json.loads(data.get("resultJson") or "{}").get("resultUrls") or []
                except (TypeError, ValueError):
                    urls = []
                if not urls:
                    raise ImageGenerationError("kie.ai finished without an image.")
                return urls[0]
            if state == "fail":
                raise ImageGenerationError(f"kie.ai could not generate the image: {data.get('failMsg') or 'unknown reason'}")
            if time.monotonic() >= deadline:
                raise ImageGenerationError("kie.ai took too long to generate the image — try again.")
            await asyncio.sleep(self._poll_interval_s)

    async def _download(self, url: str) -> ImageResult:
        """Download the generated image from its temporary URL, without the API key."""
        try:
            async with httpx.AsyncClient(timeout=60.0, transport=self._transport) as plain:
                response = await plain.get(url)
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"Could not download the generated image: {type(exc).__name__}") from exc
        if response.status_code != 200 or not response.content:
            raise ImageGenerationError(f"Could not download the generated image (HTTP {response.status_code}).")
        content_type = response.headers.get("content-type", "image/png").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/png"
        return ImageResult(data=response.content, content_type=content_type, ext=_ext_for(content_type))

    @staticmethod
    async def _json(response: httpx.Response) -> dict:
        """Parse a kie.ai response, turning HTTP and API-level errors into ImageGenerationError."""
        if response.status_code in (401, 403):
            raise ImageGenerationError("kie.ai rejected the API key — check it in Settings.")
        if response.status_code == 402:
            raise ImageGenerationError("kie.ai account has no credits left.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ImageGenerationError(f"kie.ai returned an unreadable answer (HTTP {response.status_code}).") from exc
        code = payload.get("code", response.status_code)
        if response.status_code >= 400 or code != 200:
            if code in (401, 403):
                raise ImageGenerationError("kie.ai rejected the API key — check it in Settings.")
            if code == 402:
                raise ImageGenerationError("kie.ai account has no credits left.")
            raise ImageGenerationError(f"kie.ai error {code}: {payload.get('msg') or 'request failed'}")
        return payload


class OpenAIImageProvider:
    """OpenAI images API: one POST, the image comes back base64-encoded."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        quality: str = "medium",
        timeout_s: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """Store credentials and tunables; `transport` lets tests replace the network."""
        self._api_key = api_key
        self._model = model
        self._quality = quality
        self._timeout_s = timeout_s
        self._transport = transport

    async def generate(self, prompt: str, aspect_ratio: str) -> ImageResult:
        """Request one image and decode it."""
        body = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": _OPENAI_SIZES.get(aspect_ratio, "1024x1536"),
            "quality": self._quality,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(
                base_url=OPENAI_BASE_URL, headers=headers, timeout=self._timeout_s, transport=self._transport
            ) as client:
                response = await client.post("/v1/images/generations", json=body)
        except httpx.HTTPError as exc:
            raise ImageGenerationError(f"Could not reach OpenAI: {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            raise ImageGenerationError("OpenAI rejected the API key — check it in Settings.")
        if response.status_code != 200:
            try:
                detail = response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = ""
            raise ImageGenerationError(f"OpenAI error {response.status_code}: {detail or 'request failed'}")
        try:
            b64 = response.json()["data"][0]["b64_json"]
            return ImageResult(data=base64.b64decode(b64))
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ImageGenerationError("OpenAI returned no image.") from exc


def build_image_provider(
    provider: str,
    api_key: str,
    model: str,
    *,
    quality: str = "medium",
    resolution: str = "1K",
    timeout_s: float = 180.0,
    poll_interval_s: float = 3.0,
) -> ImageProvider:
    """Return the ImageProvider for `provider` ("kie" or "openai"); ValueError for any other name."""
    if provider == "kie":
        return KieImageProvider(api_key, model, resolution, timeout_s, poll_interval_s)
    if provider == "openai":
        return OpenAIImageProvider(api_key, model, quality, timeout_s)
    raise ValueError(f"Unknown image provider {provider!r} — expected one of {list(IMAGE_PROVIDERS)}")
