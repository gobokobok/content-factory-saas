"""Build metadata baked into the image at deploy time (D077)."""

import json
import os
from pathlib import Path

_BUILD_INFO_FILE = Path(__file__).resolve().parents[2] / "build_info.json"


def get_build_info() -> dict[str, str]:
    """Return the commit and release tag this image was built from.

    Resolution order per field: the BUILD_SHA / BUILD_VERSION env vars (settable
    per-service in Railway for a hand-rolled deploy), then build_info.json —
    written by the CD workflow before `railway up` uploads the directory, and
    baked into the image by the Dockerfile's `COPY . .` — then "unknown".

    Never shells out to `git`: the built image has neither a .git directory nor
    a git binary, so the pre-D077 `git rev-parse` call always returned
    "unknown" in production (D077).
    """
    try:
        stamped = json.loads(_BUILD_INFO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamped = {}
    if not isinstance(stamped, dict):
        stamped = {}
    return {
        "commit": os.environ.get("BUILD_SHA") or stamped.get("commit") or "unknown",
        "version": os.environ.get("BUILD_VERSION") or stamped.get("version") or "unknown",
    }
