# Multi-format document parser and text normaliser.
"""Multi-format document parser and text normaliser."""

from __future__ import annotations

import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported extensions mapped to canonical format codes.
_EXTENSION_FORMATS: dict[str, str] = {
    ".pdf": "PDF",
    ".doc": "DOC",
    ".docx": "DOCX",
    ".txt": "TXT",
    ".md": "MD",
    ".xls": "XLS",
    ".xlsx": "XLSX",
    ".csv": "CSV",
    ".ppt": "PPT",
    ".pptx": "PPTX",
    ".odt": "ODF",
    ".ods": "ODF",
    ".odp": "ODF",
}

_CHAPTER_RE = re.compile(r"\n\s*\n")
_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class ParsedDocument:
    """Result of parsing a single file."""

    file_path: Path
    file_format: str
    text: str
    chunks: list[str]


class ParseError(Exception):
    """Raised when a file cannot be parsed."""


def normalise_text(text: str) -> str:
    """Collapse whitespace and strip control characters from *text*."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def chunk_text(text: str, chunk_size: int = 200, overlap: int = 40) -> list[str]:
    """Split *text* into overlapping word windows."""
    words = _WORD_RE.findall(text)
    if not words:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
        start += chunk_size - overlap
    return chunks


def format_for_path(file_path: Path) -> str | None:
    """Return the canonical format code for *file_path*, or None."""
    return _EXTENSION_FORMATS.get(file_path.suffix.lower())


def is_supported(file_path: Path) -> bool:
    """Return True when *file_path* has a supported extension."""
    return format_for_path(file_path) is not None


def parse_file(file_path: Path) -> ParsedDocument:
    """Parse *file_path* and return normalised text and chunks.

    Raises:
        ParseError: If the format is unsupported or extraction fails.
    """
    fmt = format_for_path(file_path)
    if fmt is None:
        raise ParseError(f"Unsupported file extension: {file_path.suffix}")

    raw_text = _extract_text(file_path, fmt)
    normalised = normalise_text(raw_text)
    if not normalised:
        # Empty files produce a single placeholder chunk so they are still
        # represented in the index.
        normalised = ""
        chunks: list[str] = []
    else:
        chunks = chunk_text(normalised)

    return ParsedDocument(
        file_path=file_path,
        file_format=fmt,
        text=normalised,
        chunks=chunks,
    )


def _extract_text(file_path: Path, fmt: str) -> str:
    """Dispatch to format-specific extractors."""
    try:
        if fmt == "TXT" or fmt == "MD" or fmt == "CSV":
            return file_path.read_text(encoding="utf-8", errors="ignore")
        if fmt == "PDF":
            return _extract_pdf(file_path)
        if fmt == "DOCX":
            return _extract_docx(file_path)
        if fmt == "XLSX":
            return _extract_xlsx(file_path)
        if fmt == "XLS":
            return _extract_xls(file_path)
        if fmt == "PPTX":
            return _extract_pptx(file_path)
        if fmt == "ODF":
            return _extract_odf(file_path)
        if fmt == "DOC":
            return _extract_doc(file_path)
        if fmt == "PPT":
            raise ParseError("Legacy PPT format is not supported")
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Failed to extract text from {file_path}: {exc}") from exc

    raise ParseError(f"No extractor implemented for format {fmt}")


def _extract_pdf(file_path: Path) -> str:
    import pymupdf as fitz  # type: ignore[import-untyped]

    doc = fitz.open(str(file_path))
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text())
    return "\n".join(parts)


def _extract_docx(file_path: Path) -> str:
    from docx import Document  # type: ignore[import-untyped]

    doc = Document(str(file_path))
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_xlsx(file_path: Path) -> str:
    import openpyxl  # type: ignore[import-untyped]

    wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            parts.append(
                " ".join(str(cell) for cell in row if cell is not None)
            )
    return "\n".join(parts)


def _extract_xls(file_path: Path) -> str:
    import pandas as pd

    try:
        df = pd.read_excel(str(file_path), engine="xlrd")
    except Exception as exc:
        raise ParseError(f"Cannot read XLS file: {exc}") from exc
    return "\n".join(" ".join(str(v) for v in row) for row in df.values)


def _extract_pptx(file_path: Path) -> str:
    from pptx import Presentation  # type: ignore[import-untyped]

    prs = Presentation(str(file_path))
    parts: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                parts.append(shape.text)
    return "\n".join(parts)


def _extract_odf(file_path: Path) -> str:
    from odf import opendocument, teletype  # type: ignore[import-untyped]
    from odf.text import P  # type: ignore[import-untyped]

    doc = opendocument.load(str(file_path))
    paragraphs = doc.getElementsByType(P)
    return "\n".join(teletype.extractText(p) for p in paragraphs)


def _extract_doc(file_path: Path) -> str:
    """Extract text from a legacy Word ``.doc`` file.

    On Windows, this uses Microsoft Word COM automation to convert the file
    to ``.docx`` in a temporary directory and then reads the result with
    ``python-docx``. On other platforms, where no reliable lightweight
    extractor is bundled, a :class:`ParseError` is raised.
    """
    if sys.platform != "win32":
        raise ParseError(
            "Legacy DOC format is only supported on Windows with Microsoft Word installed"
        )

    try:
        import win32com.client as win32  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ParseError(
            "Legacy DOC extraction requires pywin32 on Windows"
        ) from exc

    word = None
    try:
        word = win32.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False

        abs_path = file_path.resolve()
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_docx = Path(tmpdir) / f"{abs_path.stem}.docx"
            doc = word.Documents.Open(str(abs_path))
            try:
                doc.SaveAs2(str(temp_docx), FileFormat=16)
            finally:
                doc.Close(SaveChanges=False)
            return _extract_docx(temp_docx)
    except Exception as exc:
        raise ParseError(
            f"Failed to extract text from legacy DOC file: {exc}"
        ) from exc
    finally:
        if word is not None:
            word.Quit()
