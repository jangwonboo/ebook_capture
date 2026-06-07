"""Tests for core.pdf_input."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.pdf_input import extract_pdf_page_bytes, pdf_page_count


@pytest.fixture
def two_page_pdf(tmp_path: Path) -> Path:
    from reportlab.pdfgen import canvas

    path = tmp_path / "two_pages.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Page one")
    c.showPage()
    c.drawString(72, 720, "Page two")
    c.showPage()
    c.save()
    return path


def test_pdf_page_count(two_page_pdf: Path) -> None:
    assert pdf_page_count(two_page_pdf) == 2


def test_extract_single_page_bytes(two_page_pdf: Path) -> None:
    page0 = extract_pdf_page_bytes(two_page_pdf, 0)
    page1 = extract_pdf_page_bytes(two_page_pdf, 1)
    assert isinstance(page0, bytes) and len(page0) > 100
    assert page0 != page1


def test_extract_page_index_out_of_range(two_page_pdf: Path) -> None:
    with pytest.raises(ValueError, match="out of range"):
        extract_pdf_page_bytes(two_page_pdf, 99)
