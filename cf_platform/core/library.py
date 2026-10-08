"""Tenant-wide asset libraries — every video, voiceover, clip and AI image in one list.

Assets are stored per run (`runs/{run_id}/…` in R2). A library lists them across the
tenant's runs: each asset carries a stable, quotable ID, the project and run it
belongs to, and a download link. Nothing is indexed or copied — the listing reads the
run folders — so a library can never disagree with the runs; the price is one storage
listing per run, which is fine at a single operator's scale.

Libraries: videos, audio, footage (acquired or uploaded images and clips), ai
(AI-generated images, including replaced ones) and music (shared tracks and SFX).
"""

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any

LIBRARY_KINDS = ("videos", "audio", "footage", "ai", "music")

_ID_PREFIX = {"videos": "VID", "audio": "AUD", "footage": "FTG", "ai": "AIG", "music": "MUS"}
_VIDEO_EXT = (".mp4", ".mov", ".webm")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
_AUDIO_EXT = (".mp3", ".wav", ".m4a")
_AI_MARK = "_ai_"


class UnknownLibraryError(ValueError):
    """Raised for a library kind that does not exist."""


@dataclass(frozen=True)
class RunRef:
    """The run an asset belongs to — enough to label it."""

    run_id: str
    run_name: str
    project_id: str
    project_name: str
    created_at: str


def asset_id(kind: str, key: str) -> str:
    """A stable, quotable ID for an asset: a kind prefix and six hex digits of its storage key's hash."""
    if kind not in _ID_PREFIX:
        raise UnknownLibraryError(f"Unknown library {kind!r} — expected one of {list(LIBRARY_KINDS)}")
    return f"{_ID_PREFIX[kind]}-{hashlib.sha1(key.encode()).hexdigest()[:6].upper()}"


def _ext(key: str) -> str:
    """Lower-case file extension of a storage key, with the dot."""
    name = key.rsplit("/", 1)[-1]
    return name[name.rfind(".") :].lower() if "." in name else ""


def _name(key: str) -> str:
    """File name part of a storage key."""
    return key.rsplit("/", 1)[-1]


def classify_run_keys(
    kind: str, keys: dict[str, list[str]], in_use: set[str] | None = None
) -> list[dict[str, Any]]:
    """Pick one library's assets out of a run's file listing.

    `keys` maps a folder (output, voiceover, video, images) to the keys under it.
    `in_use` is the set of keys the run's current manifest points at; it decides
    whether an AI image is "in use" or "replaced". Returns dicts with key, name,
    facts and facet, in a stable order.
    """
    out: list[dict[str, Any]] = []
    if kind == "videos":
        for key in sorted(keys.get("output", [])):
            if _ext(key) in _VIDEO_EXT:
                out.append({"key": key, "name": _name(key), "facts": "final video", "facet": "video"})
    elif kind == "audio":
        for key in sorted(keys.get("voiceover", [])):
            if _ext(key) in _AUDIO_EXT:
                generated = _name(key).startswith("generated")
                out.append({
                    "key": key, "name": _name(key),
                    "facts": "generated voiceover" if generated else "uploaded voiceover",
                    "facet": "generated" if generated else "uploaded",
                })
    elif kind == "footage":
        for key in sorted(keys.get("video", []) + keys.get("images", [])):
            ext = _ext(key)
            if _AI_MARK in _name(key) or ext not in _VIDEO_EXT + _IMAGE_EXT:
                continue
            is_video = ext in _VIDEO_EXT
            out.append({"key": key, "name": _name(key), "facts": "video" if is_video else "image",
                        "facet": "video" if is_video else "image"})
    elif kind == "ai":
        used = in_use or set()
        for key in sorted(keys.get("images", [])):
            if _AI_MARK in _name(key) and _ext(key) in _IMAGE_EXT:
                state = "in use" if key in used else "replaced"
                out.append({"key": key, "name": _name(key), "facts": f"AI image · {state}", "facet": state})
    return out


async def _run_listing(storage: Any, run_id: str, folders: tuple[str, ...]) -> dict[str, list[str]]:
    """List the named folders of one run; a failing folder reads as empty."""
    async def one(folder: str) -> list[str]:
        try:
            return await storage.list_keys(f"runs/{run_id}/{folder}/")
        except Exception:
            return []

    lists = await asyncio.gather(*(one(f) for f in folders))
    return dict(zip(folders, lists, strict=True))


_FOLDERS = {"videos": ("output",), "audio": ("voiceover",), "footage": ("video", "images"), "ai": ("images",)}


async def list_run_assets(
    kind: str, run: RunRef, storage: Any, manifest_keys: Any = None
) -> list[dict[str, Any]]:
    """The assets of one run for one library, labelled with the run and a download link.

    `manifest_keys` is an async callable returning the keys the run's manifest uses
    (only called for the AI library, to tell "in use" from "replaced").
    """
    keys = await _run_listing(storage, run.run_id, _FOLDERS[kind])
    in_use: set[str] = set()
    if kind == "ai" and keys.get("images") and manifest_keys is not None:
        try:
            in_use = await manifest_keys(run.run_id)
        except Exception:
            in_use = set()
    items = classify_run_keys(kind, keys, in_use)
    for item in items:
        item["asset_id"] = asset_id(kind, item["key"])
        item["project_id"], item["project_name"] = run.project_id, run.project_name
        item["run_id"], item["run_name"] = run.run_id, run.run_name
        item["created_at"] = run.created_at
        try:
            item["download_url"] = await storage.generate_presigned_url(item["key"], expires_in=3600)
        except Exception:
            item["download_url"] = None
    return items


async def list_shared_music(storage: Any, sfx_entries: list[Any]) -> list[dict[str, Any]]:
    """The shared music tracks (music-library/) and the curated SFX that have a file."""
    items: list[dict[str, Any]] = []
    try:
        music = await storage.list_keys("music-library/")
    except Exception:
        music = []
    for key in sorted(k for k in music if _ext(k) in _AUDIO_EXT):
        items.append({"key": key, "name": _name(key), "facts": "music", "facet": "music"})
    for entry in sfx_entries:
        key = f"sfx-library/{entry['key']}.mp3"
        items.append({"key": key, "name": entry.get("display_name", entry["key"]), "facts": "sound effect",
                      "facet": "sfx"})
    for item in items:
        item["asset_id"] = asset_id("music", item["key"])
        item["project_id"] = item["project_name"] = item["run_id"] = item["run_name"] = None
        item["created_at"] = None
        try:
            item["download_url"] = await storage.generate_presigned_url(item["key"], expires_in=3600)
        except Exception:
            item["download_url"] = None
    return items
