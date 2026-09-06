# Dual-queue IPC conventions for data and telemetry.
"""Dual-queue IPC conventions for data and telemetry."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from multiprocessing import Queue
from typing import Any


@dataclass(frozen=True)
class TelemetryEvent:
    """Progress or status event emitted by long-running operations."""

    event_type: str
    run_id: str
    payload: dict[str, Any] = field(default_factory=dict)


class TelemetryQueue:
    """Thin wrapper around a multiprocessing Queue for telemetry events."""

    def __init__(self, queue: Queue | None = None, maxsize: int = 1000) -> None:
        self._queue: Queue = queue or Queue(maxsize)

    def emit(self, event: TelemetryEvent) -> None:
        """Publish a telemetry event without blocking."""
        with suppress(Exception):
            self._queue.put_nowait(event)

    def get(self, timeout: float = 0.1) -> TelemetryEvent | None:
        """Consume one event, or None if the queue is empty."""
        with suppress(Exception):
            return self._queue.get(timeout=timeout)
        return None

    @property
    def raw_queue(self) -> Queue:
        """Return the underlying queue for integration with Qt signals."""
        return self._queue
