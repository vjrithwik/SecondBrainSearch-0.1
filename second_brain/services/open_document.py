# Service for opening documents with the OS default handler, with path validation.
"""OS default-handler invocation with path validation."""

from __future__ import annotations

import os
import platform
import subprocess  # nosec B404 - used only for fixed-argv OS-open commands below
from pathlib import Path

from second_brain.exceptions import ValidationError
from second_brain.security import validate_directory_path


def open_document_with_default_handler(file_path: str) -> None:
    """Open *file_path* with the OS default application.

    Raises:
        ValidationError: If the path does not exist.
        SecurityError: If the path is protected or invalid.
    """
    path = Path(file_path)
    if not path.exists():
        raise ValidationError(f"File does not exist: {file_path}")

    # validate_directory_path checks the parent directory is not protected;
    # the file itself is allowed to be inside an indexed directory.
    validate_directory_path(str(path.parent))

    system = platform.system()
    if system == "Windows":
        os.startfile(str(path))  # nosec B606 - deliberate OS open, no shell
    elif system == "Darwin":
        subprocess.run(["open", str(path)], check=False)  # nosec B603 B607 - fixed argv, no shell, path validated above
    else:
        subprocess.run(["xdg-open", str(path)], check=False)  # nosec B603 B607 - fixed argv, no shell, path validated above
