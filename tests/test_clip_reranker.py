"""Tests for CLIP semantic reranking (src/clip_reranker.py)."""

from __future__ import annotations

import io
import numpy as np
import pytest
from typing import Optional
from unittest.mock import MagicMock, patch, Mock

import src.clip_reranker as cr
from src.clip_reranker import (
    CLIPReranker,
    _cosine_similarity,
    get_reranker,
    load_model,
)
from src.exceptions import CLIPError


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_reranker():
    """Reset module-level singleton before and after each test."""
    cr._reranker = None
    yield
    cr._reranker = None


def _make_mock_model(
    text_emb: Optional[np.ndarray] = None,
    img_embs: Optional[np.ndarray] = None,
) -> MagicMock:
    """Return a mock SentenceTransformer that returns given embeddings."""
    model = MagicMock()
    if text_emb is None:
        text_emb = np.array([[1.0, 0.0]])
    if img_embs is None:
        img_embs = np.array([[0.9, 0.1]])

    # encode() is called first with a list[str] (text) then list[PIL] (images)
    model.encode.side_effect = [text_emb, img_embs]
    return model


def _make_reranker_with_thumbnails(
    model: MagicMock,
    thumbnail_bytes: Optional[bytes] = None,
) -> CLIPReranker:
    """Return a CLIPReranker whose session returns a fake thumbnail image."""
    from PIL import Image

    if thumbnail_bytes is None:
        img = Image.new("RGB", (100, 100), color=(128, 128, 128))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        thumbnail_bytes = buf.getvalue()

    reranker = CLIPReranker(model)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = thumbnail_bytes
    reranker._session = MagicMock()
    reranker._session.get.return_value = mock_resp
    return reranker


# ── _cosine_similarity ────────────────────────────────────────────────────────


def test_cosine_similarity_identical_vectors():
    a = np.array([1.0, 0.0])
    b = np.array([[1.0, 0.0], [0.0, 1.0]])
    scores = _cosine_similarity(a, b)
    assert abs(scores[0] - 1.0) < 1e-6
    assert abs(scores[1] - 0.0) < 1e-6


def test_cosine_similarity_returns_array_of_length_n():
    text = np.array([1.0, 1.0, 0.0])
    imgs = np.random.rand(5, 3)
    scores = _cosine_similarity(text, imgs)
    assert scores.shape == (5,)


def test_cosine_similarity_zero_norm_does_not_raise():
    text = np.array([0.0, 0.0])
    imgs = np.array([[1.0, 0.0], [0.0, 1.0]])
    # Should not raise; result values are not meaningful but call succeeds
    _cosine_similarity(text, imgs)


# ── load_model / get_reranker ─────────────────────────────────────────────────


def test_get_reranker_returns_none_before_load():
    assert get_reranker() is None


def _patch_sentence_transformers():
    """Return a context manager that injects a mock sentence_transformers module."""
    import sys
    mock_module = MagicMock()
    mock_cls = MagicMock()
    mock_module.SentenceTransformer = mock_cls
    return patch.dict(sys.modules, {"sentence_transformers": mock_module}), mock_cls


def test_load_model_sets_singleton():
    ctx, _ = _patch_sentence_transformers()
    with ctx:
        load_model()
    assert get_reranker() is not None


def test_load_model_called_once_on_repeated_invocations():
    ctx, mock_cls = _patch_sentence_transformers()
    with ctx:
        load_model()
        load_model()
    mock_cls.assert_called_once_with(cr._MODEL_NAME)


def test_load_model_uses_configured_model_name():
    ctx, mock_cls = _patch_sentence_transformers()
    with ctx:
        load_model()
    mock_cls.assert_called_once_with("clip-ViT-B-32")


# ── rerank_videos ─────────────────────────────────────────────────────────────


def test_rerank_videos_empty_list_returns_empty():
    model = _make_mock_model()
    reranker = CLIPReranker(model)
    assert reranker.rerank_videos([], "house") == []


def test_rerank_videos_single_item_returned():
    text_emb = np.array([[1.0, 0.0]])
    img_embs = np.array([[0.8, 0.2]])
    model = _make_mock_model(text_emb, img_embs)
    reranker = _make_reranker_with_thumbnails(model)

    videos = [{"image": "http://example.com/thumb.jpg", "id": 1}]
    result = reranker.rerank_videos(videos, "house")
    assert result == videos


