"""Footage QA gate — resolution, duration, and optional CLIP scoring.

Pure functions: no I/O. All image data and model handles are passed by the caller.
Importable by P9 AcquisitionWorker with no changes.
"""

import io
import logging
from dataclasses import dataclass
from typing import Any, Optional

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]  # PIL only needed when CLIP is enabled

logger = logging.getLogger(__name__)

# Minimum resolution thresholds
_MIN_VIDEO_WIDTH = 1280
_MIN_VIDEO_HEIGHT = 720
_MIN_PHOTO_WIDTH = 800

# CLIP cosine-similarity pass threshold
_CLIP_PASS_THRESHOLD = 0.20


@dataclass
class QAResult:
    """QA outcome for one asset candidate."""

    passed: bool
    resolution_ok: bool
    duration_ok: bool
    clip_score: Optional[float]
    clip_enabled: bool


def qa_score(
    candidate: Any,
    entry: Any,
    image_data: Optional[bytes] = None,
    clip_reranker: Optional[Any] = None,
) -> QAResult:
    """Score a candidate against the scene requirements.

    Checks resolution (from metadata), duration fit for video (from metadata),
    and optionally CLIP semantic similarity (requires image_data + clip_reranker).

    Pure — no I/O. The caller downloads image_data before passing it here.
    CLIP encoding failures never reject a candidate; clip_score stays None and
    the gate treats the check as passed.

    candidate must expose: width, height, duration_seconds (Optional[float]),
    clip_type is read from entry (hard_cut = video, else photo).
    """
    is_video = entry.clip_type == "hard_cut"

    # Resolution check
    if is_video:
        resolution_ok = (
            candidate.width >= _MIN_VIDEO_WIDTH
            and candidate.height >= _MIN_VIDEO_HEIGHT
        )
    else:
        resolution_ok = candidate.width >= _MIN_PHOTO_WIDTH

    # Duration check — video only; skipped when duration data is unavailable
    duration_ok = True
    if (
        is_video
        and getattr(candidate, "duration_seconds", None) is not None
        and getattr(entry, "duration_s", 0.0) > 0
    ):
        duration_ok = candidate.duration_seconds >= entry.duration_s

    # CLIP scoring
    clip_enabled = clip_reranker is not None
    clip_score: Optional[float] = None
    clip_ok = True

    if clip_enabled and image_data:
        try:
            img = Image.open(io.BytesIO(image_data)).convert("RGB")
            clip_score = clip_reranker.score_image(img, entry.primary_query)
            clip_ok = clip_score >= _CLIP_PASS_THRESHOLD
        except Exception as exc:
            logger.warning("CLIP scoring failed — accepting candidate anyway: %s", exc)
            # CLIP failure never rejects the candidate

    passed = resolution_ok and duration_ok and clip_ok

    return QAResult(
        passed=passed,
        resolution_ok=resolution_ok,
        duration_ok=duration_ok,
        clip_score=clip_score,
        clip_enabled=clip_enabled,
    )


def pick_best(candidates_with_results: list[tuple[Any, QAResult]]) -> Any:
    """Select the best candidate from all (candidate, QAResult) pairs.

    Priority order:
    1. Candidates that passed QA — highest CLIP score, then highest resolution.
    2. Candidates that failed QA — highest resolution (last resort).

    Raises ValueError when called with an empty list.
    """
    if not candidates_with_results:
        raise ValueError("pick_best called with empty list")

    def sort_key(pair: tuple) -> tuple:
        c, r = pair
        clip = r.clip_score if r.clip_score is not None else 0.0
        return (int(r.passed), clip, c.width * c.height)

    return max(candidates_with_results, key=sort_key)[0]
