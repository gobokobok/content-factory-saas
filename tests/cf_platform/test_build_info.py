"""Tests for cf_platform/core/build_info.py and GET /platform/version (D077)."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cf_platform.core.build_info import get_build_info
from cf_platform.interfaces.routes.meta import platform_version


@pytest.fixture
def stamp_file(tmp_path, monkeypatch):
    """Point get_build_info() at a temp build_info.json and clear the env vars."""
    monkeypatch.delenv("BUILD_SHA", raising=False)
    monkeypatch.delenv("BUILD_VERSION", raising=False)
    path = tmp_path / "build_info.json"
    monkeypatch.setattr("cf_platform.core.build_info._BUILD_INFO_FILE", path)
    return path


def test_reads_commit_and_version_from_stamp_file(stamp_file):
    """The CD workflow's stamp is what a deployed image reports."""
    stamp_file.write_text(json.dumps({"commit": "d2308fb", "version": "v0.22.0"}))

    assert get_build_info() == {"commit": "d2308fb", "version": "v0.22.0"}


def test_env_vars_take_precedence_over_stamp_file(stamp_file, monkeypatch):
    """BUILD_SHA/BUILD_VERSION are the escape hatch for a hand-rolled deploy."""
    stamp_file.write_text(json.dumps({"commit": "d2308fb", "version": "v0.22.0"}))
    monkeypatch.setenv("BUILD_SHA", "abc1234")
    monkeypatch.setenv("BUILD_VERSION", "v9.9.9")

    assert get_build_info() == {"commit": "abc1234", "version": "v9.9.9"}


def test_missing_stamp_file_falls_back_to_unknown(stamp_file):
    """A missing stamp must degrade to "unknown", never raise — this runs in a route."""
    assert not stamp_file.exists()

    assert get_build_info() == {"commit": "unknown", "version": "unknown"}


def test_malformed_stamp_file_falls_back_to_unknown(stamp_file):
    """Truncated or non-JSON stamp must not 500 the version endpoint."""
    stamp_file.write_text("{not json")

    assert get_build_info() == {"commit": "unknown", "version": "unknown"}


def test_non_dict_stamp_file_falls_back_to_unknown(stamp_file):
    """Valid JSON that isn't an object must not raise on .get()."""
    stamp_file.write_text("[1, 2, 3]")

    assert get_build_info() == {"commit": "unknown", "version": "unknown"}


def test_placeholder_stamp_is_tracked_and_valid_json():
    """The repo ships a GIT-TRACKED placeholder.

    This is the regression guard for the trap that bit during D077: .gitignore
    line 8 is a blanket `*.json`, which swallowed build_info.json on first
    write. The Railway CLI honours .gitignore when uploading the build context,
    so an ignored stamp never reaches the image and GET /platform/version
    silently regresses to "unknown" — with nothing failing anywhere. Existence
    alone is not enough to catch that; tracked-ness is the real invariant.
    """
    repo_root = Path(__file__).resolve().parents[2]
    repo_stamp = repo_root / "build_info.json"

    assert repo_stamp.exists(), "build_info.json must exist at the repo root"
    assert set(json.loads(repo_stamp.read_text())) == {"commit", "version"}

    if not (repo_root / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "build_info.json"],
        cwd=repo_root,
        capture_output=True,
    )
    assert tracked.returncode == 0, (
        "build_info.json is not git-tracked — .gitignore's blanket *.json will "
        "drop it from the Railway upload and /platform/version will report "
        '"unknown". Keep the `!build_info.json` negation in .gitignore.'
    )


@pytest.mark.asyncio
async def test_version_route_reports_commit_and_version(stamp_file):
    """GET /platform/version surfaces the stamp alongside the async-worker flags."""
    stamp_file.write_text(json.dumps({"commit": "d2308fb", "version": "v0.22.0"}))

    body = await platform_version()

    assert body["commit"] == "d2308fb"
    assert body["version"] == "v0.22.0"
    assert body["storyboard_async"] is True
    assert body["voice_async"] is True


@pytest.mark.asyncio
async def test_version_route_never_shells_out_to_git(stamp_file):
    """Pre-D077 the route ran `git rev-parse`, which always failed in the image."""
    stamp_file.write_text(json.dumps({"commit": "d2308fb", "version": "v0.22.0"}))

    with patch("subprocess.check_output", side_effect=AssertionError("must not shell out")):
        body = await platform_version()

    assert body["commit"] == "d2308fb"