def test_rerank_videos_sorts_by_similarity_descending():
    # text embedding close to v1, far from v2
    text_emb = np.array([[1.0, 0.0]])
    img_embs = np.array([[0.95, 0.05], [0.1, 0.9]])  # v1 >> v2
    model = MagicMock()
    model.encode.side_effect = [text_emb, img_embs]

    from PIL import Image

    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    thumb_bytes = buf.getvalue()

    reranker = CLIPReranker(model)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = thumb_bytes
    reranker._session = MagicMock()
    reranker._session.get.return_value = mock_resp

    videos = [
        {"image": "http://example.com/v1.jpg", "id": 1},
        {"image": "http://example.com/v2.jpg", "id": 2},
    ]
    result = reranker.rerank_videos(videos, "suburb house")
    # v1 (id=1) should rank first — higher similarity
    assert result[0]["id"] == 1
    assert result[1]["id"] == 2


def test_rerank_videos_unfetchable_thumbnail_goes_to_end():
    text_emb = np.array([[1.0, 0.0]])
    img_embs = np.array([[0.8, 0.2]])  # only one image encoded
    model = MagicMock()
    model.encode.side_effect = [text_emb, img_embs]

    from PIL import Image

    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    thumb_bytes = buf.getvalue()

    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.content = thumb_bytes

    bad_resp = MagicMock()
    bad_resp.status_code = 404

    reranker = CLIPReranker(model)
    reranker._session = MagicMock()
    reranker._session.get.side_effect = [good_resp, bad_resp]

    videos = [
        {"image": "http://example.com/v1.jpg", "id": 1},
        {"image": "http://example.com/v2.jpg", "id": 2},
    ]
    result = reranker.rerank_videos(videos, "house")
    # v2 (id=2) had no thumbnail — goes last
    assert result[-1]["id"] == 2


def test_rerank_videos_no_thumbnail_field_goes_to_unscored():
    model = MagicMock()
    model.encode.return_value = np.array([[1.0, 0.0]])

    reranker = CLIPReranker(model)
    videos = [{"id": 1}, {"id": 2}]  # no "image" key
    result = reranker.rerank_videos(videos, "house")
    # No thumbnails available — returned in original order as unscored
    assert [v["id"] for v in result] == [1, 2]


# ── rerank_photos ─────────────────────────────────────────────────────────────


def test_rerank_photos_empty_list_returns_empty():
    model = _make_mock_model()
    reranker = CLIPReranker(model)
    assert reranker.rerank_photos([], "house") == []


def test_rerank_photos_uses_src_medium_thumbnail():
    text_emb = np.array([[1.0, 0.0]])
    img_embs = np.array([[0.9, 0.1]])
    model = MagicMock()
    model.encode.side_effect = [text_emb, img_embs]
    reranker = _make_reranker_with_thumbnails(model)

    photos = [{"src": {"medium": "http://example.com/med.jpg"}, "id": 1}]
    reranker.rerank_photos(photos, "house")
    reranker._session.get.assert_called_with(
        "http://example.com/med.jpg", timeout=cr._THUMBNAIL_TIMEOUT
    )


def test_rerank_photos_sorts_by_similarity_descending():
    text_emb = np.array([[1.0, 0.0]])
    img_embs = np.array([[0.2, 0.8], [0.95, 0.05]])  # p2 >> p1
    model = MagicMock()
    model.encode.side_effect = [text_emb, img_embs]

    from PIL import Image

    img = Image.new("RGB", (10, 10))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    thumb_bytes = buf.getvalue()

    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.content = thumb_bytes

    reranker = CLIPReranker(model)
    reranker._session = MagicMock()
    reranker._session.get.return_value = good_resp

    photos = [
        {"src": {"medium": "http://example.com/p1.jpg"}, "id": 1},
        {"src": {"medium": "http://example.com/p2.jpg"}, "id": 2},
    ]
    result = reranker.rerank_photos(photos, "apartment")
    assert result[0]["id"] == 2
    assert result[1]["id"] == 1


# ── CLIPError propagation ─────────────────────────────────────────────────────


def test_rerank_raises_clip_error_on_text_encoding_failure():
    model = MagicMock()
    model.encode.side_effect = RuntimeError("OOM")
    reranker = _make_reranker_with_thumbnails(model)
    videos = [{"image": "http://example.com/v.jpg", "id": 1}]
    with pytest.raises(CLIPError, match="text encoding"):
        reranker.rerank_videos(videos, "house")


def test_rerank_raises_clip_error_on_image_encoding_failure():
    text_emb = np.array([[1.0, 0.0]])
    model = MagicMock()
    model.encode.side_effect = [text_emb, RuntimeError("GPU gone")]
    reranker = _make_reranker_with_thumbnails(model)
    videos = [{"image": "http://example.com/v.jpg", "id": 1}]
    with pytest.raises(CLIPError, match="image encoding"):
        reranker.rerank_videos(videos, "house")
