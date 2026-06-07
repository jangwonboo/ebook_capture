"""Read page counts and single-page slices from input PDF files."""

from __future__ import annotations

import io
from pathlib import Path


def _pdf_reader_writer():
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except ImportError as exc:
        raise RuntimeError("PyPDF2 is required for PDF input OCR.") from exc
    return PdfReader, PdfWriter


def pdf_page_count(pdf_path: Path | str) -> int:
    """Return the number of pages in a PDF."""
    path = Path(pdf_path)
    PdfReader, _ = _pdf_reader_writer()
    reader = PdfReader(str(path))
    count = len(reader.pages)
    if count < 1:
        raise ValueError(f"PDF has no pages: {path}")
    return count


def extract_pdf_page_bytes(pdf_path: Path | str, page_index: int) -> bytes:
    """Return a one-page PDF as bytes (page_index is 0-based)."""
    path = Path(pdf_path)
    PdfReader, PdfWriter = _pdf_reader_writer()
    reader = PdfReader(str(path))
    total = len(reader.pages)
    if page_index < 0 or page_index >= total:
        raise ValueError(
            f"PDF page index {page_index} out of range (0..{total - 1}) for {path}"
        )
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
