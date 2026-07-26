"""Tests for R2Client — all boto3 calls are mocked."""

import io
import json
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
            call_kwargs = mock_boto.call_args.kwargs
            assert call_kwargs["endpoint_url"] == f"https://{FAKE_ACCOUNT_ID}.r2.cloudflarestorage.com"
            assert call_kwargs["aws_access_key_id"] == FAKE_ACCESS_KEY
            assert call_kwargs["aws_secret_access_key"] == FAKE_SECRET_KEY
            assert call_kwargs["region_name"] == "auto"

    def test_boto3_called_with_pool_size_50(self):
        """boto3.client is configured with max_pool_connections=50 for parallel list_runs."""
        with patch("src.storage.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            R2Client(FAKE_ACCOUNT_ID, FAKE_ACCESS_KEY, FAKE_SECRET_KEY, FAKE_BUCKET)
            config_arg = mock_boto.call_args.kwargs.get("config")
            assert config_arg is not None
            assert config_arg.max_pool_connections == 50

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

    def test_project_name_stored_in_run_log(self, client, mock_s3):
        """project_name is written into run_log.json when provided."""
        import json
        client.create_run_folder(FAKE_RUN_ID, project_name="Housing Crisis")
        body_bytes = mock_s3.put_object.call_args.kwargs["Body"]
        data = json.loads(body_bytes.decode("utf-8"))
        assert data["project_name"] == "Housing Crisis"

    def test_project_name_none_when_omitted(self, client, mock_s3):
        """project_name is null in run_log.json when not provided."""
        import json
        client.create_run_folder(FAKE_RUN_ID)
        body_bytes = mock_s3.put_object.call_args.kwargs["Body"]
        data = json.loads(body_bytes.decode("utf-8"))
        assert data["project_name"] is None


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


class TestListRuns:
    def _make_run_log(self, run_id: str, created_at: str) -> dict:
        """Return a minimal run_log dict."""
        return {
            "run_id": run_id,
            "created_at": created_at,
            "steps": {step: {"status": "pending"} for step in PIPELINE_STEPS},
        }

    def _prefix_response(self, *run_ids: str) -> dict:
        """Build a list_objects_v2 response with CommonPrefixes for the given run IDs."""
        return {
            "CommonPrefixes": [{"Prefix": f"runs/{rid}/"} for rid in run_ids]
        }

    def test_returns_empty_list_when_no_runs(self, client, mock_s3):
        """list_runs returns [] when no run prefixes exist."""
        mock_s3.list_objects_v2.return_value = {}
        result = client.list_runs()
        assert result == []

    def test_uses_delimiter_to_list_prefixes(self, client, mock_s3):
        """list_objects_v2 is called with Delimiter='/' to avoid enumerating asset keys."""
        mock_s3.list_objects_v2.return_value = {}
        client.list_runs()
        mock_s3.list_objects_v2.assert_called_once_with(
            Bucket=FAKE_BUCKET,
            Prefix="runs/",
            Delimiter="/",
        )

    def test_returns_run_summary_for_each_run(self, client, mock_s3):
        """list_runs returns one summary per discovered run prefix."""
        mock_s3.list_objects_v2.return_value = self._prefix_response(FAKE_RUN_ID)
        log_data = self._make_run_log(FAKE_RUN_ID, "2026-05-22T10:00:00+00:00")
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(log_data).encode())}
        result = client.list_runs()
        assert len(result) == 1
        assert result[0]["run_id"] == FAKE_RUN_ID
        assert result[0]["created_at"] == "2026-05-22T10:00:00+00:00"

    def test_steps_flattened_to_status_strings(self, client, mock_s3):
        """list_runs flattens steps to {step: status} strings."""
        mock_s3.list_objects_v2.return_value = self._prefix_response(FAKE_RUN_ID)
        log_data = self._make_run_log(FAKE_RUN_ID, "2026-05-22T10:00:00+00:00")
        log_data["steps"]["storyboard"]["status"] = "complete"
        mock_s3.get_object.return_value = {"Body": io.BytesIO(json.dumps(log_data).encode())}
        result = client.list_runs()
        assert result[0]["steps"]["storyboard"] == "complete"

    def test_sorted_by_created_at_descending(self, client, mock_s3):
        """list_runs returns runs sorted newest first regardless of listing order."""
        mock_s3.list_objects_v2.return_value = self._prefix_response(
            "2026-05-21_older", "2026-05-22_newer"
        )
        older = self._make_run_log("2026-05-21_older", "2026-05-21T08:00:00+00:00")
        newer = self._make_run_log("2026-05-22_newer", "2026-05-22T08:00:00+00:00")
        logs = {
            "runs/2026-05-21_older/run_log.json": older,
            "runs/2026-05-22_newer/run_log.json": newer,
        }

        def fake_get_object(**kwargs):
            data = logs[kwargs["Key"]]
            return {"Body": io.BytesIO(json.dumps(data).encode())}

        mock_s3.get_object.side_effect = fake_get_object
        result = client.list_runs()
        assert result[0]["run_id"] == "2026-05-22_newer"
        assert result[1]["run_id"] == "2026-05-21_older"

    def test_skips_run_with_unreadable_log(self, client, mock_s3):
        """A run whose run_log.json raises StorageError is silently skipped."""
        mock_s3.list_objects_v2.return_value = self._prefix_response(FAKE_RUN_ID)
        mock_s3.get_object.side_effect = Exception("key not found")
        result = client.list_runs()
        assert result == []

    def test_partial_failure_returns_readable_runs(self, client, mock_s3):
        """A single unreadable run_log.json does not prevent other runs from being listed."""
        mock_s3.list_objects_v2.return_value = self._prefix_response(
            "2026-05-21_bad", "2026-05-22_good"
        )
        good_log = self._make_run_log("2026-05-22_good", "2026-05-22T08:00:00+00:00")

        def fake_get_object(**kwargs):
            if "bad" in kwargs["Key"]:
                raise Exception("corrupted")
            return {"Body": io.BytesIO(json.dumps(good_log).encode())}

        mock_s3.get_object.side_effect = fake_get_object
        result = client.list_runs()
        assert len(result) == 1
        assert result[0]["run_id"] == "2026-05-22_good"

    def test_list_failure_raises_storage_error(self, client, mock_s3):
        """list_objects_v2 failure propagates as StorageError."""
        mock_s3.list_objects_v2.side_effect = Exception("R2 unreachable")
        with pytest.raises(StorageError, match="R2 list failed"):
            client.list_runs()


