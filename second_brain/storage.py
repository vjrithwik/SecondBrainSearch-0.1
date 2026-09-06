# DuckDB storage abstraction, migration runner, and schema helpers.
"""DuckDB storage abstraction, migration runner, and schema helpers."""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from second_brain.config import (
    CHUNK_BATCH_SIZE,
    DEFAULT_DB_FILENAME,
    EMBEDDING_DIMENSION,
)
from second_brain.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

_MIGRATION_DIR = Path(__file__).parent / "migrations"
_MIGRATION_PATTERN = re.compile(r"^(\d{3})_.*\.sql$")


@dataclass(frozen=True)
class DocumentRow:
    """Projection of a documents row used by services."""

    file_id: str
    index_id: str
    directory_id: str
    file_path: str
    file_name: str
    file_format: str
    file_size_bytes: int
    last_modified: datetime
    status: str
    indexed_at: datetime | None


@dataclass(frozen=True)
class ChunkRow:
    """Projection of a document_chunks row used by services."""

    chunk_id: str
    file_id: str
    chunk_index: int
    is_filename_entry: bool
    chunk_text: str
    embedding: list[float]


class Storage:
    """Local DuckDB storage with deterministic schema migrations."""

    def __init__(self, db_path: Path | None = None) -> None:
        """Open or create the DuckDB file at *db_path*."""
        self._db_path = db_path or Path.home() / ".second_brain" / DEFAULT_DB_FILENAME
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._ensure_vss()

    def _ensure_vss(self) -> None:
        """Load the vss extension if available; log and continue if offline."""
        try:
            self._conn.execute("INSTALL vss")
            self._conn.execute("LOAD vss")
        except Exception:  # pragma: no cover - environment dependent
            logger.warning("vss extension not available; HNSW index will be skipped")

    @property
    def db_path(self) -> Path:
        return self._db_path

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()

    def ensure_schema(self) -> None:
        """Run pending migrations in numeric order."""
        # Bootstrap the version-tracking table before any migration check.
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "    version INTEGER PRIMARY KEY,"
            "    applied_at TIMESTAMP NOT NULL DEFAULT NOW()"
            ")"
        )
        migrations = sorted(
            _MIGRATION_DIR.glob("*.sql"),
            key=lambda p: int(_MIGRATION_PATTERN.match(p.name).group(1)),  # type: ignore[union-attr]
        )
        for migration in migrations:
            version = int(_MIGRATION_PATTERN.match(migration.name).group(1))  # type: ignore[union-attr]
            already_applied = self._conn.execute(
                "SELECT 1 FROM schema_version WHERE version = ?", [version]
            ).fetchone()
            if already_applied:
                continue
            logger.info("Applying migration %s", migration.name)
            sql = migration.read_text(encoding="utf-8")
            self._conn.execute(sql)
            self._conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", [version]
            )

    def initialize_index_record(self) -> str:
        """Ensure the singleton indexes row exists; return its id."""
        existing = self._conn.execute(
            "SELECT index_id FROM indexes WHERE storage_path = ?",
            [str(self._db_path)],
        ).fetchone()
        if existing:
            return existing[0]
        self._conn.execute(
            "INSERT INTO indexes (storage_path) VALUES (?)",
            [str(self._db_path)],
        )
        row = self._conn.execute(
            "SELECT index_id FROM indexes WHERE storage_path = ?",
            [str(self._db_path)],
        ).fetchone()
        return row[0]

    def get_index(self) -> dict[str, Any]:
        """Return the singleton index row as a dict."""
        row = self._conn.execute(
            "SELECT * FROM indexes WHERE storage_path = ?",
            [str(self._db_path)],
        ).fetchone()
        if row is None:
            raise NotFoundError("Index record not found")
        cols = [desc[0] for desc in self._conn.description]
        return dict(zip(cols, row, strict=False))

    def upsert_directory(
        self,
        directory_path: Path,
        is_default: bool = False,
        display_name: str | None = None,
    ) -> str:
        """Insert or update a directory record; return directory_id."""
        path_str = str(directory_path)
        existing = self._conn.execute(
            "SELECT directory_id FROM directories WHERE directory_path = ?",
            [path_str],
        ).fetchone()
        if existing:
            directory_id = existing[0]
            updates = ["is_default = ?", "updated_at = NOW()"]
            params: list[Any] = [is_default]
            if display_name is not None:
                updates.append("display_name = ?")
                params.append(display_name)
            params.append(directory_id)
            self._conn.execute(
                f"UPDATE directories SET {', '.join(updates)} WHERE directory_id = ?",  # nosec B608 - fixed column-name literals
                params,
            )
            return directory_id
        columns = ["directory_path", "is_default"]
        values: list[Any] = [path_str, is_default]
        if display_name is not None:
            columns.append("display_name")
            values.append(display_name)
        self._conn.execute(
            f"INSERT INTO directories ({', '.join(columns)}) VALUES ({', '.join(['?'] * len(values))})",  # nosec B608 - fixed column-name literals
            values,
        )
        row = self._conn.execute(
            "SELECT directory_id FROM directories WHERE directory_path = ?",
            [path_str],
        ).fetchone()
        return row[0]

    def set_directory_display_name(
        self, directory_id: str, display_name: str
    ) -> None:
        """Set the user-defined display name for a directory."""
        self._conn.execute(
            "UPDATE directories SET display_name = ?, updated_at = NOW() "
            "WHERE directory_id = ?",
            [display_name, directory_id],
        )

    def get_directory_by_path(self, directory_path: Path) -> dict[str, Any] | None:
        """Return directory row by path, or None."""
        row = self._conn.execute(
            "SELECT * FROM directories WHERE directory_path = ?",
            [str(directory_path)],
        ).fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._conn.description]
        return dict(zip(cols, row, strict=False))

    def get_directories(self) -> list[dict[str, Any]]:
        """Return all registered directories."""
        rows = self._conn.execute("SELECT * FROM directories").fetchall()
        cols = [desc[0] for desc in self._conn.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    def delete_directory(self, directory_id: str) -> None:
        """Delete a directory and all associated documents, chunks, and runs."""
        self._conn.execute(
            "DELETE FROM document_chunks WHERE file_id IN "
            "(SELECT file_id FROM documents WHERE directory_id = ?)",
            [directory_id],
        )
        self._conn.execute(
            "DELETE FROM documents WHERE directory_id = ?",
            [directory_id],
        )
        self._conn.execute(
            "DELETE FROM indexing_runs WHERE directory_id = ?",
            [directory_id],
        )
        self._conn.execute(
            "DELETE FROM directories WHERE directory_id = ?",
            [directory_id],
        )

    def get_indexed_directories(self) -> list[dict[str, Any]]:
        """Return directories that have indexed documents, with counts.

        The document count is recursive: it includes every indexed file whose
        path starts with the directory path, including files that belong to
        descendant directory scopes. This makes the count match what search
        will actually return for that scope.
        """
        rows = self._conn.execute(
            "SELECT d.directory_id, d.directory_path, d.display_name, "
            "COUNT(doc.file_id) AS document_count "
            "FROM directories d "
            "JOIN documents doc ON doc.file_path ILIKE d.directory_path || '\\%' "
            "AND doc.status IN ('INDEXED', 'STALE') "
            "GROUP BY d.directory_id, d.directory_path, d.display_name "
            "HAVING COUNT(doc.file_id) > 0 "
            "ORDER BY d.directory_path"
        ).fetchall()
        return [
            {
                "directory_id": r[0],
                "directory_path": r[1],
                "display_name": r[2],
                "document_count": r[3],
            }
            for r in rows
        ]

    def get_indexed_descendant_directories(
        self, directory_path: Path
    ) -> list[dict[str, Any]]:
        """Return indexed directories that are strict descendants of *directory_path*."""
        path_str = str(directory_path)
        rows = self._conn.execute(
            "SELECT d.directory_id, d.directory_path "
            "FROM directories d "
            "WHERE d.directory_path ILIKE ? || '\\%' "
            "AND d.directory_path != ? "
            "AND EXISTS ("
            "    SELECT 1 FROM documents doc "
            "    WHERE doc.directory_id = d.directory_id "
            "    AND doc.status IN ('INDEXED', 'STALE')"
            ")",
            [path_str, path_str],
        ).fetchall()
        cols = [desc[0] for desc in self._conn.description]
        return [dict(zip(cols, row, strict=False)) for row in rows]

    def upsert_document(
        self,
        index_id: str,
        directory_id: str,
        file_path: Path,
        file_format: str,
        file_size_bytes: int,
        last_modified: datetime,
        status: str = "REGISTERED",
    ) -> str:
        """Insert or update a document record; return file_id."""
        path_str = str(file_path)
        name = file_path.name
        existing = self._conn.execute(
            "SELECT file_id FROM documents WHERE index_id = ? AND file_path = ?",
            [index_id, path_str],
        ).fetchone()
        if existing:
            file_id = existing[0]
            self._conn.execute(
                "UPDATE documents SET directory_id = ?, file_name = ?, "
                "file_format = ?, file_size_bytes = ?, last_modified = ?, "
                "status = ?, updated_at = NOW() WHERE file_id = ?",
                [
                    directory_id,
                    name,
                    file_format,
                    file_size_bytes,
                    last_modified,
                    status,
                    file_id,
                ],
            )
            return file_id
        self._conn.execute(
            "INSERT INTO documents (index_id, directory_id, file_path, file_name, "
            "file_format, file_size_bytes, last_modified, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                index_id,
                directory_id,
                path_str,
                name,
                file_format,
                file_size_bytes,
                last_modified,
                status,
            ],
        )
        row = self._conn.execute(
            "SELECT file_id FROM documents WHERE index_id = ? AND file_path = ?",
            [index_id, path_str],
        ).fetchone()
        return row[0]

    def get_documents_by_directory(self, directory_id: str) -> list[DocumentRow]:
        """Return all documents under *directory_id*."""
        rows = self._conn.execute(
            "SELECT file_id, index_id, directory_id, file_path, file_name, "
            "file_format, file_size_bytes, last_modified, status, indexed_at "
            "FROM documents WHERE directory_id = ?",
            [directory_id],
        ).fetchall()
        return [
            DocumentRow(
                file_id=r[0],
                index_id=r[1],
                directory_id=r[2],
                file_path=r[3],
                file_name=r[4],
                file_format=r[5],
                file_size_bytes=r[6],
                last_modified=r[7],
                status=r[8],
                indexed_at=r[9],
            )
            for r in rows
        ]

    def get_document_by_path(self, index_id: str, file_path: Path) -> DocumentRow | None:
        """Return a document by index and path, or None."""
        row = self._conn.execute(
            "SELECT file_id, index_id, directory_id, file_path, file_name, "
            "file_format, file_size_bytes, last_modified, status, indexed_at "
            "FROM documents WHERE index_id = ? AND file_path = ?",
            [index_id, str(file_path)],
        ).fetchone()
        if row is None:
            return None
        return DocumentRow(
            file_id=row[0],
            index_id=row[1],
            directory_id=row[2],
            file_path=row[3],
            file_name=row[4],
            file_format=row[5],
            file_size_bytes=row[6],
            last_modified=row[7],
            status=row[8],
            indexed_at=row[9],
        )

    def mark_documents_removed(self, directory_id: str, keep_paths: set[str]) -> int:
        """Mark documents in *directory_id* as REMOVED unless path is in *keep_paths*."""
        if keep_paths:
            self._conn.execute(
                "UPDATE documents SET status = 'REMOVED', updated_at = NOW() "
                "WHERE directory_id = ? AND file_path NOT IN (SELECT unnest(?)) "
                "AND status != 'REMOVED'",
                [directory_id, list(keep_paths)],
            )
        else:
            self._conn.execute(
                "UPDATE documents SET status = 'REMOVED', updated_at = NOW() "
                "WHERE directory_id = ? AND status != 'REMOVED'",
                [directory_id],
            )
        count_row = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE directory_id = ? AND status = 'REMOVED'",
            [directory_id],
        ).fetchone()
        return count_row[0]

    def delete_chunks_for_file(self, file_id: str) -> None:
        """Remove all chunks for a document."""
        self._conn.execute(
            "DELETE FROM document_chunks WHERE file_id = ?", [file_id]
        )

    def insert_chunks(self, file_id: str, chunks: list[ChunkRow]) -> None:
        """Persist chunks in batches of CHUNK_BATCH_SIZE."""
        if not chunks:
            return
        for i in range(0, len(chunks), CHUNK_BATCH_SIZE):
            batch = chunks[i : i + CHUNK_BATCH_SIZE]
            self._conn.executemany(
                "INSERT INTO document_chunks (file_id, chunk_index, "
                "is_filename_entry, chunk_text, embedding) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        file_id,
                        chunk.chunk_index,
                        chunk.is_filename_entry,
                        chunk.chunk_text,
                        chunk.embedding,
                    )
                    for chunk in batch
                ],
            )

    def set_document_indexed(self, file_id: str) -> None:
        """Mark a document as INDEXED and set indexed_at."""
        self._conn.execute(
            "UPDATE documents SET status = 'INDEXED', indexed_at = NOW(), "
            "updated_at = NOW() WHERE file_id = ?",
            [file_id],
        )

    def set_index_active(self, index_id: str) -> None:
        """Mark the index as ACTIVE."""
        self._conn.execute(
            "UPDATE indexes SET status = 'ACTIVE', updated_at = NOW() "
            "WHERE index_id = ?",
            [index_id],
        )

    def update_last_sync(self, index_id: str) -> None:
        """Update indexes.last_sync_at to now."""
        self._conn.execute(
            "UPDATE indexes SET last_sync_at = NOW(), updated_at = NOW() "
            "WHERE index_id = ?",
            [index_id],
        )

    def _maybe_enable_hnsw_persistence(self) -> None:
        """Enable HNSW persistence on file-backed databases if vss is loaded."""
        try:
            self._conn.execute("LOAD vss")
            if str(self._db_path) != ":memory:":
                self._conn.execute("SET hnsw_enable_experimental_persistence = true")
        except Exception:  # pragma: no cover - environment dependent
            pass

    def create_hnsw_index(self) -> None:
        """Create the HNSW index on document_chunks.embedding if vss is loaded."""
        try:
            self._maybe_enable_hnsw_persistence()
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS chunk_vec_idx ON document_chunks "
                "USING HNSW (embedding)"
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Could not create HNSW index: %s", exc)

    def rebuild_hnsw_index(self) -> None:
        """Drop and recreate the HNSW index after bulk ingestion."""
        try:
            self._maybe_enable_hnsw_persistence()
            self._conn.execute("DROP INDEX IF EXISTS chunk_vec_idx")
            self._conn.execute(
                "CREATE INDEX chunk_vec_idx ON document_chunks USING HNSW (embedding)"
            )
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.warning("Could not rebuild HNSW index: %s", exc)

    def search_chunks(
        self, embedding: list[float], top_k: int = 15
    ) -> list[dict[str, Any]]:
        """Return top-k documents by max cosine similarity across chunks."""
        if len(embedding) != EMBEDDING_DIMENSION:
            raise ValidationError(
                f"Embedding dimension must be {EMBEDDING_DIMENSION}"
            )
        rows = self._conn.execute(
            "SELECT d.file_id, d.file_name, d.file_path, "
            "MAX(array_cosine_similarity(dc.embedding, ?::FLOAT[384])) AS score, "
            "COUNT(*) AS matched_chunk_count "
            "FROM document_chunks dc "
            "JOIN documents d ON d.file_id = dc.file_id "
            "WHERE d.status IN ('INDEXED', 'STALE') "
            "GROUP BY d.file_id, d.file_name, d.file_path "
            "ORDER BY score DESC NULLS LAST "
            "LIMIT ?",
            [embedding, top_k],
        ).fetchall()
        return [
            {
                "file_id": r[0],
                "file_name": r[1],
                "file_path": r[2],
                "score": float(r[3]) if r[3] is not None else 0.0,
                "matched_chunk_count": r[4],
            }
            for r in rows
        ]

    def search_chunks_scoped(
        self, directory_path: str, embedding: list[float], top_k: int = 15
    ) -> list[dict[str, Any]]:
        """Return top-k documents under *directory_path* by cosine similarity."""
        if len(embedding) != EMBEDDING_DIMENSION:
            raise ValidationError(
                f"Embedding dimension must be {EMBEDDING_DIMENSION}"
            )
        pattern = str(directory_path).rstrip("\\/") + "\\%"
        rows = self._conn.execute(
            "SELECT d.file_id, d.file_name, d.file_path, "
            "MAX(array_cosine_similarity(dc.embedding, ?::FLOAT[384])) AS score, "
            "COUNT(*) AS matched_chunk_count "
            "FROM document_chunks dc "
            "JOIN documents d ON d.file_id = dc.file_id "
            "WHERE d.status IN ('INDEXED', 'STALE') "
            "AND d.file_path ILIKE ? "
            "GROUP BY d.file_id, d.file_name, d.file_path "
            "ORDER BY score DESC NULLS LAST "
            "LIMIT ?",
            [embedding, pattern, top_k],
        ).fetchall()
        return [
            {
                "file_id": r[0],
                "file_name": r[1],
                "file_path": r[2],
                "score": float(r[3]) if r[3] is not None else 0.0,
                "matched_chunk_count": r[4],
            }
            for r in rows
        ]

    def create_indexing_run(
        self, index_id: str, directory_id: str, targeted_directory: str
    ) -> str:
        """Create a PLANNED indexing run; return run_id."""
        self._conn.execute(
            "INSERT INTO indexing_runs (index_id, directory_id, targeted_directory) "
            "VALUES (?, ?, ?)",
            [index_id, directory_id, targeted_directory],
        )
        row = self._conn.execute(
            "SELECT run_id FROM indexing_runs WHERE index_id = ? AND directory_id = ? "
            "AND targeted_directory = ? ORDER BY created_at DESC LIMIT 1",
            [index_id, directory_id, targeted_directory],
        ).fetchone()
        return row[0]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Return indexing run row by id, or None."""
        row = self._conn.execute(
            "SELECT * FROM indexing_runs WHERE run_id = ?", [run_id]
        ).fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._conn.description]
        return dict(zip(cols, row, strict=False))

    def get_active_run(self) -> dict[str, Any] | None:
        """Return any RUNNING indexing run, or None."""
        row = self._conn.execute(
            "SELECT * FROM indexing_runs WHERE status = 'RUNNING' LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._conn.description]
        return dict(zip(cols, row, strict=False))

    def update_run_status(
        self,
        run_id: str,
        status: str,
        files_processed: int | None = None,
        files_skipped: int | None = None,
        error_log: str | None = None,
        last_processed_path: str | None = None,
    ) -> None:
        """Update run status and optional counters."""
        sets = ["status = ?", "updated_at = NOW()"]
        params: list[Any] = [status]
        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            sets.append("completed_at = NOW()")
        if files_processed is not None:
            sets.append("files_processed = ?")
            params.append(files_processed)
        if files_skipped is not None:
            sets.append("files_skipped = ?")
            params.append(files_skipped)
        if error_log is not None:
            sets.append("error_log = ?")
            params.append(error_log)
        if last_processed_path is not None:
            sets.append("last_processed_path = ?")
            sets.append("checkpointed_at = NOW()")
            params.append(last_processed_path)
        params.append(run_id)
        self._conn.execute(
            f"UPDATE indexing_runs SET {', '.join(sets)} WHERE run_id = ?",  # nosec B608 - sets built from fixed column-name literals only
            params,
        )

    def get_resumable_run(self, directory_id: str) -> dict[str, Any] | None:
        """Return the most recent non-terminal run for *directory_id*, or None."""
        row = self._conn.execute(
            "SELECT * FROM indexing_runs "
            "WHERE directory_id = ? AND status IN ('RUNNING', 'PLANNED') "
            "ORDER BY started_at DESC LIMIT 1",
            [directory_id],
        ).fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in self._conn.description]
        return dict(zip(cols, row, strict=False))

    def get_index_status(self) -> dict[str, Any]:
        """Return index status with derived document count.

        If the singleton index record has not been created yet, returns a
        synthetic EMPTY status instead of raising. This avoids noisy warnings
        when consumers check readiness before the controller finishes setup.
        """
        try:
            idx = self.get_index()
        except NotFoundError:
            idx = {}

        required = {"index_id", "status", "storage_path", "last_sync_at"}
        if not required.issubset(idx):
            return {
                "index_id": idx.get("index_id", ""),
                "status": "EMPTY",
                "storage_path": str(self._db_path),
                "last_sync_at": idx.get("last_sync_at"),
                "document_count": 0,
            }

        count_row = self._conn.execute(
            "SELECT COUNT(*) FROM documents WHERE index_id = ? "
            "AND status IN ('INDEXED', 'STALE')",
            [idx["index_id"]],
        ).fetchone()
        return {
            "index_id": idx["index_id"],
            "status": idx["status"],
            "storage_path": idx["storage_path"],
            "last_sync_at": idx["last_sync_at"],
            "document_count": count_row[0],
        }

    def purge(self) -> dict[str, Any]:
        """Drop all tables, delete the DB file, and return purged metadata."""
        idx = self.get_index()
        deleted_at = datetime.now(timezone.utc)
        self._conn.close()
        with contextlib.suppress(FileNotFoundError):
            self._db_path.unlink()
        # Remove parent directory only if empty.
        with contextlib.suppress(OSError):
            self._db_path.parent.rmdir()
        return {
            "purged": True,
            "index_id": idx["index_id"],
            "storage_path": idx["storage_path"],
            "deleted_at": deleted_at,
        }

    def reset_after_purge(self) -> None:
        """Reopen a fresh DB and rerun schema after the file was deleted."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(self._db_path))
        self._ensure_vss()
        self.ensure_schema()

    def startup_permission_check(self) -> None:
        """Verify the DB parent directory is writable; raise otherwise."""
        parent = self._db_path.parent
        parent.mkdir(parents=True, exist_ok=True)
        try:
            test = parent / ".sbs_startup_write_test"
            test.write_text("")
            test.unlink()
        except OSError as exc:
            raise ValidationError(
                f"Cannot write to index directory {parent}: {exc}"
            ) from exc
        free = shutil.disk_usage(parent).free
        min_free = 50 * 1024 * 1024  # 50 MB
        if free < min_free:
            raise ValidationError(
                f"Insufficient disk space on {parent}: {free} bytes free"
            )

    def __enter__(self) -> Storage:
        self.ensure_schema()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
