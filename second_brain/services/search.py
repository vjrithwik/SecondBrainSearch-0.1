# Service for executing semantic and filename-keyword searches.
"""Search service for natural-language and filename-keyword retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from second_brain.config import EMBEDDING_DIMENSION
from second_brain.embedder import Embedder, create_embedder
from second_brain.exceptions import NotReadyError, ValidationError
from second_brain.storage import Storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchQuery:
    """User search request."""

    query_text: str
    top_k: int = 15
    query_type: str = "NATURAL_LANGUAGE"
    directory_path: str | None = None


@dataclass(frozen=True)
class SearchResult:
    """Single ranked document result."""

    file_id: str
    file_name: str
    file_path: str
    score: float
    matched_chunk_count: int


@dataclass(frozen=True)
class SearchResultPage:
    """Page of search results."""

    query_text: str
    total_results: int
    results: list[SearchResult]


@dataclass(frozen=True)
class SearchReadiness:
    """Index readiness status."""

    ready: bool
    reason: str


class SearchService:
    """Execute semantic and filename-keyword searches."""

    _VALID_QUERY_TYPES = {"NATURAL_LANGUAGE", "FILENAME_KEYWORD"}

    def __init__(
        self, storage: Storage, embedder: Embedder | None = None
    ) -> None:
        self._storage = storage
        self._embedder = embedder or create_embedder()

    def search(self, query: SearchQuery) -> SearchResultPage:
        """Return ranked search results for *query*."""
        self._validate_query(query)
        readiness = self.is_search_ready()
        if not readiness.ready:
            raise NotReadyError(readiness.reason)

        embedding = self._embedder.encode([query.query_text])[0]
        if len(embedding) != EMBEDDING_DIMENSION:
            raise ValidationError(
                f"Embedding dimension must be {EMBEDDING_DIMENSION}"
            )

        if query.directory_path:
            rows = self._storage.search_chunks_scoped(
                query.directory_path, embedding, top_k=query.top_k
            )
        else:
            rows = self._storage.search_chunks(embedding, top_k=query.top_k)
        results = [
            SearchResult(
                file_id=r["file_id"],
                file_name=r["file_name"],
                file_path=r["file_path"],
                score=min(1.0, max(0.0, r["score"])),
                matched_chunk_count=r["matched_chunk_count"],
            )
            for r in rows
        ]
        return SearchResultPage(
            query_text=query.query_text,
            total_results=len(results),
            results=results,
        )

    def is_search_ready(self) -> SearchReadiness:
        """Return whether the index is ready for search."""
        try:
            status = self._storage.get_index_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not determine index status: %s", exc)
            return SearchReadiness(ready=False, reason="NO_INDEX_FILE")

        if status.get("status") == "ACTIVE":
            return SearchReadiness(ready=True, reason="INDEX_READY")
        if status.get("document_count", 0) == 0:
            return SearchReadiness(ready=False, reason="INDEX_EMPTY")
        return SearchReadiness(ready=False, reason="INDEXING_IN_PROGRESS")

    def _validate_query(self, query: SearchQuery) -> None:
        if not query.query_text or not query.query_text.strip():
            raise ValidationError("query_text is required", "query_text")
        if len(query.query_text) > 512:
            raise ValidationError(
                "query_text must be 512 characters or fewer", "query_text"
            )
        if query.top_k < 1 or query.top_k > 100:
            raise ValidationError("top_k must be between 1 and 100", "top_k")
        if query.query_type not in self._VALID_QUERY_TYPES:
            raise ValidationError(
                f"query_type must be one of {self._VALID_QUERY_TYPES}",
                "query_type",
            )
