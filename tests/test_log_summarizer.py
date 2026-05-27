"""Tests for log summarizer — src/log_summarizer.py and src/pipeline.py."""

import json
from unittest.mock import MagicMock, call, patch

import pytest

from src.exceptions import StorageError
from src.log_summarizer import (
    HAIKU_MODEL,
    generate_run_log_summary,
    write_run_log_summary,
)
from src.pipeline import summarize_step

# ── Fixtures ──────────────────────────────────────────────────────────────────

FAKE_API_KEY = "sk-ant-test-key"
FAKE_RUN_ID = "2026-05-27_test-run"

SAMPLE_RUN_LOG = {
    "run_id": FAKE_RUN_ID,
    "created_at": "2026-05-27T10:00:00Z",
    "steps": {
        "storyboard": {"status": "complete", "completed_at": "2026-05-27T10:01:00Z", "error": None},
        "asset_manifest": {"status": "failed", "completed_at": None, "error": "missing sfx field"},
        "asset_acquisition": {"status": "pending", "completed_at": None, "error": None},
        "alignment": {"status": "pending", "completed_at": None, "error": None},
        "ffmpeg_script": {"status": "pending", "completed_at": None, "error": None},
        "render": {"status": "pending", "completed_at": None, "error": None},
    },
}

SAMPLE_SUMMARY = (
    "✓ Storyboard: Complete\n"
    "✗ Asset Manifest: Failed — missing sfx field\n"
    "○ Asset Acquisition: Pending\n"
    "○ Alignment: Pending\n"
    "○ FFmpeg Script: Pending\n"
    "○ Render: Pending"
)


def _mock_anthropic(summary_text: str = SAMPLE_SUMMARY) -> MagicMock:
    """Build a mock Anthropic instance returning summary_text."""
    mock_content = MagicMock()
    mock_content.text = summary_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_instance = MagicMock()
    mock_instance.messages.create.return_value = mock_response
    return mock_instance


# ── generate_run_log_summary ──────────────────────────────────────────────────


class TestGenerateRunLogSummary:
    def test_returns_stripped_text_from_haiku(self):
        """Returns the text from the first content block, stripped."""
        mock_instance = _mock_anthropic("  " + SAMPLE_SUMMARY + "  ")
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            result = generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        assert result == SAMPLE_SUMMARY

    def test_uses_haiku_model(self):
        """messages.create is called with HAIKU_MODEL."""
        mock_instance = _mock_anthropic()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        call_kwargs = mock_instance.messages.create.call_args[1]
        assert call_kwargs["model"] == HAIKU_MODEL

    def test_max_tokens_512(self):
        """max_tokens is set to 512."""
        mock_instance = _mock_anthropic()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        call_kwargs = mock_instance.messages.create.call_args[1]
        assert call_kwargs["max_tokens"] == 512

    def test_run_log_json_included_in_user_message(self):
        """The user message contains the JSON-serialised run log."""
        mock_instance = _mock_anthropic()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        user_content = mock_instance.messages.create.call_args[1]["messages"][0]["content"]
        assert json.dumps(SAMPLE_RUN_LOG, indent=2) in user_content

    def test_anthropic_constructed_with_api_key(self):
        """Anthropic client is initialised with the supplied api_key."""
        mock_instance = _mock_anthropic()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance) as mock_cls:
            generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        mock_cls.assert_called_once_with(api_key=FAKE_API_KEY)

    def test_system_prompt_is_set(self):
        """messages.create is called with a non-empty system prompt."""
        mock_instance = _mock_anthropic()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            generate_run_log_summary(SAMPLE_RUN_LOG, FAKE_API_KEY)
        call_kwargs = mock_instance.messages.create.call_args[1]
        assert call_kwargs["system"]
        assert "step" in call_kwargs["system"].lower()


# ── write_run_log_summary ─────────────────────────────────────────────────────


