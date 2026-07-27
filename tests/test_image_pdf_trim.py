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


def test_fill_top_whitens_toolbar_without_shrinking_height() -> None:
    # Dark title (50px) + colored toolbar (100px) + white content.
    img = Image.new("RGB", (200, 1000), color=(255, 255, 255))
    for y in range(0, 50):
        for x in range(200):
            img.putpixel((x, y), (40, 40, 40))
    for y in range(50, 150):
        for x in range(200):
            img.putpixel((x, y), (80, 120, 200))
    # title crop 0.05 (=50px), fill_top 0.10 (=100px) of original height
    out = crop_image_by_trim_ratios(
        img, PdfTrim(top=0.05, fill_top=0.10, bottom=0.0)
    )
    assert out.size == (200, 950)
    # First rows of result are former toolbar — now white
    assert out.getpixel((100, 10)) == (255, 255, 255)
    assert out.getpixel((100, 90)) == (255, 255, 255)
    # Content below fill stays white
    assert out.getpixel((100, 200)) == (255, 255, 255)


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
