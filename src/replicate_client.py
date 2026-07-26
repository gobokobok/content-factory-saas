"""Replicate/Flux AI image generation client — fallback when Pexels yields no result.

Generation strategy
-------------------
Submits a text-to-image prediction to the configured Flux model using the
scene's ai_generate_prompt. Polls until the prediction reaches a terminal
status (succeeded / failed / canceled) or the poll budget is exhausted.
Downloads the first output URL and uploads the bytes to R2 as a .webp file.

Output format
-------------
Flux Schnell returns WebP images. All Replicate-generated assets are stored
as .webp regardless of CDN URL format — the URL often has no meaningful
extension, so inferring it would be unreliable.
"""

import logging
import time

import replicate
import requests

from src.exceptions import ReplicateError
from src.models import ManifestEntry, ReplicateAcquireResult
from src.storage import R2Client

logger = logging.getLogger(__name__)

_IMAGE_EXT = ".webp"
_IMAGE_CONTENT_TYPE = "image/webp"
_TERMINAL_STATUSES = {"succeeded", "failed", "canceled"}

# Appended to ai_generate_prompt when a non-default visual style is configured.
# "Realistic" has no modifier — the base prompts already target realistic footage.
_STYLE_MODIFIERS: dict[str, str] = {
    "Cinematic": "cinematic, shallow depth of field, golden hour lighting",
    "Cartoonish": "cartoon style, illustrated, vibrant colors",
    "Documentary": "documentary photography, photojournalism, natural light",
    "Minimalist": "minimalist, clean composition, simple background",
}


class ReplicateClient:
    """Client for Replicate Flux image generation — fallback asset source."""

    def __init__(
        self,
        api_token: str,
        model: str,
        poll_interval_seconds: int = 3,
        max_poll_attempts: int = 60,
    ) -> None:
        """Initialise with API token, Flux model identifier, and polling config."""
        self._client = replicate.Client(api_token=api_token)
        self._model = model
        self._poll_interval = poll_interval_seconds
        self._max_attempts = max_poll_attempts

    def _generate_image(self, prompt: str) -> bytes:
        """
        Submit a Flux generation prediction and poll until complete.

        Returns raw image bytes on success. Raises ReplicateError on API
        failure, terminal error/canceled status, poll timeout, or download
        failure.
        """
        try:
            prediction = self._client.predictions.create(
                model=self._model,
                input={"prompt": prompt},
            )
        except Exception as exc:
            raise ReplicateError(f"Replicate prediction create failed: {exc}") from exc

        for attempt in range(self._max_attempts):
            try:
                prediction.reload()
            except Exception as exc:
                raise ReplicateError(f"Replicate poll failed: {exc}") from exc

            status = prediction.status
            if status == "succeeded":
                break
            if status in ("failed", "canceled"):
                raise ReplicateError(
                    f"Replicate prediction {prediction.id} ended with status "
                    f"'{status}': {prediction.error}"
                )
            logger.debug(
                "Replicate prediction %s status=%s (attempt %d/%d)",
                prediction.id,
                status,
                attempt + 1,
                self._max_attempts,
            )
            time.sleep(self._poll_interval)
        else:
            raise ReplicateError(
                f"Replicate prediction {prediction.id} timed out after "
                f"{self._max_attempts} poll attempts"
            )

        output = prediction.output
        if not output:
            raise ReplicateError(
                f"Replicate prediction {prediction.id} succeeded but output is empty"
            )

        url = str(output[0])
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code != 200:
                raise ReplicateError(
                    f"Image download failed (HTTP {resp.status_code}): {url}"
                )
            return resp.content
        except ReplicateError:
            raise
        except Exception as exc:
            raise ReplicateError(f"Image download error: {exc}") from exc

    def acquire_for_entry(
        self,
        entry: ManifestEntry,
        run_id: str,
        storage: R2Client,
        visual_style: str = "Realistic",
    ) -> ReplicateAcquireResult:
        """
        Generate a Flux image for one manifest entry and upload to R2.

        Uses entry.ai_generate_prompt as the generation prompt, with an optional
        style modifier appended based on visual_style (e.g. 'Cinematic' adds
        'cinematic, shallow depth of field, golden hour lighting').
        Uploads result to runs/{run_id}/images/{scene_id}.webp. Returns
        ReplicateAcquireResult on success. Raises ReplicateError on any
        generation, download, or upload failure.
        """
        prompt = entry.ai_generate_prompt
        modifier = _STYLE_MODIFIERS.get(visual_style, "")
        if modifier:
            prompt = f"{prompt}, {modifier}"
        logger.info(
            "Replicate generation: scene=%s prompt='%.80s'",
            entry.scene_id,
            prompt,
        )
        data = self._generate_image(prompt)
        key = f"runs/{run_id}/images/{entry.scene_id}{_IMAGE_EXT}"
        storage.upload_bytes(key, data, content_type=_IMAGE_CONTENT_TYPE)
        logger.info("Replicate image uploaded: scene=%s key=%s", entry.scene_id, key)
        return ReplicateAcquireResult(scene_id=entry.scene_id, file_key=key)
