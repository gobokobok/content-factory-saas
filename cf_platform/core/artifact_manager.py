"""Artifact Manager (P1-S3) — write/read immutable, versioned artifacts to R2.

Artifacts are stored at `users/{user_id}/runs/{run_id}/{stage}/{name}@v{n}.json`
(plan §6, D055). A write never overwrites an existing key — it computes the next
version by listing existing `@v*` keys for the same (user_id, run_id, stage, name)
and writes `@v{n+1}`. Persistence sits behind the `ArtifactStorage` Protocol;
`InMemoryArtifactStorage` is used in tests, `R2ArtifactStorage` is a thin,
standalone boto3 client against the shared R2 bucket — separate from
src/storage.py's R2Client, since cf_platform may not import src/ (D047).
"""

import asyncio
import json
import re
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel

from cf_platform.core.schemas import Artifact, LineageEnvelope

_R2_REGION = "auto"
_VERSION_KEY_PATTERN = re.compile(r"@v(\d+)\.json$")


class ArtifactStorageError(Exception):
    """Raised when the backing key-value store fails to read, write, or list keys."""


class ArtifactStorage(Protocol):
    """Backing key-value store for artifact envelopes — swappable (R2 in prod, in-memory in tests)."""

    async def put_json(self, key: str, data: dict[str, Any]) -> None:
        """Serialise data as JSON and store it at key."""
        ...

    async def get_json(self, key: str) -> dict[str, Any]:
        """Return the JSON object stored at key. Raises ArtifactStorageError if absent."""
        ...

    async def list_keys(self, prefix: str) -> list[str]:
        """Return all keys starting with prefix. Returns an empty list if none exist."""
        ...


class ArtifactRepository(Protocol):
    """Postgres-index interface for Artifact rows (P2-S3, D048).

    Records the lineage row for an artifact already written to R2 by
    `write_artifact` — Postgres holds the `r2_key` + lineage columns, never the
    artifact body (R2 stays blob truth). Swappable: `InMemoryArtifactRepository`
    for tests, `PostgresArtifactRepository` (cf_platform/core/postgres_repos.py)
    in production.
    """

    async def record(self, artifact: Artifact) -> None:
        """Persist the lineage index row for artifact. Idempotent on (run_id, stage, name, version)."""
        ...

    async def list_for_run(self, run_id: str) -> list[Artifact]:
        """Return all recorded artifacts for run_id."""
        ...


