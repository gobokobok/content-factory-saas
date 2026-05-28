"""Cloudflare R2 storage client — upload, download, and run_log helpers.

R2 is a flat key-value store; "folders" are key prefixes ending with '/'.
No folder creation is required — uploading a key like runs/foo/bar.json
implicitly creates the prefix structure in the R2 console view.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from src.exceptions import StorageError
from src.models import PIPELINE_STEPS, RunLog, StepLog

logger = logging.getLogger(__name__)

_R2_REGION = "auto"


class R2Client:
    """S3-compatible client for Cloudflare R2."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
    ) -> None:
        """Initialise boto3 S3 client pointed at the R2 endpoint for account_id."""
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
            raise StorageError(f"Failed to initialise R2 client: {exc}") from exc
        self._bucket = bucket_name

    def upload_json(self, key: str, data: dict) -> None:
        """Serialise data as JSON and upload to the given R2 key."""
        content = json.dumps(data, indent=2).encode("utf-8")
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType="application/json",
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 upload failed for '{key}': {exc}") from exc

    def upload_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        """Upload raw bytes (images, video files) to the given R2 key."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 upload failed for '{key}': {exc}") from exc

    def upload_text(self, key: str, content: str, content_type: str = "text/plain") -> None:
        """Encode content as UTF-8 and upload to the given R2 key."""
        self.upload_bytes(key, content.encode("utf-8"), content_type)

    def get_json(self, key: str) -> dict:
        """Download and parse a JSON object from R2."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return json.loads(response["Body"].read())
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 get failed for '{key}': {exc}") from exc

    def get_bytes(self, key: str) -> bytes:
        """Download raw bytes from R2."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 get failed for '{key}': {exc}") from exc

    def list_keys(self, prefix: str) -> list[str]:
        """List all R2 keys with the given prefix. Returns an empty list if none exist."""
        try:
            response = self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
            return [obj["Key"] for obj in response.get("Contents", [])]
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 list failed for prefix '{prefix}': {exc}") from exc

    def list_runs(self) -> list[dict]:
        """
        Return run summaries for all runs in R2.

        Uses delimiter-based listing to enumerate run prefixes without fetching
        individual asset keys, then fetches each run_log.json in parallel via a
        thread pool.  Runs whose run_log.json cannot be fetched are skipped.
        Returns a list of {run_id, created_at, steps} dicts sorted by
        created_at descending.
        """
        t_start = time.monotonic()

        try:
            response = self._client.list_objects_v2(
                Bucket=self._bucket,
                Prefix="runs/",
                Delimiter="/",
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"R2 list failed for prefix 'runs/': {exc}") from exc

        # CommonPrefixes contains entries like {"Prefix": "runs/{run_id}/"}
        prefixes = [p["Prefix"] for p in response.get("CommonPrefixes", [])]

        def _fetch(prefix: str) -> Optional[dict]:
            """Fetch run_log.json for one run prefix; return None on failure."""
            run_id = prefix.rstrip("/").split("/")[-1]
            key = f"{prefix}run_log.json"
            try:
                data = self.get_json(key)
            except StorageError:
                logger.warning("Skipping run with unreadable log: %s", key)
                return None
            return {
                "run_id": run_id,
                "created_at": data.get("created_at", ""),
                "steps": {
                    step: log.get("status", "pending")
                    for step, log in data.get("steps", {}).items()
                },
            }

        with ThreadPoolExecutor(max_workers=32) as executor:
            results = list(executor.map(_fetch, prefixes))

        runs = [r for r in results if r is not None]
        runs.sort(key=lambda r: r["created_at"], reverse=True)

        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.info(
            "list_runs: %d runs in %.0fms (parallelised across %d prefixes)",
            len(runs),
            elapsed_ms,
            len(prefixes),
        )
        return runs

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned GET URL for the given R2 key valid for expires_in seconds."""
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"Failed to generate presigned URL for '{key}': {exc}") from exc

    def generate_presigned_put_url(self, key: str, expires_in: int = 600) -> str:
        """Generate a presigned PUT URL for the given R2 key valid for expires_in seconds."""
        try:
            return self._client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError, Exception) as exc:
            raise StorageError(f"Failed to generate presigned PUT URL for '{key}': {exc}") from exc

    def create_run_folder(self, run_id: str) -> str:
        """
        Initialise a run prefix in R2 by uploading run_log.json.

        R2 has no real folders — the prefix runs/{run_id}/ exists implicitly
        once any key with that prefix is written. Returns the prefix string.
        """
        prefix = f"runs/{run_id}/"
        run_log = _build_run_log(run_id)
        self.upload_json(f"{prefix}run_log.json", run_log.model_dump(mode="json"))
        logger.info("Run prefix initialised: %s", prefix)
        return prefix

    def update_run_log(
        self,
        run_id: str,
        step: str,
        status: str,
        output_url: Optional[str] = None,
        error: Optional[str] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
    ) -> None:
        """Read, update, and re-upload run_log.json for the given step."""
        key = f"runs/{run_id}/run_log.json"
        data = self.get_json(key)
        data["steps"][step]["status"] = status
        if status == "complete":
            data["steps"][step]["completed_at"] = datetime.now(timezone.utc).isoformat()
        if output_url is not None:
            data["steps"][step]["output_url"] = output_url
        if error is not None:
            data["steps"][step]["error"] = error
        if input_tokens is not None:
            data["steps"][step]["input_tokens"] = input_tokens
        if output_tokens is not None:
            data["steps"][step]["output_tokens"] = output_tokens
        if cost_usd is not None:
            data["steps"][step]["cost_usd"] = cost_usd
        self.upload_json(key, data)
        logger.info("run_log updated: run=%s step=%s status=%s", run_id, step, status)


def _build_run_log(run_id: str) -> RunLog:
    """Construct a RunLog with all pipeline steps initialised to pending."""
    return RunLog(
        run_id=run_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        steps={step: StepLog() for step in PIPELINE_STEPS},
    )
