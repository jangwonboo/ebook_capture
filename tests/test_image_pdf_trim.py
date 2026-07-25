"""PDF image build + ratio-based margin trim."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.config import PdfTrim
from core.image_pdf import build_page_image_pdf, crop_image_by_trim_ratios


def test_crop_image_by_trim_ratios() -> None:
    img = Image.new("RGB", (1000, 2000), color=(10, 20, 30))
    trimmed = crop_image_by_trim_ratios(
        img, PdfTrim(left=0.1, right=0.1, top=0.05, bottom=0.05)
    )
    assert trimmed.size == (800, 1800)


def test_build_page_image_pdf_with_trim(tmp_path: Path) -> None:
    png = tmp_path / "page.png"
    Image.new("RGB", (400, 800), color=(255, 255, 255)).save(png)
    out = tmp_path / "page.pdf"
    build_page_image_pdf(
        png,
        out,
        trim=PdfTrim(left=0.05, right=0.05, top=0.1, bottom=0.1),
    )
    assert out.is_file()
    assert out.stat().st_size > 0


def test_pdf_trim_validate_rejects_too_large() -> None:
    import pytest

    with pytest.raises(ValueError):
        PdfTrim(left=0.6).validate()
    with pytest.raises(ValueError):
        PdfTrim(left=0.5, right=0.5).validate()
