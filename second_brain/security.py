# Path validation and sanitisation middleware.
"""Path validation and sanitisation middleware."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from second_brain.exceptions import SecurityError, ValidationError

# Fallback protected paths used before the database is available.
# The canonical list lives in the protected_system_paths reference table.
_FALLBACK_PROTECTED_PREFIXES: tuple[str, ...] = (
    "/System",
    "/usr",
    "/bin",
    "/boot",
    "/etc",
    "/lib",
    "/proc",
    "/sys",
    r"C:\Windows",
    r"C:\Program Files",
)


def _normalise(path: str) -> Path:
    """Return an absolute, resolved Path for *path* if it exists."""
    p = Path(path)
    if not p.exists():
        raise ValidationError(f"Path does not exist: {path}")
    return p.resolve()


def _has_traversal(path: Path) -> bool:
    """Detect path-traversal attempts outside the resolved absolute path."""
    try:
        parts = path.resolve().parts
    except OSError:
        return True
    return any(part == ".." for part in parts)


def _is_protected(path: Path, extra_prefixes: Iterable[str] | None = None) -> bool:
    """Return True when *path* is at or under a protected system prefix."""
    prefixes = list(_FALLBACK_PROTECTED_PREFIXES)
    if extra_prefixes:
        prefixes.extend(extra_prefixes)
    path_str = str(path)
    # On Windows, compare case-insensitively and with both separators.
    lowered = path_str.lower().replace("/", "\\")
    for prefix in prefixes:
        normalised_prefix = prefix.lower().replace("/", "\\")
        if lowered == normalised_prefix or lowered.startswith(normalised_prefix + "\\"):
            return True
    return False


def validate_directory_path(
    path: str,
    require_writable: bool = False,
    protected_prefixes: Iterable[str] | None = None,
) -> Path:
    """Validate and return a sanitised directory path.

    Args:
        path: User-provided directory path.
        require_writable: If True, ensure the directory is writable.
        protected_prefixes: Additional protected-path prefixes to enforce.

    Returns:
        Resolved absolute Path.

    Raises:
        ValidationError: If the path is missing, not a directory, or contains
            traversal sequences.
        SecurityError: If the path is protected or not writable when required.
    """
    if not path or not path.strip():
        raise ValidationError("Directory path is required.")

    if _is_protected(Path(path), protected_prefixes):
        raise SecurityError(f"Directory is protected and cannot be indexed: {path}")
    resolved = _normalise(path)
    if _has_traversal(Path(path)):
        raise SecurityError("Path contains traversal sequences.")
    if not resolved.is_dir():
        raise ValidationError(f"Path is not a directory: {path}")
    if require_writable and not _is_writable(resolved):
        raise SecurityError(f"Directory is not writable: {path}")
    return resolved


def _is_writable(directory: Path) -> bool:
    """Best-effort writable check without mutating the target directory."""
    try:
        test_file = directory / ".sbs_write_test"
        test_file.write_text("")
        test_file.unlink()
        return True
    except OSError:
        return False


def is_system_wide_scan(path: Path) -> bool:
    """Return True when *path* is a root or near-root directory.

    A system-wide scan confirmation is required for these directories.
    """
    try:
        resolved = path.resolve()
    except OSError:
        return True
    parts = resolved.parts
    return len(parts) <= 1 or (
        len(parts) == 2 and parts[0] in ("/", "C:\\")
    )
