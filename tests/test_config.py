"""Tests for CaptureConfig."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from core.config import (
    CaptureConfig,
    OUTPUT_IMAGES,
    OUTPUT_PDF,
    OUTPUT_TEXT,
    normalize_output_mode,
)
from core.pdf_input import pdf_page_count


def test_pdf_page_index_mapping() -> None:
    cfg = CaptureConfig(start_page=8, n_pages=3)
    assert cfg.page_numbers() == [8, 9, 10]
    assert cfg.pdf_page_index(8) == 7


def test_final_markdown_paths() -> None:
    cfg = CaptureConfig(title="MyBook", base_dir="E:/ebook")
    assert cfg.final_markdown_path() == Path("E:/ebook/MyBook/MyBook.md")


def test_output_mode_phases() -> None:
    images = CaptureConfig(output_mode=OUTPUT_IMAGES)
    assert images.run_capture_phase is True
    assert images.run_ocr_phase is False
    assert images.run_pdf_phase is False

    pdf = CaptureConfig(output_mode=OUTPUT_PDF)
    assert pdf.run_capture_phase is True
    assert pdf.run_ocr_phase is False
    assert pdf.run_pdf_phase is True

    text = CaptureConfig(output_mode=OUTPUT_TEXT)
    assert text.run_capture_phase is True
    assert text.run_ocr_phase is True
    assert text.run_pdf_phase is False


def test_ocr_skip_capture() -> None:
    cfg = CaptureConfig(output_mode=OUTPUT_TEXT, skip_capture=True)
    assert cfg.run_capture_phase is False
    assert cfg.run_ocr_phase is True


def test_invalid_output_mode_raises() -> None:
    with pytest.raises(ValueError, match="output_mode"):
        normalize_output_mode("pdf_image")


def test_assemble_style_validation() -> None:
    cfg = CaptureConfig(
        title="t",
        base_dir="E:/out",
        assemble_style="prose",
        capture_mode="window_full",
        target_window_title="Reader",
        skip_capture=True,
    )
    cfg.validate()


def test_input_pdf_validation(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "x")
    c.showPage()
    c.save()

    cfg = CaptureConfig(
        title="t",
        base_dir=str(tmp_path),
        input_pdf=str(pdf),
        output_mode=OUTPUT_TEXT,
        n_pages=pdf_page_count(pdf),
        start_page=1,
    )
    cfg.validate()
    assert cfg.run_capture_phase is False
    assert cfg.run_ocr_phase is True

    cfg.start_page = 99
    with pytest.raises(ValueError, match="exceeds PDF page count"):
        cfg.validate()
