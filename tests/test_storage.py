"""Tests for R2Client — all boto3 calls are mocked."""

import io
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.exceptions import StorageError
from src.models import PIPELINE_STEPS, StepStatus
from src.storage import R2Client, _build_run_log


FAKE_ACCOUNT_ID = "fake-account-id"
FAKE_ACCESS_KEY = "fake-access-key"
FAKE_SECRET_KEY = "fake-secret-key"
FAKE_BUCKET = "content-factory-dev"
FAKE_RUN_ID = "2026-05-22_test-slug"


@pytest.fixture()
def mock_s3():
    """Patch boto3.client so no real R2 calls are made. Yields the mock S3 client."""
    with patch("src.storage.boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        yield mock_client


@pytest.fixture()
def client(mock_s3) -> R2Client:
    """R2Client with boto3 fully mocked."""
    return R2Client(FAKE_ACCOUNT_ID, FAKE_ACCESS_KEY, FAKE_SECRET_KEY, FAKE_BUCKET)


class TestR2ClientInit:
    def test_successful_init(self, mock_s3):
        """Valid credentials produce an R2Client without error."""
        c = R2Client(FAKE_ACCOUNT_ID, FAKE_ACCESS_KEY, FAKE_SECRET_KEY, FAKE_BUCKET)
        assert c is not None

    def test_boto3_called_with_correct_endpoint(self):
        """boto3.client is called with the R2 endpoint derived from account_id."""
        with patch("src.storage.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            R2Client(FAKE_ACCOUNT_ID, FAKE_ACCESS_KEY, FAKE_SECRET_KEY, FAKE_BUCKET)
            mock_boto.assert_called_once_with(
                "s3",
                endpoint_url=f"https://{FAKE_ACCOUNT_ID}.r2.cloudflarestorage.com",
                aws_access_key_id=FAKE_ACCESS_KEY,
                aws_secret_access_key=FAKE_SECRET_KEY,
                region_name="auto",
            )

    def test_boto3_failure_raises_storage_error(self):
        """If boto3.client raises, StorageError is surfaced."""
        with patch("src.storage.boto3.client", side_effect=Exception("network error")):
            with pytest.raises(StorageError, match="Failed to initialise R2 client"):
                R2Client(FAKE_ACCOUNT_ID, FAKE_ACCESS_KEY, FAKE_SECRET_KEY, FAKE_BUCKET)


class TestUploadJson:
    def test_calls_put_object_with_correct_args(self, client, mock_s3):
        """put_object is called with the right bucket, key, and content type."""
        client.upload_json("runs/foo/bar.json", {"key": "val"})
        mock_s3.put_object.assert_called_once()
        call_kwargs = mock_s3.put_object.call_args.kwargs
        assert call_kwargs["Bucket"] == FAKE_BUCKET
        assert call_kwargs["Key"] == "runs/foo/bar.json"
        assert call_kwargs["ContentType"] == "application/json"

    def test_serialises_data_as_json(self, client, mock_s3):
        """The body uploaded is valid JSON matching the input dict."""
        data = {"step": "storyboard", "status": "pending"}
        client.upload_json("test.json", data)
        body = mock_s3.put_object.call_args.kwargs["Body"]
        assert json.loads(body) == data

    def test_put_object_failure_raises_storage_error(self, client, mock_s3):
        """put_object failure propagates as StorageError."""
        mock_s3.put_object.side_effect = Exception("access denied")
        with pytest.raises(StorageError, match="R2 upload failed"):
            client.upload_json("test.json", {})


class TestGetJson:
    def test_returns_parsed_dict(self, client, mock_s3):
        """get_object response body is parsed and returned as a dict."""
        payload = {"run_id": "test", "steps": {}}
        mock_s3.get_object.return_value = {
            "Body": io.BytesIO(json.dumps(payload).encode())
        }
        result = client.get_json("runs/test/run_log.json")
        assert result == payload

    def test_get_object_failure_raises_storage_error(self, client, mock_s3):
        """get_object failure propagates as StorageError."""
        mock_s3.get_object.side_effect = Exception("key not found")
        with pytest.raises(StorageError, match="R2 get failed"):
            client.get_json("missing.json")


class TestCreateRunFolder:
    def test_returns_correct_prefix(self, client, mock_s3):
        """create_run_folder returns runs/{run_id}/."""
        prefix = client.create_run_folder(FAKE_RUN_ID)
        assert prefix == f"runs/{FAKE_RUN_ID}/"

    def test_uploads_run_log_json(self, client, mock_s3):
        """run_log.json is uploaded under the run prefix."""
        client.create_run_folder(FAKE_RUN_ID)
        uploaded_key = mock_s3.put_object.call_args.kwargs["Key"]
        assert uploaded_key == f"runs/{FAKE_RUN_ID}/run_log.json"

    def test_upload_failure_raises_storage_error(self, client, mock_s3):
        """If the run_log.json upload fails, StorageError is raised."""
        mock_s3.put_object.side_effect = Exception("quota exceeded")
        with pytest.raises(StorageError):
            client.create_run_folder(FAKE_RUN_ID)


class TestUpdateRunLog:
    def _run_log_body(self, status: str = "pending") -> dict:
        """Return a minimal run_log dict for use in get_object mock responses."""
        return {
            "run_id": FAKE_RUN_ID,
            "created_at": "2026-05-22T10:00:00+00:00",
            "steps": {step: {"status": status, "completed_at": None, "error": None}
                      for step in PIPELINE_STEPS},
        }

    def test_updates_step_status(self, client, mock_s3):
        """The target step's status is updated in the re-uploaded run_log."""
        body = self._run_log_body()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(body).encode())}
        client.update_run_log(FAKE_RUN_ID, "storyboard", "complete")
        uploaded = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert uploaded["steps"]["storyboard"]["status"] == "complete"

    def test_sets_completed_at_on_complete(self, client, mock_s3):
        """completed_at is set when status is 'complete'."""
        body = self._run_log_body()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(body).encode())}
        client.update_run_log(FAKE_RUN_ID, "storyboard", "complete")
        uploaded = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert uploaded["steps"]["storyboard"]["completed_at"] is not None

    def test_sets_output_url_when_provided(self, client, mock_s3):
        """output_url is stored in the step log when provided."""
        body = self._run_log_body()
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(body).encode())}
        client.update_run_log(FAKE_RUN_ID, "storyboard", "complete", output_url="r2://bucket/key")
        uploaded = json.loads(mock_s3.put_object.call_args.kwargs["Body"])
        assert uploaded["steps"]["storyboard"]["output_url"] == "r2://bucket/key"


class TestBuildRunLog:
    def test_all_steps_present(self):
        """run_log contains all five pipeline steps."""
        log = _build_run_log(FAKE_RUN_ID)
        assert set(log.steps.keys()) == set(PIPELINE_STEPS)

    def test_all_steps_pending(self):
        """All steps are initialised to pending."""
        log = _build_run_log(FAKE_RUN_ID)
        for step, entry in log.steps.items():
            assert entry.status == StepStatus.pending, f"{step} should be pending"

    def test_run_id_preserved(self):
        """run_id matches the value passed in."""
        log = _build_run_log(FAKE_RUN_ID)
        assert log.run_id == FAKE_RUN_ID

    def test_created_at_is_set(self):
        """created_at is a non-empty ISO timestamp."""
        log = _build_run_log(FAKE_RUN_ID)
        assert log.created_at and "T" in log.created_at
