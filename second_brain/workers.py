# Sandboxed worker functions for document parsing.
"""Sandboxed worker functions for document parsing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from second_brain.parsers import ParseError, parse_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResult:
    """Outcome of parsing a single file in a worker process."""

    file_path: str
    file_format: str
    chunks: list[str]
    error: str | None = None


def parse_single_file(file_path: str) -> WorkerResult:
    """Parse one file and return a serialisable result.

    This function is designed to run inside a ProcessPoolExecutor worker.
    Exceptions are caught and converted to error results so that a single
    malformed file cannot crash the pool.
    """
    try:
        parsed = parse_file(Path(file_path))
        return WorkerResult(
            file_path=str(parsed.file_path),
            file_format=parsed.file_format,
            chunks=parsed.chunks,
        )
    except ParseError as exc:
        logger.warning("Parse error for %s: %s", file_path, exc)
        return WorkerResult(
            file_path=file_path,
            file_format="",
            chunks=[],
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - worker boundary
        logger.exception("Unexpected worker error for %s", file_path)
        return WorkerResult(
            file_path=file_path,
            file_format="",
            chunks=[],
            error=f"Unexpected error: {exc}",
        )
