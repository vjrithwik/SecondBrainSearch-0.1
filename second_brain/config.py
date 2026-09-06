# Application-wide configuration constants.
"""Application-wide configuration constants."""

from pathlib import Path

APP_NAME: str = "SecondBrainSearch"
APP_VERSION: str = "0.1.0"

DEFAULT_DB_FILENAME: str = "brain_index.duckdb"
DEFAULT_DB_PATH: Path = Path.home() / ".second_brain" / DEFAULT_DB_FILENAME

MAX_WORKER_PROCESSES: int = max(1, (__import__("os").cpu_count() or 1) - 1)
CHUNK_BATCH_SIZE: int = 100
EMBEDDING_DIMENSION: int = 384

# Indexing responsiveness tuning.  Parsing is I/O-bound and does not scale
# linearly with cores; keeping the pool small leaves CPU headroom for the
# user's other desktop applications.  The yield interval gives the OS scheduler
# a chance to run foreground apps while embedding is in progress.
INDEXING_PARSE_WORKERS: int = 2
INDEXING_YIELD_EVERY_N_FILES: int = 5
