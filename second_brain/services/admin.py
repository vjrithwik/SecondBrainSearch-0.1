
"""Index administration service (status and purge)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from second_brain.exceptions import ConfirmationRequiredError
from second_brain.storage import Storage


@dataclass(frozen=True)
class PurgeRequest:
    """Request to purge the local index."""

    confirmed: bool


@dataclass(frozen=True)
class PurgeResult:
    """Outcome of a purge operation."""

    purged: bool
    index_id: str
    storage_path: str
    deleted_at: str


class IndexAdminService:
    """Administer the local index."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def get_status(self) -> dict[str, Any]:
        """Return the current index status."""
        return self._storage.get_index_status()

    def purge_directory(self, directory_id: str) -> dict[str, Any]:
        """Delete a single directory index and its data."""
        self._storage.delete_directory(directory_id)
        return {"purged": True, "directory_id": directory_id}

    def purge(self, request: PurgeRequest) -> PurgeResult:
        """Delete the local index after explicit confirmation.

        Raises:
            ConfirmationRequiredError: If *request.confirmed* is False.
        """
        if not request.confirmed:
            raise ConfirmationRequiredError(
                "Purge requires explicit confirmation"
            )
        status = self._storage.get_index_status()
        result = self._storage.purge()
        self._storage.reset_after_purge()
        self._storage.initialize_index_record()
        return PurgeResult(
            purged=result["purged"],
            index_id=status["index_id"],
            storage_path=status["storage_path"],
            deleted_at=datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        )
