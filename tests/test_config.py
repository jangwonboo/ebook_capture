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


def test_pdf_phase_runs_even_when_capture_skipped() -> None:
    """Existing PNGs: plan sets skip_capture, but PDF merge must still run."""
    cfg = CaptureConfig(output_mode=OUTPUT_PDF, skip_capture=True)
    assert cfg.run_capture_phase is False
    assert cfg.run_pdf_phase is True


def test_invalid_output_mode_raises() -> None:
    with pytest.raises(ValueError, match="output_mode"):
        normalize_output_mode("pdf_image")


def test_json_file_allows_line_comments(tmp_path: Path) -> None:
    path = tmp_path / "cfg.json"
    path.write_text(
        """
        {
          // book title
          "title": "My Book",
          "base_dir": "E:/ebook",
          "n_pages": 2,
          "capture_mode": "manual",
          "rect": { "left": 1, "top": 2, "width": 100, "height": 200 }
        }
        """,
        encoding="utf-8",
    )
    cfg = CaptureConfig.from_json_file(path)
    assert cfg.title == "My Book"
    assert cfg.rect.width == 100


def test_json_file_allows_block_comments(tmp_path: Path) -> None:
    from core.config import load_json_file

    path = tmp_path / "cfg.json"
    path.write_text(
        '{"title": /* inline */ "T", "base_dir": "E:/x", "n_pages": 1}',
        encoding="utf-8",
    )
    data = load_json_file(path)
    assert data["title"] == "T"


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


def test_pdf_device_preset_and_padding():
    """pdf_device resolves to a device aspect and pads pages with white margins."""
    from core.config import pdf_device_aspect, PDF_DEVICE_PRESETS
    from core.image_pdf import pad_image_to_aspect
    from PIL import Image

    assert pdf_device_aspect("kindle_scribe") == 1860 / 2480
    assert pdf_device_aspect("KINDLE_COLORSOFT ") == 1264 / 1680
    assert pdf_device_aspect("") == 0.0
    assert pdf_device_aspect("nope") == 0.0
    assert set(PDF_DEVICE_PRESETS) == {"kindle_scribe", "kindle_colorsoft"}

    # too-narrow page gets left/right white margins to reach 0.75, no scaling
    narrow = pad_image_to_aspect(Image.new("RGB", (1170, 1741), (0, 0, 0)), 0.75)
    assert abs(narrow.width / narrow.height - 0.75) < 0.002  # integer-rounded
    assert narrow.height == 1741 and narrow.width > 1170
    # aspect 0 leaves the image untouched
    same = Image.new("RGB", (100, 200))
    assert pad_image_to_aspect(same, 0.0) is same


def test_pdf_device_validation():
    base = dict(
        capture_mode="manual",
        rect={"left": 0, "top": 0, "width": 10, "height": 10},
        base_dir="D:/x",
        output_mode="images",
    )
    from core.config import CaptureConfig

    CaptureConfig.from_mapping({**base, "pdf_device": "kindle_scribe"}).validate()
    CaptureConfig.from_mapping({**base, "pdf_device": ""}).validate()
    try:
        CaptureConfig.from_mapping({**base, "pdf_device": "bogus"}).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("bogus pdf_device should fail validation")
