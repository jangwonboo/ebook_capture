"""Build image-only PDFs from captured PNG pages."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from core.config import PdfTrim


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


def crop_image_by_trim_ratios(img: Image.Image, trim: PdfTrim) -> Image.Image:
    """Apply ``PdfTrim``: optional white-fill bands, then crop margins.

    ``fill_*`` values are ratios of the original corresponding dimension and
    paint white starting just inside the matching crop edge. This removes
    toolbars and persistent reader borders without removing page height/width.
    """
    from PIL import ImageDraw

    trim.validate()
    if not trim.is_active():
        return img
    width_px, height_px = img.size
    left = int(round(width_px * trim.left))
    top = int(round(height_px * trim.top))
    right = width_px - int(round(width_px * trim.right))
    bottom = height_px - int(round(height_px * trim.bottom))
    if right - left < 2 or bottom - top < 2:
        raise ValueError(
            f"pdf_trim leaves too little content: "
            f"crop=({left},{top},{right},{bottom}) size={width_px}x{height_px}"
        )

    work = img
    fill_top_px = int(round(height_px * trim.fill_top))
    fill_bottom_px = int(round(height_px * trim.fill_bottom))
    fill_left_px = int(round(width_px * trim.fill_left))
    fill_right_px = int(round(width_px * trim.fill_right))
    if fill_top_px > 0 or fill_bottom_px > 0 or fill_left_px > 0 or fill_right_px > 0:
        work = img.copy()
        if work.mode not in ("RGB", "RGBA"):
            work = work.convert("RGB")
        drawer = ImageDraw.Draw(work)
        if fill_top_px > 0:
            y1 = min(bottom, top + fill_top_px)
            if y1 > top:
                drawer.rectangle([left, top, right - 1, y1 - 1], fill=(255, 255, 255))
        if fill_bottom_px > 0:
            y0 = max(top, bottom - fill_bottom_px)
            if bottom > y0:
                drawer.rectangle([left, y0, right - 1, bottom - 1], fill=(255, 255, 255))
        if fill_left_px > 0:
            x1 = min(right, left + fill_left_px)
            if x1 > left:
                drawer.rectangle([left, top, x1 - 1, bottom - 1], fill=(255, 255, 255))
        if fill_right_px > 0:
            x0 = max(left, right - fill_right_px)
            if right > x0:
                drawer.rectangle([x0, top, right - 1, bottom - 1], fill=(255, 255, 255))

    return work.crop((left, top, right, bottom))


def pad_image_to_aspect(img: Image.Image, aspect: float) -> Image.Image:
    """Center ``img`` on a white canvas whose width/height equals ``aspect``.

    White margins are added on whichever pair of sides is needed (never crops or
    scales), so the page fills a device screen of that aspect ratio. ``aspect``
    <= 0 returns the image unchanged.
    """
    if aspect <= 0.0:
        return img
    work = img if img.mode in ("RGB", "RGBA") else img.convert("RGB")
    w, h = work.size
    if w <= 0 or h <= 0:
        return work
    if w / h < aspect:                       # too narrow -> pad left/right
        canvas_w, canvas_h = round(h * aspect), h
    else:                                    # too wide -> pad top/bottom
        canvas_w, canvas_h = w, round(w / aspect)
    if canvas_w <= w and canvas_h <= h:
        return work
    out = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
    out.paste(work, ((canvas_w - w) // 2, (canvas_h - h) // 2))
    return out


def pad_image_with_margin(img: Image.Image, margin: float) -> Image.Image:
    """Add equal white margins around all sides of ``img``.

    ``margin`` is a fraction of the image's original width and height per side.
    """
    margin = float(margin)
    if margin <= 0.0:
        return img
    work = img if img.mode in ("RGB", "RGBA") else img.convert("RGB")
    width, height = work.size
    if width <= 0 or height <= 0:
        return work
    x = round(width * margin)
    y = round(height * margin)
    if x <= 0 and y <= 0:
        return work
    out = Image.new("RGB", (width + 2 * x, height + 2 * y), (255, 255, 255))
    out.paste(work, (x, y))
    return out


def _pdf_page_geometry_from_image(img: Image.Image) -> tuple[float, float]:
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


def _pdf_page_geometry(image_path: Path) -> tuple[float, float]:
    with Image.open(image_path) as img:
        return _pdf_page_geometry_from_image(img)


def build_page_image_pdf(
    image_path: Path | str,
    output_pdf_path: Path | str,
    *,
    trim: PdfTrim | None = None,
    page_aspect: float = 0.0,
    page_margin: float = 0.0,
) -> Path:
    """Create one plain PDF page with the captured image as the full page.

    ``trim`` crops margins as fractions of the capture width/height before
    embedding (so trim scales with resolution). ``page_margin`` adds equal white
    margins around the cropped page. ``page_aspect`` (width/height), when > 0,
    then pads the result to that ratio so it fills a device screen.
    """
    canvas_mod, ImageReader = _load_reportlab()
    image = Path(image_path)
    output = Path(output_pdf_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    trim = trim or PdfTrim()
    with Image.open(image) as src:
        cropped = crop_image_by_trim_ratios(src, trim)
        padded = pad_image_with_margin(cropped, page_margin)
        padded = pad_image_to_aspect(padded, page_aspect)
        # Copy so we can close the source file handle before writing PDF.
        work = padded.copy()
        if "dpi" in src.info:
            work.info["dpi"] = src.info["dpi"]

    width, height = _pdf_page_geometry_from_image(work)

    c = canvas_mod.Canvas(str(output), pagesize=(width, height))
    c.drawImage(ImageReader(work), 0, 0, width=width, height=height)
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
