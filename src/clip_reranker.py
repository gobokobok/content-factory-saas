"""CLIP semantic reranking for Pexels search results.

Uses sentence-transformers clip-ViT-B-32 to score thumbnails against the
scene's visual description text, surfacing the most semantically relevant
result at the top of the list before the existing size/resolution filter runs.

Loaded lazily at startup only when CLIP_RERANK_ENABLED=True. When disabled
(the default), get_reranker() returns None and PexelsClient falls back to its
original Pexels-order selection logic with no change in behaviour.
"""

import io
import logging
from typing import Optional

import numpy as np
import requests
from PIL import Image

from src.exceptions import CLIPError

logger = logging.getLogger(__name__)

_MODEL_NAME = "clip-ViT-B-32"
_THUMBNAIL_TIMEOUT = 10  # seconds per thumbnail fetch

_reranker: Optional["CLIPReranker"] = None


def load_model() -> None:
    """Load the CLIP model into the module-level singleton.

    Called once at startup when CLIP_RERANK_ENABLED=True. Safe to call
    multiple times — subsequent calls are no-ops.
    """
    global _reranker
    if _reranker is not None:
        return
    # Import here so sentence-transformers is not imported unless needed.
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    logger.info("Loading CLIP model: %s", _MODEL_NAME)
    model = SentenceTransformer(_MODEL_NAME)
    _reranker = CLIPReranker(model)
    logger.info("CLIP model loaded")


def get_reranker() -> Optional["CLIPReranker"]:
    """Return the loaded CLIPReranker singleton, or None if not loaded."""
    return _reranker


def _cosine_similarity(text_emb: np.ndarray, img_embs: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between one text vector and N image vectors.

    Returns a 1-D array of N similarity scores in [-1, 1]. Small epsilon
    prevents division by zero on zero-norm embeddings.
    """
    text_norm = text_emb / (np.linalg.norm(text_emb) + 1e-8)
    img_norms = img_embs / (np.linalg.norm(img_embs, axis=1, keepdims=True) + 1e-8)
    return img_norms @ text_norm


class CLIPReranker:
    """Scores Pexels thumbnails against a text query using CLIP embeddings."""

    def __init__(self, model: object) -> None:
        """Initialise with a loaded SentenceTransformer CLIP model."""
        self._model = model
        self._session = requests.Session()

    def _fetch_thumbnail(self, url: str) -> Optional[Image.Image]:
        """Download thumbnail and return a PIL Image, or None on any failure."""
        try:
            resp = self._session.get(url, timeout=_THUMBNAIL_TIMEOUT)
            if resp.status_code != 200:
                logger.debug("Thumbnail fetch HTTP %d: %s", resp.status_code, url)
                return None
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
        except Exception as exc:
            logger.debug("Thumbnail fetch error %s: %s", url, exc)
            return None

    def score_image(self, image: "Image.Image", text: str) -> float:
        """Return CLIP cosine similarity between one image and a text query.

        Used by footage_qa.qa_score to check a single asset against the scene
        visual description. Raises CLIPError on encoding failure.
        """
        try:
            text_emb = self._model.encode([text])
        except Exception as exc:
            raise CLIPError(f"CLIP text encoding failed for query '{text}': {exc}") from exc
        try:
            img_emb = self._model.encode([image])
        except Exception as exc:
            raise CLIPError(f"CLIP image encoding failed: {exc}") from exc
        scores = _cosine_similarity(text_emb[0], img_emb)
        return float(scores[0])

    def rerank_videos(self, videos: list[dict], query: str) -> list[dict]:
        """Return videos sorted by CLIP similarity to query (descending).

        Uses the Pexels `image` thumbnail field. Videos whose thumbnails
        cannot be fetched are kept at the bottom of the list in original order.
        Raises CLIPError if model encoding fails.
        """
        if not videos:
            return videos
        return self._rerank(videos, query, thumbnail_fn=lambda v: v.get("image"))

    def rerank_photos(self, photos: list[dict], query: str) -> list[dict]:
        """Return photos sorted by CLIP similarity to query (descending).

        Uses the `src.medium` thumbnail. Photos whose thumbnails cannot be
        fetched are kept at the bottom of the list in original order.
        Raises CLIPError if model encoding fails.
        """
        if not photos:
            return photos
        return self._rerank(
            photos, query, thumbnail_fn=lambda p: p.get("src", {}).get("medium")
        )

    def _rerank(
        self,
        items: list[dict],
        query: str,
        thumbnail_fn,
    ) -> list[dict]:
        """Score items by CLIP similarity to query text and return sorted list.

        Items whose thumbnails cannot be fetched are placed after all scored
        items, preserving their relative order. Raises CLIPError on encoding
        failure.
        """
        try:
            text_emb = self._model.encode([query])  # shape (1, D)
        except Exception as exc:
            raise CLIPError(
                f"CLIP text encoding failed for query '{query}': {exc}"
            ) from exc

        scoreable: list[dict] = []
        images: list[Image.Image] = []
        unscored: list[dict] = []

        for item in items:
            url = thumbnail_fn(item)
            if not url:
                unscored.append(item)
                continue
            img = self._fetch_thumbnail(url)
            if img is None:
                unscored.append(item)
                continue
            scoreable.append(item)
            images.append(img)

        if not images:
            return unscored

        try:
            img_embs = self._model.encode(images)  # shape (N, D)
        except Exception as exc:
            raise CLIPError(f"CLIP image encoding failed: {exc}") from exc

        scores = _cosine_similarity(text_emb[0], img_embs)
        ranked = sorted(
            zip(scores, scoreable),
            key=lambda x: x[0],
            reverse=True,
        )
        logger.debug(
            "CLIP reranked %d/%d items for query '%s' — top score %.3f",
            len(ranked),
            len(items),
            query,
            ranked[0][0] if ranked else 0.0,
        )
        return [item for _, item in ranked] + unscored
