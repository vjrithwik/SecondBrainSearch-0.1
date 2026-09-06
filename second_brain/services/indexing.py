

"""Directory selection, crawling, and indexing services."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import (
    Executor,
    ThreadPoolExecutor,
    as_completed,
)
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from second_brain.config import (
    DEFAULT_DB_PATH,
    INDEXING_PARSE_WORKERS,
    INDEXING_YIELD_EVERY_N_FILES,
    MAX_WORKER_PROCESSES,
)
from second_brain.embedder import Embedder, create_embedder
from second_brain.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from second_brain.parsers import chunk_text, is_supported
from second_brain.queues import TelemetryEvent, TelemetryQueue
from second_brain.security import is_system_wide_scan, validate_directory_path
from second_brain.storage import ChunkRow, Storage
from second_brain.workers import WorkerResult, parse_single_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartIndexingRequest:
    """Request to start an indexing run."""

    directory_path: str
    confirm_system_wide_scan: bool = False


@dataclass(frozen=True)
class IndexingRunSummary:
    """Summary of an indexing run."""

    run_id: str
    status: str
    directory_path: str
    started_at: str
    completed_at: str | None
    files_processed: int
    files_skipped: int
    error_log: str | None


@dataclass(frozen=True)
class DirectorySelectionResult:
    """Result of selecting a directory for indexing."""

    directory_id: str
    directory_path: str
    is_default: bool
    requires_system_wide_confirmation: bool


@dataclass(frozen=True)
class ResumePrompt:
    """Information needed by the UI to offer resuming an interrupted run."""

    run_id: str
    directory_path: str
    files_processed: int
    last_processed_path: str | None


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


class DirectoryService:
    """Select and register directories for indexing."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def select_directory(
        self,
        directory_path: str,
        protected_prefixes: list[str] | None = None,
        display_name: str | None = None,
    ) -> DirectorySelectionResult:
        """Validate and register a directory for indexing.

        Raises:
            ValidationError: If the path is invalid.
            SecurityError: If the path is protected.
        """
        resolved = validate_directory_path(
            directory_path,
            require_writable=False,
            protected_prefixes=protected_prefixes,
        )
        requires_confirmation = is_system_wide_scan(resolved)
        directory_id = self._storage.upsert_directory(
            resolved, display_name=display_name
        )
        return DirectorySelectionResult(
            directory_id=directory_id,
            directory_path=str(resolved),
            is_default=False,
            requires_system_wide_confirmation=requires_confirmation,
        )

    def get_resume_prompt(self, directory_path: str) -> ResumePrompt | None:
        """Return resume information for *directory_path* if one exists."""
        resolved = validate_directory_path(
            directory_path, require_writable=False
        )
        directory = self._storage.get_directory_by_path(resolved)
        if directory is None:
            return None
        run = self._storage.get_resumable_run(directory["directory_id"])
        if run is None:
            return None
        return ResumePrompt(
            run_id=run["run_id"],
            directory_path=run["targeted_directory"],
            files_processed=run["files_processed"],
            last_processed_path=run.get("last_processed_path"),
        )


class Crawler:
    """Filesystem crawler producing supported files under a root."""

    def crawl(self, root: Path) -> list[Path]:
        """Return all supported files under *root*, sorted."""
        files: list[Path] = []
        try:
            for path in root.rglob("*"):
                if path.is_file() and is_supported(path):
                    files.append(path)
        except OSError as exc:
            logger.warning("Crawl error for %s: %s", root, exc)
        files.sort()
        return files


