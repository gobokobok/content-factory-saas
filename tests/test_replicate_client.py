"""Tests for src/replicate_client.py — Replicate/Flux image generation client."""

from unittest.mock import Mock, patch

import pytest

from src.exceptions import ReplicateError
from src.models import ManifestEntry, ReplicateAcquireResult
from src.replicate_client import _STYLE_MODIFIERS, ReplicateClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_TOKEN = "r8_test_token"
FAKE_MODEL = "black-forest-labs/flux-schnell"
FAKE_IMAGE_BYTES = b"\x89PNG fake image bytes"
FAKE_IMAGE_URL = "https://replicate.delivery/output/abc123/image"


def _make_client(**kwargs) -> ReplicateClient:
    """Construct a ReplicateClient with test defaults, patching replicate.Client."""
    with patch("src.replicate_client.replicate.Client"):
        return ReplicateClient(
            api_token=FAKE_TOKEN,
            model=FAKE_MODEL,
            poll_interval_seconds=0,
            max_poll_attempts=kwargs.get("max_poll_attempts", 5),
        )


def _make_entry(
    scene_id: str = "01",
    clip_type: str = "still_with_motion",
    ai_generate_prompt: str = "A dramatic aerial view of suburban sprawl",
) -> ManifestEntry:
    """Build a ManifestEntry suitable for Replicate acquisition."""
    return ManifestEntry(
        scene_id=scene_id,
        clip_type=clip_type,
        primary_query="suburban sprawl aerial",
        fallback_query="housing development",
        ai_generate_prompt=ai_generate_prompt,
    )


def _make_succeeded_prediction(image_url: str = FAKE_IMAGE_URL) -> Mock:
    """Return a mock prediction that is already in 'succeeded' state."""
    pred = Mock()
    pred.id = "pred_abc123"
    pred.status = "succeeded"
    pred.output = [Mock(__str__=lambda self: image_url)]
    pred.error = None
    return pred


def _make_storage() -> Mock:
    """Return a mock R2Client."""
    return Mock()


# ── Initialisation ─────────────────────────────────────────────────────────────


def test_init_creates_replicate_client_with_token():
    """ReplicateClient passes api_token to replicate.Client on init."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        ReplicateClient(
            api_token=FAKE_TOKEN,
            model=FAKE_MODEL,
            poll_interval_seconds=0,
            max_poll_attempts=5,
        )
    mock_client_class.assert_called_once_with(api_token=FAKE_TOKEN)


# ── Happy-path: acquire_for_entry ─────────────────────────────────────────────


def test_acquire_for_entry_returns_replicate_acquire_result():
    """acquire_for_entry returns a ReplicateAcquireResult on success."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())

    assert isinstance(result, ReplicateAcquireResult)


def test_acquire_for_entry_source_is_replicate():
    """Result source is always 'replicate'."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())

    assert result.source == "replicate"


def test_acquire_for_entry_status_is_acquired():
    """Result status is always 'acquired'."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry("03"), "2026-05-22_test-run", _make_storage())

    assert result.status == "acquired"


def test_acquire_for_entry_scene_id_matches_entry():
    """Result scene_id matches the manifest entry scene_id."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry("07"), "2026-05-22_test-run", _make_storage())

    assert result.scene_id == "07"


def test_acquire_for_entry_file_key_uses_webp_extension():
    """file_key always uses .webp extension regardless of CDN URL format."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction(
            "https://replicate.delivery/output/abc123/no-extension-here"
        )
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry("02"), "2026-05-22_test-run", _make_storage())

    assert result.file_key.endswith(".webp")


def test_acquire_for_entry_file_key_correct_r2_path():
    """file_key follows runs/{run_id}/images/{scene_id}.webp pattern."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(
            _make_entry("04"), "2026-05-22_test-run", _make_storage()
        )

    assert result.file_key == "runs/2026-05-22_test-run/images/04.webp"


def test_acquire_for_entry_uploads_with_webp_content_type():
    """upload_bytes is called with content_type='image/webp'."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    storage = _make_storage()
    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        client.acquire_for_entry(_make_entry("05"), "2026-05-22_test-run", storage)

    assert storage.upload_bytes.call_args[1].get("content_type") == "image/webp"