class TestWriteRunLogSummary:
    def _mock_storage(self, run_log: dict = None) -> MagicMock:
        """Build a mock R2Client returning run_log from get_json."""
        storage = MagicMock()
        storage.get_json.return_value = run_log or SAMPLE_RUN_LOG
        return storage

    def test_reads_run_log_json_from_r2(self):
        """get_json is called with the expected run_log.json key."""
        storage = self._mock_storage()
        write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)
        storage.get_json.assert_any_call(f"runs/{FAKE_RUN_ID}/run_log.json")

    def test_uploads_run_log_txt_to_r2(self):
        """upload_text is called with the expected run_log.txt key."""
        storage = self._mock_storage()
        write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)
        storage.upload_text.assert_called_once()
        call_key = storage.upload_text.call_args[0][0]
        assert call_key == f"runs/{FAKE_RUN_ID}/run_log.txt"

    def test_uploaded_content_matches_haiku_output(self):
        """The text written to run_log.txt is exactly what Haiku returned."""
        custom_summary = "✓ Storyboard: Complete\n✗ Asset Manifest: Failed — bad data"
        mock_instance = _mock_anthropic(custom_summary)
        storage = self._mock_storage()
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)
        storage.upload_text.assert_called_once_with(
            f"runs/{FAKE_RUN_ID}/run_log.txt", custom_summary
        )

    def test_non_fatal_on_get_json_storage_error(self):
        """StorageError reading run_log.json is caught and does not propagate."""
        storage = MagicMock()
        storage.get_json.side_effect = StorageError("R2 read failed")
        write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)  # must not raise
        storage.upload_text.assert_not_called()

    def test_non_fatal_on_upload_storage_error(self):
        """StorageError writing run_log.txt is caught and does not propagate."""
        storage = self._mock_storage()
        storage.upload_text.side_effect = StorageError("R2 write failed")
        write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)  # must not raise

    def test_non_fatal_on_api_error(self):
        """Any exception from the Anthropic API is caught and does not propagate."""
        storage = self._mock_storage()
        mock_instance = MagicMock()
        mock_instance.messages.create.side_effect = RuntimeError("API unavailable")
        with patch("src.log_summarizer.Anthropic", return_value=mock_instance):
            write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)  # must not raise
        storage.upload_text.assert_not_called()

    def test_non_fatal_on_generic_exception(self):
        """Any unexpected exception is caught and does not propagate."""
        storage = MagicMock()
        storage.get_json.side_effect = Exception("Unexpected failure")
        write_run_log_summary(FAKE_RUN_ID, storage, FAKE_API_KEY)  # must not raise


# ── summarize_step (pipeline.py) ─────────────────────────────────────────────


class TestSummarizeStep:
    def test_delegates_to_write_run_log_summary(self):
        """summarize_step calls write_run_log_summary with run_id, storage, and api_key."""
        from src.config import Settings

        storage = MagicMock()
        storage.get_json.return_value = SAMPLE_RUN_LOG
        settings = MagicMock(spec=Settings)
        settings.ANTHROPIC_API_KEY = FAKE_API_KEY

        with patch("src.pipeline.write_run_log_summary") as mock_write:
            summarize_step(FAKE_RUN_ID, storage, settings)

        mock_write.assert_called_once_with(FAKE_RUN_ID, storage, FAKE_API_KEY)

    def test_uses_anthropic_api_key_from_settings(self):
        """summarize_step passes settings.ANTHROPIC_API_KEY to write_run_log_summary."""
        from src.config import Settings

        storage = MagicMock()
        settings = MagicMock(spec=Settings)
        settings.ANTHROPIC_API_KEY = "sk-ant-specific-key"

        with patch("src.pipeline.write_run_log_summary") as mock_write:
            summarize_step(FAKE_RUN_ID, storage, settings)

        _, _, passed_key = mock_write.call_args[0]
        assert passed_key == "sk-ant-specific-key"


# ── GET /runs/{run_id}/run-log-txt ────────────────────────────────────────────


class TestGetRunLogTxt:
    VALID_ENV = {
        "ENVIRONMENT": "dev",
        "R2_ACCOUNT_ID": "test-account",
        "R2_ACCESS_KEY_ID": "test-key",
        "R2_SECRET_ACCESS_KEY": "test-secret",
        "R2_BUCKET_NAME": "test-bucket",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "PEXELS_API_KEY": "test-pexels",
        "REPLICATE_API_TOKEN": "test-replicate",
        "FREESOUND_API_KEY": "test-freesound",
    }

    @pytest.fixture()
    def client(self):
        from fastapi.testclient import TestClient

        from src.config import Settings, get_settings
        from src.main import app

        settings = Settings.model_validate(self.VALID_ENV)
        app.dependency_overrides[get_settings] = lambda: settings
        yield TestClient(app, raise_server_exceptions=False)
        app.dependency_overrides.clear()

    def test_returns_200_with_content_when_available(self, client):
        """Returns 200 with the run_log.txt content when the file exists."""
        mock_r2 = MagicMock()
        mock_r2.get_bytes.return_value = SAMPLE_SUMMARY.encode("utf-8")
        with patch("src.routes.runs.R2Client", return_value=mock_r2):
            resp = client.get(f"/runs/{FAKE_RUN_ID}/run-log-txt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["content"] == SAMPLE_SUMMARY

    def test_returns_200_with_available_false_when_missing(self, client):
        """Returns 200 with available=False and empty content when run_log.txt does not exist."""
        mock_r2 = MagicMock()
        mock_r2.get_bytes.side_effect = StorageError("NoSuchKey")
        with patch("src.routes.runs.R2Client", return_value=mock_r2):
            resp = client.get(f"/runs/{FAKE_RUN_ID}/run-log-txt")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is False
        assert body["content"] == ""

    def test_fetches_correct_r2_key(self, client):
        """get_bytes is called with the expected run_log.txt key."""
        mock_r2 = MagicMock()
        mock_r2.get_bytes.return_value = b"some text"
        with patch("src.routes.runs.R2Client", return_value=mock_r2):
            client.get(f"/runs/{FAKE_RUN_ID}/run-log-txt")
        mock_r2.get_bytes.assert_called_once_with(f"runs/{FAKE_RUN_ID}/run_log.txt")
