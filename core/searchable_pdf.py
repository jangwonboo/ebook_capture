"""Build searchable PDFs from page images and OCR layout JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image


def _load_reportlab():
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:  # pragma: no cover - dependency message path
        raise RuntimeError("reportlab is required to build searchable PDFs.") from exc
    return canvas, ImageReader, pdfmetrics, TTFont, UnicodeCIDFont


def _register_search_font() -> str:
    _, _, pdfmetrics, TTFont, UnicodeCIDFont = _load_reportlab()
    font_name = "EbookCaptureOCR"
    if font_name in pdfmetrics.getRegisteredFontNames():
        return font_name

    candidates = [
        Path("C:/Windows/Fonts/malgun.ttf"),
        Path("C:/Windows/Fonts/arialuni.ttf"),
        Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
                return font_name
            except Exception:
                continue

    for cid_font in ("HYSMyeongJo-Medium", "HeiseiKakuGo-W5", "STSong-Light"):
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(cid_font))
            return cid_font
        except Exception:
            continue
    return "Helvetica"


def _safe_text(text: Any) -> str:
    return str(text or "").replace("\x00", "").strip()


def _block_bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    bbox = block.get("bbox")
    if not isinstance(bbox, dict):
        return None
    try:
        x = float(bbox["x"])
        y = float(bbox["y"])
        w = float(bbox["w"])
        h = float(bbox["h"])
    except (KeyError, TypeError, ValueError):
        return None
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    w = max(0.0, min(1.0 - x, w))
    h = max(0.0, min(1.0 - y, h))
    if w <= 0.0 or h <= 0.0:
        return None
    return x, y, w, h


def _font_size_for(text: str, box_w: float, box_h: float) -> float:
    if not text:
        return 1.0
    line_count = max(1, text.count("\n") + 1)
    longest = max(len(line) for line in text.splitlines() or [text])
    by_height = box_h / max(1.0, line_count) * 0.78
    by_width = box_w / max(1.0, longest) * 1.9
    return max(3.0, min(18.0, by_height, by_width))


def _safe_dpi(value: Any) -> float:
    try:
        dpi = float(value)
    except (TypeError, ValueError):
        return 72.0
    if dpi <= 1.0:
        return 72.0
    return dpi


def _pdf_page_geometry(image_path: Path) -> tuple[float, float]:
    """Return PDF page size in points from image pixels + DPI metadata."""
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


def build_page_searchable_pdf(
    image_path: Path | str,
    ocr_json_path: Path | str,
    output_pdf_path: Path | str,
) -> Path:
    """Create one searchable PDF page with the original image as background."""
    canvas_mod, ImageReader, _, _, _ = _load_reportlab()
    image = Path(image_path)
    ocr_json = Path(ocr_json_path)
    output = Path(output_pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    layout = json.loads(ocr_json.read_text(encoding="utf-8"))
    blocks = layout.get("blocks")
    if not isinstance(blocks, list):
        raise RuntimeError(f"OCR JSON missing blocks: {ocr_json}")

    width, height = _pdf_page_geometry(image)

    font_name = _register_search_font()
    c = canvas_mod.Canvas(str(output), pagesize=(width, height))
    c.drawImage(ImageReader(str(image)), 0, 0, width=width, height=height)

    for block in blocks:
        if not isinstance(block, dict):
            continue
        text = _safe_text(block.get("text"))
        bbox = _block_bbox(block)
        if not text or bbox is None:
            continue
        x, y, w, h = bbox
        box_x = x * width
        box_w = w * width
        box_h = h * height
        # PDF coordinates are bottom-left, OCR bboxes are top-left.
        box_y = height - ((y + h) * height)
        font_size = _font_size_for(text, box_w, box_h)
        text_obj = c.beginText()
        text_obj.setTextOrigin(box_x, box_y + max(0.0, box_h - font_size))
        text_obj.setFont(font_name, font_size)
        text_obj.setTextRenderMode(3)  # invisible text; searchable/selectable layer.
        text_obj.setLeading(font_size * 1.15)
        for line in text.splitlines() or [text]:
            text_obj.textLine(line)
        c.drawText(text_obj)

    c.showPage()
    c.save()
    return output


def build_page_image_pdf(
    image_path: Path | str,
    output_pdf_path: Path | str,
) -> Path:
    """Create one plain PDF page with the captured image as the full page."""
    canvas_mod, ImageReader, _, _, _ = _load_reportlab()
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
    except ImportError:  # pragma: no cover
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