def test_acquire_for_entry_uses_ai_generate_prompt():
    """predictions.create is called with the entry's ai_generate_prompt."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    prompt = "Sweeping aerial shot of empty lots in Phoenix"
    entry = _make_entry(ai_generate_prompt=prompt)
    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        client.acquire_for_entry(entry, "2026-05-22_test-run", _make_storage())

    mock_client.predictions.create.assert_called_once_with(
        model=FAKE_MODEL, input={"prompt": prompt}
    )


# ── Polling behaviour ──────────────────────────────────────────────────────────


def test_acquire_for_entry_succeeds_after_multiple_polls():
    """acquire_for_entry succeeds when prediction transitions processing → succeeded."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_xyz"
        pred.status = "starting"
        pred.output = [Mock(__str__=lambda self: FAKE_IMAGE_URL)]
        pred.error = None
        statuses = iter(["processing", "processing", "succeeded"])

        def reload_effect():
            pred.status = next(statuses)

        pred.reload.side_effect = reload_effect
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        result = client.acquire_for_entry(_make_entry("06"), "2026-05-22_test-run", _make_storage())

    assert result.source == "replicate"
    assert pred.reload.call_count == 3


# ── Failure paths ──────────────────────────────────────────────────────────────


def test_prediction_failed_status_raises_replicate_error():
    """ReplicateError raised when prediction ends with status 'failed'."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_fail"
        pred.status = "failed"
        pred.error = "NSFW content detected"
        pred.reload.return_value = None
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with pytest.raises(ReplicateError, match="failed"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_prediction_canceled_status_raises_replicate_error():
    """ReplicateError raised when prediction ends with status 'canceled'."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_cancel"
        pred.status = "canceled"
        pred.error = None
        pred.reload.return_value = None
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with pytest.raises(ReplicateError, match="canceled"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_poll_timeout_raises_replicate_error():
    """ReplicateError raised when max_poll_attempts exhausted without terminal status."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_slow"
        pred.status = "processing"
        pred.reload.return_value = None
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(
            FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0, max_poll_attempts=3
        )

    with pytest.raises(ReplicateError, match="timed out"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())

    assert pred.reload.call_count == 3


def test_predictions_create_exception_raises_replicate_error():
    """ReplicateError raised when predictions.create itself throws."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.side_effect = RuntimeError("network error")
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with pytest.raises(ReplicateError, match="prediction create failed"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_reload_exception_raises_replicate_error():
    """ReplicateError raised when prediction.reload() throws."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_reload_err"
        pred.status = "processing"
        pred.reload.side_effect = RuntimeError("connection reset")
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with pytest.raises(ReplicateError, match="poll failed"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_empty_output_raises_replicate_error():
    """ReplicateError raised when prediction succeeds but output is empty."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        pred = Mock()
        pred.id = "pred_empty"
        pred.status = "succeeded"
        pred.output = []
        pred.error = None
        pred.reload.return_value = None
        mock_client.predictions.create.return_value = pred
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with pytest.raises(ReplicateError, match="output is empty"):
        client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_download_non_200_raises_replicate_error():
    """ReplicateError raised when image download returns a non-200 status code."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=503)
        with pytest.raises(ReplicateError, match="Image download failed"):
            client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_download_exception_raises_replicate_error():
    """ReplicateError raised when requests.get throws during image download."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.side_effect = ConnectionError("timeout")
        with pytest.raises(ReplicateError, match="Image download error"):
            client.acquire_for_entry(_make_entry(), "2026-05-22_test-run", _make_storage())


def test_storage_upload_bytes_called_with_correct_args():
    """upload_bytes called with correct key, bytes, and content_type."""
    with patch("src.replicate_client.replicate.Client") as mock_client_class:
        mock_client = mock_client_class.return_value
        mock_client.predictions.create.return_value = _make_succeeded_prediction()
        client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

    storage = _make_storage()
    with patch("src.replicate_client.requests.get") as mock_get:
        mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
        client.acquire_for_entry(_make_entry("08"), "2026-05-22_slug", storage)

    storage.upload_bytes.assert_called_once_with(
        "runs/2026-05-22_slug/images/08.webp",
        FAKE_IMAGE_BYTES,
        content_type="image/webp",
    )


# ── Visual style modifier ─────────────────────────────────────────────────────


class TestVisualStyleModifier:
    """Verify visual_style appends the correct modifier to the Replicate prompt."""

    BASE_PROMPT = "Aerial view of suburban housing development"

    def _prompt_sent_to_replicate(self, visual_style: str) -> str:
        """Run acquire_for_entry with the given visual_style and return the prompt used."""
        with patch("src.replicate_client.replicate.Client") as mock_client_class:
            mock_client = mock_client_class.return_value
            pred = _make_succeeded_prediction()
            mock_client.predictions.create.return_value = pred
            client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

        _make_entry(ai_generate_prompt=self.BASE_PROMPT)
        with patch("src.replicate_client.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
            client.acquire_for_entry(_make_entry(ai_generate_prompt=self.BASE_PROMPT), "run-id", _make_storage(), visual_style=visual_style)

        return mock_client.predictions.create.call_args[1]["input"]["prompt"]

    def test_realistic_appends_no_modifier(self):
        """Realistic visual_style leaves the prompt unchanged."""
        prompt = self._prompt_sent_to_replicate("Realistic")
        assert prompt == self.BASE_PROMPT

    def test_cinematic_appends_modifier(self):
        """Cinematic visual_style appends its modifier to the prompt."""
        prompt = self._prompt_sent_to_replicate("Cinematic")
        assert prompt.startswith(self.BASE_PROMPT + ", ")
        assert "cinematic" in prompt.lower()

    def test_cartoonish_appends_modifier(self):
        """Cartoonish visual_style appends its modifier to the prompt."""
        prompt = self._prompt_sent_to_replicate("Cartoonish")
        assert "cartoon" in prompt.lower()

    def test_documentary_appends_modifier(self):
        """Documentary visual_style appends its modifier to the prompt."""
        prompt = self._prompt_sent_to_replicate("Documentary")
        assert "documentary" in prompt.lower()

    def test_minimalist_appends_modifier(self):
        """Minimalist visual_style appends its modifier to the prompt."""
        prompt = self._prompt_sent_to_replicate("Minimalist")
        assert "minimalist" in prompt.lower()

    def test_default_visual_style_is_realistic(self):
        """When visual_style is omitted, no modifier is appended (Realistic default)."""
        with patch("src.replicate_client.replicate.Client") as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.predictions.create.return_value = _make_succeeded_prediction()
            client = ReplicateClient(FAKE_TOKEN, FAKE_MODEL, poll_interval_seconds=0)

        entry = _make_entry(ai_generate_prompt=self.BASE_PROMPT)
        with patch("src.replicate_client.requests.get") as mock_get:
            mock_get.return_value = Mock(status_code=200, content=FAKE_IMAGE_BYTES)
            client.acquire_for_entry(entry, "run-id", _make_storage())

        prompt = mock_client.predictions.create.call_args[1]["input"]["prompt"]
        assert prompt == self.BASE_PROMPT

    def test_style_modifiers_dict_has_four_entries(self):
        """_STYLE_MODIFIERS covers the four non-Realistic visual styles."""
        assert set(_STYLE_MODIFIERS.keys()) == {"Cinematic", "Cartoonish", "Documentary", "Minimalist"}

    def test_realistic_not_in_style_modifiers(self):
        """Realistic is intentionally absent from _STYLE_MODIFIERS (handled by dict.get default)."""
        assert "Realistic" not in _STYLE_MODIFIERS
