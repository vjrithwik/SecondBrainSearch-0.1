# Controller layer bridging the UI to services and storage.
"""Controller layer bridging the UI to services and storage."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from second_brain.config import DEFAULT_DB_PATH
from second_brain.embedder import create_embedder
from second_brain.queues import TelemetryQueue
from second_brain.services.admin import IndexAdminService, PurgeRequest
from second_brain.services.indexing import (
    DirectoryService,
    IndexingService,
    StartIndexingRequest,
)
from second_brain.services.search import SearchQuery, SearchService
from second_brain.storage import Storage


class AppController:
    """High-level application controller."""

    def __init__(
        self,
        db_path: Path | None = None,
        telemetry: TelemetryQueue | None = None,
    ) -> None:
        self._db_path = db_path or DEFAULT_DB_PATH
        self._storage = Storage(self._db_path)
        self._storage.ensure_schema()
        self._storage.initialize_index_record()
        self._search_service = SearchService(self._storage)
        self._admin_service = IndexAdminService(self._storage)
        self._directory_service = DirectoryService(self._storage)
        self._indexing_service = IndexingService(
            self._storage,
            embedder=create_embedder(),
            telemetry=telemetry or TelemetryQueue(),
        )

    @property
    def storage(self) -> Storage:
        """Return the underlying storage (for advanced consumers)."""
        return self._storage

    @property
    def indexing_service(self) -> IndexingService:
        return self._indexing_service

    @property
    def search_service(self) -> SearchService:
        return self._search_service

    @property
    def admin_service(self) -> IndexAdminService:
        return self._admin_service

    def select_directory(
        self, directory_path: str, display_name: str | None = None
    ) -> dict[str, Any]:
        """Validate and register a directory for indexing."""
        result = self._directory_service.select_directory(
            directory_path, display_name=display_name
        )
        return {
            "directory_id": result.directory_id,
            "directory_path": result.directory_path,
            "is_default": result.is_default,
            "requires_system_wide_confirmation": result.requires_system_wide_confirmation,
        }

    def set_directory_display_name(
        self, directory_id: str, display_name: str
    ) -> None:
        """Set the user-defined short name for an indexed directory."""
        self._storage.set_directory_display_name(directory_id, display_name)

    def start_indexing(
        self,
        directory_path: str,
        resume_run_id: str | None = None,
        on_started: Callable[[str], None] | None = None,
    ) -> Any:
        """Run an indexing synchronously and return the summary.

        If *resume_run_id* is provided, continue a previously interrupted run.
        The optional *on_started* callback is invoked with the run id as soon
        as the run is created, before any files are processed.
        """
        request = StartIndexingRequest(
            directory_path=directory_path,
            confirm_system_wide_scan=True,
        )
        return self._indexing_service.start_indexing(
            request, resume_run_id=resume_run_id, on_started=on_started
        )

    def request_stop_indexing(self, run_id: str) -> None:
        """Ask the active indexing run to stop after the current file."""
        self._indexing_service.request_stop(run_id)

    def get_resume_prompt(self, directory_path: str) -> Any:
        """Return resume information for *directory_path* if one exists."""
        return self._directory_service.get_resume_prompt(directory_path)

    def search(
        self, query_text: str, top_k: int = 15, directory_scope: str | None = None
    ) -> Any:
        """Execute a search and return a result page.

        If *directory_scope* is provided, only documents under that directory
        path are returned.
        """
        return self._search_service.search(
            SearchQuery(
                query_text=query_text,
                top_k=top_k,
                directory_path=directory_scope,
            )
        )

    def get_indexed_directories(self) -> list[dict[str, Any]]:
        """Return directories that have been indexed and can be searched."""
        return self._storage.get_indexed_directories()

    def get_status(self) -> dict[str, Any]:
        """Return current index status."""
        return self._admin_service.get_status()

    def purge_directory(self, directory_id: str) -> Any:
        """Purge a single directory index."""
        return self._admin_service.purge_directory(directory_id)

    def purge(self, confirmed: bool) -> Any:
        """Purge the local index."""
        result = self._admin_service.purge(PurgeRequest(confirmed=confirmed))
        # Storage has been recreated; rewire services.
        self._storage = Storage(self._db_path)
        self._storage.ensure_schema()
        self._storage.initialize_index_record()
        self._search_service = SearchService(self._storage)
        self._admin_service = IndexAdminService(self._storage)
        self._directory_service = DirectoryService(self._storage)
        self._indexing_service = IndexingService(
            self._storage,
            embedder=create_embedder(),
            telemetry=self._indexing_service._telemetry,
        )
        return result

    def close(self) -> None:
        """Close the storage connection."""
        self._storage.close()
