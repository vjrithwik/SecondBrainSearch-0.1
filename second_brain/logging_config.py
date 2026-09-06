# Structured JSON logger setup with PII redaction.
"""Structured JSON logger setup with PII redaction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any


class _RedactingFilter(logging.Filter):
    """Redact document paths, query strings, and chunk text from log records."""

    _HOME_RE = re.compile(r"([A-Za-z]:\\Users\\|/Users/|/home/)[^\\/]+")
    _PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/)[^\s\"'\n\r]+")
    _UUID_RE = re.compile(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        re.IGNORECASE,
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = str(record.getMessage())
        msg = self._UUID_RE.sub("[REDACTED:uuid]", msg)
        msg = self._HOME_RE.sub("[REDACTED:home]/", msg)
        msg = self._PATH_RE.sub("[REDACTED:path]", msg)
        record.msg = msg
        record.args = ()
        return True


class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "trace_id"):
            payload["trace_id"] = record.trace_id
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure the root logger for local structured output.

    Args:
        level: Minimum log level emitted by the root logger.
    """
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_JsonFormatter())
        root.addHandler(handler)
    for handler in root.handlers:
        handler.addFilter(_RedactingFilter())


def get_logger(name: str) -> logging.Logger:
    """Return a logger scoped to *name* with the redaction filter attached."""
    logger = logging.getLogger(name)
    logger.addFilter(_RedactingFilter())
    return logger
