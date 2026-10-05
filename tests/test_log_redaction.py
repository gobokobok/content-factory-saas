"""Tests for log redaction of provider API keys (P14b-S5)."""

import io
import logging

import pytest

from src.log_redaction import RedactingFormatter, install_log_redaction, redact_secrets

SECRET = "SUPERSECRET123"

URLS = [
    f"https://pixabay.com/api/?key={SECRET}&q=house&per_page=10",
    f"https://pixabay.com/api/videos/?q=house&key={SECRET}",
    f"https://freesound.org/apiv2/search/text/?query=whoosh&token={SECRET}&page_size=5",
    f"https://api.pexels.com/videos/search?query=house&api_key={SECRET}",
    f"https://example.com/x?apikey={SECRET}",
]


@pytest.mark.parametrize("url", URLS)
def test_redact_secrets_removes_value(url: str) -> None:
    """Every provider URL shape loses its secret but keeps host and other params."""
    out = redact_secrets(url)
    assert SECRET not in out
    assert "REDACTED" in out
    assert url.split("?")[0] in out


def test_redact_keeps_unrelated_params() -> None:
    """Parameters whose names merely contain 'key' are left alone."""
    assert redact_secrets("https://x.test/?monkey=1&keyword=a") == "https://x.test/?monkey=1&keyword=a"


def _capture() -> tuple[logging.Logger, io.StringIO]:
    """Build an isolated logger writing through a redacting handler."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    logger = logging.getLogger("test.redaction.isolated")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return logger, stream


def test_formatter_redacts_message_args_and_traceback() -> None:
    """Message, %-args and exception text/traceback are all redacted."""
    logger, stream = _capture()
    logger.handlers[0].setFormatter(RedactingFormatter(logging.Formatter("%(message)s")))
    logger.info('HTTP Request: GET %s "HTTP/1.1 200 OK"', URLS[0])
    try:
        raise RuntimeError(f"failed calling {URLS[2]}")
    except RuntimeError:
        logger.exception("boom")
    assert SECRET not in stream.getvalue()
    assert "key=REDACTED" in stream.getvalue()


def test_install_wraps_root_handlers_once() -> None:
    """install_log_redaction wraps existing handlers and is idempotent."""
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        install_log_redaction()
        install_log_redaction()
        assert isinstance(handler.formatter, RedactingFormatter)
        assert not isinstance(handler.formatter._inner, RedactingFormatter)
    finally:
        root.removeHandler(handler)