class IndexingService:
    """Orchestrate incremental indexing runs."""

    def __init__(
        self,
        storage: Storage,
        embedder: Embedder | None = None,
        telemetry: TelemetryQueue | None = None,
        executor_class: type[Executor] | None = None,
        parse_workers: int | None = None,
    ) -> None:
        self._storage = storage
        self._embedder = embedder or create_embedder()
        self._telemetry = telemetry or TelemetryQueue()
        # ThreadPoolExecutor is the default because parsing is I/O-bound and
        # process-pool serialization adds overhead while saturating CPU.  Tests
        # and benchmarks may still opt into ProcessPoolExecutor.
        self._executor_class = executor_class or ThreadPoolExecutor
        self._parse_workers = parse_workers or INDEXING_PARSE_WORKERS
        self._cancel_events: dict[str, threading.Event] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start_indexing(
        self,
        request: StartIndexingRequest,
        resume_run_id: str | None = None,
        on_started: Callable[[str], None] | None = None,
    ) -> IndexingRunSummary:
        """Start or resume an indexing run for *request.directory_path*.

        If *resume_run_id* is provided, the existing run record is reused and
        processing resumes from the last checkpointed file. This lets indexing
        survive sleep, shutdown, or crashes.

        This method is synchronous; callers that need a responsive UI should
        invoke it from a background thread.
        """
        resolved = validate_directory_path(request.directory_path)
        if is_system_wide_scan(resolved) and not request.confirm_system_wide_scan:
            raise ValidationError(
                "System-wide scan requires explicit confirmation",
                "confirm_system_wide_scan",
            )

        active = self._storage.get_active_run()
        if active is not None and (
            resume_run_id is None or active["run_id"] != resume_run_id
        ):
            raise ConflictError("An indexing run is already in progress")

        index_id = self._storage.initialize_index_record()
        directory_id = self._storage.upsert_directory(resolved)

        if resume_run_id:
            existing = self._storage.get_run(resume_run_id)
            if existing is None:
                raise NotFoundError(f"Resume run not found: {resume_run_id}")
            if existing["directory_id"] != directory_id:
                raise ValidationError(
                    "Resume run does not match selected directory"
                )
            run_id = resume_run_id
            self._storage.update_run_status(run_id, "RUNNING")
        else:
            run_id = self._storage.create_indexing_run(
                index_id, directory_id, str(resolved)
            )
            self._storage.update_run_status(run_id, "RUNNING")

        cancel_event = threading.Event()
        stop_event = threading.Event()
        with self._lock:
            self._cancel_events[run_id] = cancel_event
            self._stop_events[run_id] = stop_event

        self._emit(
            run_id,
            "started",
            {"run_id": run_id, "directory_path": str(resolved)},
        )
        if on_started is not None:
            on_started(run_id)

        try:
            self._execute_run(
                run_id, directory_id, resolved, cancel_event, stop_event
            )
        except Exception as exc:  # noqa: BLE001 - run boundary
            logger.exception("Indexing run %s failed", run_id)
            self._storage.update_run_status(
                run_id, "FAILED", error_log=str(exc)
            )
            self._emit(run_id, "failed", {"error": str(exc)})
        finally:
            with self._lock:
                self._cancel_events.pop(run_id, None)
                self._stop_events.pop(run_id, None)

        run = self._storage.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Run {run_id} disappeared")
        return _run_summary(run)

    def get_run(self, run_id: str) -> IndexingRunSummary:
        """Return the summary for an indexing run."""
        run = self._storage.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Indexing run not found: {run_id}")
        return _run_summary(run)

    def cancel_run(self, run_id: str) -> IndexingRunSummary:
        """Request cancellation of a running or planned run."""
        run = self._storage.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Indexing run not found: {run_id}")
        if run["status"] not in ("PLANNED", "RUNNING"):
            raise ConflictError(
                f"Cannot cancel run in status {run['status']}"
            )
        with self._lock:
            event = self._cancel_events.get(run_id)
            if event:
                event.set()
        self._storage.update_run_status(run_id, "CANCELLED")
        run = self._storage.get_run(run_id)
        return _run_summary(run)

    def request_stop(self, run_id: str) -> None:
        """Request that a running run stop after the current file.

        Unlike cancellation, a stop request lets the file currently being
        ingested finish, then performs final cleanup (HNSW rebuild) so the
        index is immediately searchable.
        """
        run = self._storage.get_run(run_id)
        if run is None:
            raise NotFoundError(f"Indexing run not found: {run_id}")
        if run["status"] != "RUNNING":
            raise ConflictError(
                f"Cannot stop run in status {run['status']}"
            )
        with self._lock:
            event = self._stop_events.get(run_id)
            if event:
                event.set()

    def _execute_run(
        self,
        run_id: str,
        directory_id: str,
        directory_path: Path,
        cancel_event: threading.Event,
        stop_event: threading.Event,
    ) -> None:
        """Core indexing loop with resume checkpointing and graceful stop."""
        crawler = Crawler()
        files = crawler.crawl(directory_path)
        existing = {
            r.file_path: r
            for r in self._storage.get_documents_by_directory(directory_id)
        }

        run = self._storage.get_run(run_id)
        resume_from = (
            run.get("last_processed_path")
            if run is not None
            else None
        )
        reached_checkpoint = resume_from is None

        processed = 0
        skipped = 0
        errors: list[str] = []
        files_to_process: list[Path] = []
        keep_paths: set[str] = set()
        indexed_descendants = self._storage.get_indexed_descendant_directories(
            directory_path
        )
        descendant_paths = [d["directory_path"] for d in indexed_descendants]

        for file_path in files:
            if cancel_event.is_set():
                self._storage.update_run_status(
                    run_id,
                    "CANCELLED",
                    files_processed=processed,
                    files_skipped=skipped,
                )
                self._emit(run_id, "cancelled", {})
                return

            path_str = str(file_path)
            if self._is_under_any_directory(path_str, descendant_paths):
                # This file is already covered by a child index scope; leave
                # it to that scope so the parent index does not re-embed it.
                continue

            keep_paths.add(path_str)
            stat = file_path.stat()
            mtime = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).replace(tzinfo=None)
            doc = existing.get(path_str)
            if doc and doc.status == "INDEXED" and doc.last_modified == mtime:
                skipped += 1
                continue

            # When resuming, skip files already completed before the checkpoint.
            if not reached_checkpoint:
                if path_str == resume_from:
                    reached_checkpoint = True
                continue

            files_to_process.append(file_path)

        # Parse files concurrently, but keep the worker pool small so the OS
        # still has CPU available for the user's other desktop applications.
        # as_completed lets us ingest/embed each file as soon as it is parsed,
        # which pipelines work and improves perceived responsiveness.
        max_workers = (
            1
            if self._executor_class is ThreadPoolExecutor
            else MAX_WORKER_PROCESSES
        )
        if self._executor_class is ThreadPoolExecutor:
            max_workers = self._parse_workers

        total_to_process = len(files_to_process)
        stopped = False
        with self._executor_class(max_workers=max_workers) as pool:
            futures = {
                pool.submit(parse_single_file, str(fp)): fp
                for fp in files_to_process
            }
            for future in as_completed(futures):
                if cancel_event.is_set():
                    self._storage.update_run_status(
                        run_id,
                        "CANCELLED",
                        files_processed=processed,
                        files_skipped=skipped,
                    )
                    self._emit(run_id, "cancelled", {})
                    return

                result: WorkerResult = future.result()
                if result.error:
                    errors.append(f"{result.file_path}: {result.error}")
                    skipped += 1
                    continue
                fp = futures[future]
                stats = self._ingest_file(
                    directory_id,
                    fp,
                    result.file_format,
                    result.chunks,
                )
                processed += 1
                path_str = str(fp)
                self._storage.update_run_status(
                    run_id,
                    "RUNNING",
                    files_processed=processed,
                    files_skipped=skipped,
                    last_processed_path=path_str,
                )
                self._emit(
                    run_id,
                    "progress",
                    {
                        "files_processed": processed,
                        "files_skipped": skipped,
                        "total_files": total_to_process,
                        "percent_complete": (
                            int(100 * processed / total_to_process)
                            if total_to_process
                            else 100
                        ),
                        "current_file": path_str,
                        **stats,
                    },
                )

                # Stop after the file that has just been ingested.
                if stop_event.is_set():
                    stopped = True
                    break

                # Yield to the OS scheduler periodically so foreground apps
                # (Excel, Word, browsers) remain responsive during embedding.
                if processed % INDEXING_YIELD_EVERY_N_FILES == 0:
                    time.sleep(0)

        # Mark missing files as removed.
        self._storage.mark_documents_removed(directory_id, keep_paths)

        # Rebuild vector index and update metadata.
        self._storage.rebuild_hnsw_index()
        self._storage.update_last_sync(self._storage.get_index()["index_id"])
        self._storage.set_index_active(self._storage.get_index()["index_id"])

        error_log = "\n".join(errors) if errors else None
        final_status = "COMPLETED" if not stopped else "CANCELLED"
        self._storage.update_run_status(
            run_id,
            final_status,
            files_processed=processed,
            files_skipped=skipped,
            error_log=error_log,
        )
        self._emit(
            run_id,
            "completed" if not stopped else "stopped",
            {"stopped": stopped},
        )

    @staticmethod
    def _is_under_any_directory(
        path_str: str, directory_paths: list[str]
    ) -> bool:
        """Return True when *path_str* is inside any of *directory_paths*."""
        path = Path(path_str)
        for directory_path in directory_paths:
            try:
                path.relative_to(Path(directory_path))
                return True
            except ValueError:
                continue
        return False

    def _ingest_file(
        self,
        directory_id: str,
        file_path: Path,
        file_format: str,
        chunks: list[str],
    ) -> dict[str, Any]:
        """Embed chunks and persist them for a single file.

        Returns runtime statistics about this ingestion step so the UI can
        display live progress information.
        """
        index_id = self._storage.get_index()["index_id"]
        stat = file_path.stat()
        mtime = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).replace(tzinfo=None)
        file_id = self._storage.upsert_document(
            index_id=index_id,
            directory_id=directory_id,
            file_path=file_path,
            file_format=file_format,
            file_size_bytes=stat.st_size,
            last_modified=mtime,
            status="REGISTERED",
        )
        self._storage.delete_chunks_for_file(file_id)

        filename_chunks = chunk_text(file_path.name)
        all_texts = chunks + filename_chunks
        if not all_texts:
            self._storage.set_document_indexed(file_id)
            return {
                "chunks_count": 0,
                "embeddings_count": 0,
                "db_path": str(DEFAULT_DB_PATH),
            }

        embeddings = self._embedder.encode(all_texts)
        chunk_rows: list[ChunkRow] = []
        for idx, text in enumerate(chunks):
            chunk_rows.append(
                ChunkRow(
                    chunk_id="",
                    file_id=file_id,
                    chunk_index=idx,
                    is_filename_entry=False,
                    chunk_text=text,
                    embedding=embeddings[idx],
                )
            )
        offset = len(chunks)
        for idx, text in enumerate(filename_chunks):
            chunk_rows.append(
                ChunkRow(
                    chunk_id="",
                    file_id=file_id,
                    chunk_index=offset + idx,
                    is_filename_entry=True,
                    chunk_text=text,
                    embedding=embeddings[offset + idx],
                )
            )
        self._storage.insert_chunks(file_id, chunk_rows)
        self._storage.set_document_indexed(file_id)
        return {
            "chunks_count": len(all_texts),
            "embeddings_count": len(all_texts),
            "db_path": str(DEFAULT_DB_PATH),
        }

    def _emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self._telemetry.emit(
            TelemetryEvent(event_type=event_type, run_id=run_id, payload=payload)
        )


def _run_summary(run: dict[str, Any]) -> IndexingRunSummary:
    return IndexingRunSummary(
        run_id=run["run_id"],
        status=run["status"],
        directory_path=run["targeted_directory"],
        started_at=_iso(run["started_at"]),
        completed_at=_iso(run["completed_at"]),
        files_processed=run["files_processed"],
        files_skipped=run["files_skipped"],
        error_log=run.get("error_log"),
    )
