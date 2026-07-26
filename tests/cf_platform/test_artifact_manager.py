"""Tests for cf_platform/core/artifact_manager.py (P1-S3)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from pydantic import BaseModel

from cf_platform.core.artifact_manager import (
    ArtifactStorageError,
    InMemoryArtifactStorage,
    R2ArtifactStorage,
    read_artifact,
    write_artifact,
)
from cf_platform.core.schemas import Artifact, LineageEnvelope


class _EchoBody(BaseModel):
    message: str


def _lineage(run_id: str = "run-1") -> LineageEnvelope:
    return LineageEnvelope(
        run_id=run_id,
        worker="echo",
        worker_version="v1",
        prompt_version="v1",
        model="claude-haiku-4-5-20251001",
        created_at=datetime.now(UTC),
    )


class TestWriteArtifact:
    @pytest.mark.asyncio
    async def test_first_write_is_version_1(self):
        """Writing an artifact for the first time produces version 1 with a versioned r2_key."""
        storage = InMemoryArtifactStorage()

        artifact = await write_artifact(
            storage,
            _EchoBody(message="hello"),
            name="echo",
            stage="echo_stage",
            run_id="run-1",
            user_id="user-1",
            lineage=_lineage(),
        )

        assert isinstance(artifact, Artifact)
        assert artifact.version == 1
        assert artifact.r2_key == "users/user-1/runs/run-1/echo_stage/echo@v1.json"
        assert artifact.name == "echo"
        assert artifact.stage == "echo_stage"
        assert artifact.run_id == "run-1"

    @pytest.mark.asyncio
    async def test_rewrite_creates_next_version_without_overwriting(self):
        """Re-writing the same (user, run, stage, name) creates @v2 and leaves @v1 intact."""
        storage = InMemoryArtifactStorage()

        first = await write_artifact(
            storage,
            _EchoBody(message="v1"),
            name="echo",
            stage="echo_stage",
            run_id="run-1",
            user_id="user-1",
            lineage=_lineage(),
        )
        second = await write_artifact(
            storage,
            _EchoBody(message="v2"),
            name="echo",
            stage="echo_stage",
            run_id="run-1",
            user_id="user-1",
            lineage=_lineage(),
        )

        assert first.version == 1
        assert second.version == 2
        assert second.r2_key == "users/user-1/runs/run-1/echo_stage/echo@v2.json"
        assert first.r2_key != second.r2_key

        # both versions remain readable — the first write was never overwritten
        _, body_v1 = await read_artifact(storage, first.r2_key)
        _, body_v2 = await read_artifact(storage, second.r2_key)
        assert body_v1 == {"message": "v1"}
        assert body_v2 == {"message": "v2"}

    @pytest.mark.asyncio
    async def test_different_names_and_stages_version_independently(self):
        """Versioning is scoped per (user_id, run_id, stage, name) — independent counters."""
        storage = InMemoryArtifactStorage()

        a1 = await write_artifact(
            storage, _EchoBody(message="a"), name="a", stage="stage1",
            run_id="run-1", user_id="user-1", lineage=_lineage(),
        )
        b1 = await write_artifact(
            storage, _EchoBody(message="b"), name="b", stage="stage1",
            run_id="run-1", user_id="user-1", lineage=_lineage(),
        )
        a2 = await write_artifact(
            storage, _EchoBody(message="a2"), name="a", stage="stage1",
            run_id="run-1", user_id="user-1", lineage=_lineage(),
        )

        assert a1.version == 1
        assert b1.version == 1
        assert a2.version == 2


class TestReadArtifact:
    @pytest.mark.asyncio
    async def test_round_trips_artifact_and_body(self):
        """read_artifact returns the same Artifact envelope and body that write_artifact produced."""
        storage = InMemoryArtifactStorage()
        lineage = _lineage()

        written = await write_artifact(
            storage,
            _EchoBody(message="round trip"),
            name="echo",
            stage="echo_stage",
            run_id="run-1",
            user_id="user-1",
            lineage=lineage,
        )

        artifact, body = await read_artifact(storage, written.r2_key)

        assert artifact == written
        assert _EchoBody.model_validate(body) == _EchoBody(message="round trip")

    @pytest.mark.asyncio
    async def test_missing_key_raises_artifact_storage_error(self):
        """Reading an unknown key raises ArtifactStorageError."""
        storage = InMemoryArtifactStorage()

        with pytest.raises(ArtifactStorageError):
            await read_artifact(storage, "users/user-1/runs/run-1/echo_stage/missing@v1.json")


class TestR2ArtifactStorage:
    def _client(self) -> R2ArtifactStorage:
        with patch("cf_platform.core.artifact_manager.boto3.client") as mock_boto:
            mock_boto.return_value = MagicMock()
            storage = R2ArtifactStorage("acct", "key", "secret", "bucket")
        return storage

    @pytest.mark.asyncio
    async def test_put_json_calls_put_object(self):
        """put_json serialises data to JSON and calls put_object with the right key/bucket."""
        storage = self._client()

        await storage.put_json("users/u/runs/r/stage/name@v1.json", {"artifact": {}, "body": {"x": 1}})

        storage._client.put_object.assert_called_once()
        kwargs = storage._client.put_object.call_args.kwargs
        assert kwargs["Bucket"] == "bucket"
        assert kwargs["Key"] == "users/u/runs/r/stage/name@v1.json"
        assert kwargs["ContentType"] == "application/json"

    @pytest.mark.asyncio
    async def test_get_json_returns_parsed_body(self):
        """get_json parses the JSON object returned by get_object."""
        storage = self._client()
        body_bytes = b'{"artifact": {}, "body": {"x": 1}}'
        mock_body = MagicMock()
        mock_body.read.return_value = body_bytes
        storage._client.get_object.return_value = {"Body": mock_body}

        result = await storage.get_json("users/u/runs/r/stage/name@v1.json")

        assert result == {"artifact": {}, "body": {"x": 1}}

    @pytest.mark.asyncio
    async def test_get_json_wraps_client_error(self):
        """A ClientError from get_object is wrapped in ArtifactStorageError."""
        storage = self._client()
        storage._client.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject"
        )

        with pytest.raises(ArtifactStorageError):
            await storage.get_json("users/u/runs/r/stage/missing@v1.json")

    @pytest.mark.asyncio
    async def test_list_keys_returns_key_list(self):
        """list_keys returns the Key field of each object under Contents."""
        storage = self._client()
        storage._client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "users/u/runs/r/stage/name@v1.json"},
                {"Key": "users/u/runs/r/stage/name@v2.json"},
            ]
        }

        keys = await storage.list_keys("users/u/runs/r/stage/name@v")

        assert keys == [
            "users/u/runs/r/stage/name@v1.json",
            "users/u/runs/r/stage/name@v2.json",
        ]

    @pytest.mark.asyncio
    async def test_list_keys_returns_empty_when_no_contents(self):
        """list_keys returns an empty list when the prefix has no matching objects."""
        storage = self._client()
        storage._client.list_objects_v2.return_value = {}

        keys = await storage.list_keys("users/u/runs/r/stage/none@v")

        assert keys == []