class InMemoryArtifactRepository:
    """In-memory ArtifactRepository implementation — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._artifacts: list[Artifact] = []

    async def record(self, artifact: Artifact) -> None:
        """Append artifact to the in-memory list, skipping exact (run_id, stage, name, version) duplicates."""
        key = (artifact.run_id, artifact.stage, artifact.name, artifact.version)
        if any((a.run_id, a.stage, a.name, a.version) == key for a in self._artifacts):
            return
        self._artifacts.append(artifact)

    async def list_for_run(self, run_id: str) -> list[Artifact]:
        """Return all recorded artifacts for run_id, in recording order."""
        return [artifact for artifact in self._artifacts if artifact.run_id == run_id]


class InMemoryArtifactStorage:
    """In-memory ArtifactStorage implementation — process-local, not durable."""

    def __init__(self) -> None:
        """Initialize an empty in-memory store."""
        self._objects: dict[str, dict[str, Any]] = {}

    async def put_json(self, key: str, data: dict[str, Any]) -> None:
        """Serialise data as JSON and store it at key."""
        self._objects[key] = data

    async def get_json(self, key: str) -> dict[str, Any]:
        """Return the JSON object stored at key. Raises ArtifactStorageError if absent."""
        try:
            return self._objects[key]
        except KeyError:
            raise ArtifactStorageError(f"Artifact not found: {key}") from None

    async def list_keys(self, prefix: str) -> list[str]:
        """Return all keys starting with prefix. Returns an empty list if none exist."""
        return [key for key in self._objects if key.startswith(prefix)]


class R2ArtifactStorage:
    """Thin boto3-backed ArtifactStorage for Cloudflare R2.

    Standalone from src/storage.py's R2Client per D047 — cf_platform owns its own
    client against the shared R2 bucket rather than importing from src/.
    """

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
    ) -> None:
        """Initialise a boto3 S3 client pointed at the R2 endpoint for account_id."""
        endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        try:
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key_id,
                aws_secret_access_key=secret_access_key,
                region_name=_R2_REGION,
                config=Config(max_pool_connections=50),
            )
        except Exception as exc:
            raise ArtifactStorageError(f"Failed to initialise R2 client: {exc}") from exc
        self._bucket = bucket_name

    async def put_json(self, key: str, data: dict[str, Any]) -> None:
        """Serialise data as JSON and upload it to the given R2 key."""
        await asyncio.to_thread(self._put_json_sync, key, data)

    def _put_json_sync(self, key: str, data: dict[str, Any]) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=json.dumps(data, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise ArtifactStorageError(f"R2 upload failed for '{key}': {exc}") from exc

    async def get_json(self, key: str) -> dict[str, Any]:
        """Download and parse a JSON object from the given R2 key."""
        return await asyncio.to_thread(self._get_json_sync, key)

    def _get_json_sync(self, key: str) -> dict[str, Any]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return json.loads(response["Body"].read())
        except (BotoCoreError, ClientError, Exception) as exc:
            raise ArtifactStorageError(f"R2 get failed for '{key}': {exc}") from exc

    async def list_keys(self, prefix: str) -> list[str]:
        """List all R2 keys with the given prefix. Returns an empty list if none exist."""
        return await asyncio.to_thread(self._list_keys_sync, prefix)

    def _list_keys_sync(self, prefix: str) -> list[str]:
        try:
            response = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            return [obj["Key"] for obj in response.get("Contents", [])]
        except (BotoCoreError, ClientError, Exception) as exc:
            raise ArtifactStorageError(f"R2 list failed for prefix '{prefix}': {exc}") from exc


def _artifact_prefix(user_id: str, run_id: str, stage: str, name: str) -> str:
    """Return the R2 key prefix shared by all versions of one artifact."""
    return f"users/{user_id}/runs/{run_id}/{stage}/{name}@v"


async def _next_version(storage: ArtifactStorage, user_id: str, run_id: str, stage: str, name: str) -> int:
    """Return the next version number for (user_id, run_id, stage, name) — 1 if none exist."""
    prefix = _artifact_prefix(user_id, run_id, stage, name)
    keys = await storage.list_keys(prefix)
    versions = [int(match.group(1)) for key in keys if (match := _VERSION_KEY_PATTERN.search(key))]
    return max(versions, default=0) + 1


async def write_artifact(
    storage: ArtifactStorage,
    body: BaseModel,
    *,
    name: str,
    stage: str,
    run_id: str,
    user_id: str,
    lineage: LineageEnvelope,
    content_type: str = "application/json",
) -> Artifact:
    """Write body wrapped in an immutable, versioned Artifact envelope to storage.

    Computes the next version for (user_id, run_id, stage, name) and writes to
    `users/{user_id}/runs/{run_id}/{stage}/{name}@v{n}.json` — never overwrites an
    existing version (D055). Returns the Artifact record, including its r2_key.
    """
    version = await _next_version(storage, user_id, run_id, stage, name)
    r2_key = f"{_artifact_prefix(user_id, run_id, stage, name)}{version}.json"
    artifact = Artifact(
        name=name,
        stage=stage,
        version=version,
        run_id=run_id,
        content_type=content_type,
        r2_key=r2_key,
        lineage=lineage,
    )
    await storage.put_json(r2_key, {"artifact": artifact.model_dump(mode="json"), "body": body.model_dump(mode="json")})
    return artifact


async def read_artifact(storage: ArtifactStorage, r2_key: str) -> tuple[Artifact, dict[str, Any]]:
    """Read an artifact envelope + body from storage by r2_key.

    Returns the Artifact record and the body as a plain dict (deserialise into the
    caller's expected Pydantic model via `model_validate`).
    """
    data = await storage.get_json(r2_key)
    return Artifact.model_validate(data["artifact"]), data["body"]