class TestGeneratePresignedUrl:
    def test_returns_url_string(self, client, mock_s3):
        """generate_presigned_url returns the URL from boto3."""
        mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
        result = client.generate_presigned_url("runs/test/output/final.mp4")
        assert result == "https://example.com/signed"

    def test_calls_boto3_with_correct_params(self, client, mock_s3):
        """boto3 generate_presigned_url is called with get_object and correct key."""
        mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
        client.generate_presigned_url("runs/test/output/final.mp4", expires_in=3600)
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": FAKE_BUCKET, "Key": "runs/test/output/final.mp4"},
            ExpiresIn=3600,
        )

    def test_default_expires_in_is_3600(self, client, mock_s3):
        """Default expiry is 1 hour (3600 seconds)."""
        mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
        client.generate_presigned_url("runs/test/output/final.mp4")
        call_kwargs = mock_s3.generate_presigned_url.call_args.kwargs
        assert call_kwargs["ExpiresIn"] == 3600

    def test_failure_raises_storage_error(self, client, mock_s3):
        """boto3 failure propagates as StorageError."""
        mock_s3.generate_presigned_url.side_effect = Exception("credentials expired")
        with pytest.raises(StorageError, match="Failed to generate presigned URL"):
            client.generate_presigned_url("runs/test/output/final.mp4")


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

    def test_project_name_stored_when_provided(self):
        """project_name is set when passed to _build_run_log."""
        log = _build_run_log(FAKE_RUN_ID, project_name="Housing Crisis")
        assert log.project_name == "Housing Crisis"

    def test_project_name_none_by_default(self):
        """project_name is None when not provided."""
        log = _build_run_log(FAKE_RUN_ID)
        assert log.project_name is None


class TestDeleteRun:
    def test_deletes_all_keys_and_returns_count(self, client, mock_s3):
        """delete_run calls delete_objects and returns the key count."""
        keys = [f"runs/{FAKE_RUN_ID}/run_log.json", f"runs/{FAKE_RUN_ID}/storyboard.json"]
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": k} for k in keys]}
        count = client.delete_run(FAKE_RUN_ID)
        assert count == 2
        mock_s3.delete_objects.assert_called_once_with(
            Bucket=FAKE_BUCKET,
            Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
        )

    def test_raises_storage_error_when_run_not_found(self, client, mock_s3):
        """Empty prefix (no keys) raises StorageError with 'not found'."""
        mock_s3.list_objects_v2.return_value = {}
        with pytest.raises(StorageError, match="not found"):
            client.delete_run(FAKE_RUN_ID)

    def test_raises_storage_error_on_delete_objects_failure(self, client, mock_s3):
        """ClientError from delete_objects propagates as StorageError."""
        from botocore.exceptions import ClientError
        keys = [f"runs/{FAKE_RUN_ID}/run_log.json"]
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": k} for k in keys]}
        mock_s3.delete_objects.side_effect = ClientError(
            {"Error": {"Code": "InternalError", "Message": "R2 error"}}, "DeleteObjects"
        )
        with pytest.raises(StorageError):
            client.delete_run(FAKE_RUN_ID)
