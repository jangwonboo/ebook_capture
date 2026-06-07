"""Build image-only PDFs from captured PNG pages."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def _load_reportlab():
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("reportlab is required to build PDFs.") from exc
    return canvas, ImageReader


def _safe_dpi(value: object) -> float:
    try:
        dpi = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 72.0
    if dpi <= 1.0:
        return 72.0
    return dpi


def _pdf_page_geometry(image_path: Path) -> tuple[float, float]:
    with Image.open(image_path) as img:
        width_px, height_px = img.size
        dpi_meta = img.info.get("dpi", (72.0, 72.0))
    if isinstance(dpi_meta, tuple):
        dpi_x = _safe_dpi(dpi_meta[0] if len(dpi_meta) > 0 else 72.0)
        dpi_y = _safe_dpi(dpi_meta[1] if len(dpi_meta) > 1 else dpi_x)
    else:
        dpi_x = dpi_y = _safe_dpi(dpi_meta)
    width_pt = float(width_px) * 72.0 / dpi_x
    height_pt = float(height_px) * 72.0 / dpi_y
    return width_pt, height_pt


def build_page_image_pdf(
    image_path: Path | str,
    output_pdf_path: Path | str,
) -> Path:
    """Create one plain PDF page with the captured image as the full page."""
    canvas_mod, ImageReader = _load_reportlab()
    image = Path(image_path)
    output = Path(output_pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    width, height = _pdf_page_geometry(image)

    c = canvas_mod.Canvas(str(output), pagesize=(width, height))
    c.drawImage(ImageReader(str(image)), 0, 0, width=width, height=height)
    c.showPage()
    c.save()
    return output


def merge_pdfs(pdf_paths: list[Path], output_pdf_path: Path | str) -> Path:
    try:
        from PyPDF2 import PdfMerger
    except ImportError:
        from PyPDF2 import PdfFileMerger as PdfMerger  # type: ignore

    output = Path(output_pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    merger = PdfMerger()
    try:
        for path in pdf_paths:
            merger.append(str(path))
        with open(output, "wb") as fh:
            merger.write(fh)
    finally:
        merger.close()
    return output
