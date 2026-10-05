"""Log redaction — keeps provider API keys out of every log line (P14b-S5).

httpx logs every request URL at INFO, and several providers carry the key in the
query string (Pixabay ``?key=``, Freesound ``?token=``). Rather than silencing
httpx, a formatter wrapper redacts the *final* formatted text, so messages,
exception text and tracebacks are all covered while other request logging stays.
"""

import logging
import re

_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(api_key|apikey|api-key|access_token|token|key)=[^&\s\"'<>)\]]+"
)
_REDACTED = "REDACTED"

_LOGGERS_WITH_OWN_HANDLERS = ("httpx", "httpcore", "uvicorn", "uvicorn.error", "uvicorn.access")


def redact_secrets(text: str) -> str:
    """Replace the value of key=, api_key=, apikey=, token= query parameters in text."""
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", text)


class RedactingFormatter(logging.Formatter):
    """Formatter that delegates to another formatter and redacts its output."""

    def __init__(self, inner: logging.Formatter | None = None) -> None:
        """Wrap `inner` (or a default Formatter when None)."""
        super().__init__()
        self._inner = inner or logging.Formatter()

    def format(self, record: logging.LogRecord) -> str:
        """Format the record with the wrapped formatter, then redact secrets."""
        return redact_secrets(self._inner.format(record))


def install_log_redaction() -> None:
    """Wrap the formatter of every root and library handler; safe to call repeatedly."""
    loggers = [logging.getLogger()] + [logging.getLogger(n) for n in _LOGGERS_WITH_OWN_HANDLERS]
    for logger in loggers:
        for handler in logger.handlers:
            if not isinstance(handler.formatter, RedactingFormatter):
                handler.setFormatter(RedactingFormatter(handler.formatter))
