"""Detect the page outline shared by captured pages and turn it into a crop.

Readers letterbox the page inside their own background (white or grey bands
left/right, RDP adds black bars when the remote aspect differs). The outline is
invisible on a plain text page when page and reader background are both white,
but obvious on pages with a full-bleed background: cover, part openers,
dark-themed figures. Those pages give the true page rectangle; the median of
their boxes is applied to every page so the whole PDF shares one crop.

Per page the analysis peels uniform borders in passes: the median colour of the
outermost pixels is the background of that pass, the bounding box of everything
else is the next region. Each box is "solid" when most pixels inside differ from
that background (a page against black bars, cover art against the page) and
"sparse" when they do not (text on a white page). The outermost solid box of a
page is its outline candidate.

When no page has a solid box the fallback is the union of the first-pass content
boxes (text, page numbers, headers), which at least removes the reader bands.

A second pass looks for reader chrome: rows at the top / bottom edge whose
pixels (within the outline's horizontal span) are identical on a large share of
the pages and are not blank page background. A toolbar that pops up part-way
through a run and stays is found this way and folded into the crop.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageChops, ImageStat

from core.config import PdfTrim

ProgressFn = Callable[[str], None]

Box = tuple[int, int, int, int]
RatioBox = tuple[float, float, float, float]
ImageSource = "Path | str | Image.Image"

# Downscale target width for analysis (speed; 1438 px pages -> 3x reduce).
_ANALYSIS_MAX_WIDTH = 400
# Per-channel distance from the pass background that counts as content.
_DEFAULT_TOLERANCE = 10
# Share of content pixels inside a box for it to count as a solid region.
_DEFAULT_SOLID_FILL = 0.6
# Border-peeling passes per page (bars -> page -> art is plenty).
_MAX_PASSES = 3
# PdfTrim refuses to crop more than this per edge.
_MAX_EDGE_TRIM = 0.45
# Chrome detection: scan this share of the height from the top and bottom
# edge; a row is chrome when identical on at least this share of the pages.
_CHROME_BAND = 0.15
_CHROME_SHARE = 0.3


@dataclass
class PageOutline:
    """Page rectangle as ratios of the capture (left/top inclusive, right/bottom exclusive)."""

    left: float = 0.0
    top: float = 0.0
    right: float = 1.0
    bottom: float = 1.0
    source: str = "none"  # solid | content_union | none
    n_pages: int = 0
    n_solid: int = 0
    # Reader chrome (toolbar / nav bar) found as rows identical across many
    # pages at the top / bottom edge; already folded into top / bottom.
    chrome_top: float = 0.0
    chrome_bottom: float = 0.0

    def as_tuple(self) -> RatioBox:
        return (self.left, self.top, self.right, self.bottom)

    def is_identity(self) -> bool:
        return (
            self.left <= 0.0
            and self.top <= 0.0
            and self.right >= 1.0
            and self.bottom >= 1.0
        )


@dataclass
class PageBoxes:
    """Per-page outline analysis (ratios of the capture)."""

    content: RatioBox | None = None  # first-pass bounding box
    solid: RatioBox | None = None  # outermost solid box (page outline candidate)
    passes: list[tuple[RatioBox, float]] = field(default_factory=list)


# Row signature for chrome detection: (hash of the row's pixels, uniform?, mean colour).
RowSig = tuple[bytes, bool, tuple[int, int, int]]


@dataclass
class PageBands:
    """Per-page edge rows for chrome detection (full resolution)."""

    top_rows: list[RowSig]  # top-down
    bottom_rows: list[RowSig]  # bottom-up
    page_bg: tuple[int, int, int]
    height: int


# --- outline ---------------------------------------------------------------


def _analysis_image(img: Image.Image) -> Image.Image:
    # convert() always yields a new, fully loaded image, so the caller may
    # close the source file right after this returns.
    work = img.convert("RGB")
    factor = max(1, work.width // _ANALYSIS_MAX_WIDTH)
    return work.reduce(factor) if factor > 1 else work


def border_color(img: Image.Image, band: int = 2) -> tuple[int, int, int]:
    """Median colour of the outermost ``band`` pixels."""
    w, h = img.size
    band = max(1, min(band, w // 2, h // 2))
    strips = [
        img.crop((0, 0, w, band)),
        img.crop((0, h - band, w, h)),
        img.crop((0, 0, band, h)),
        img.crop((w - band, 0, w, h)),
    ]
    channels: list[list[int]] = [[], [], []]
    for strip in strips:
        raw = strip.tobytes()
        channels[0].extend(raw[0::3])
        channels[1].extend(raw[1::3])
        channels[2].extend(raw[2::3])
    return tuple(int(median(c)) for c in channels)  # type: ignore[return-value]


def content_mask(
    img: Image.Image,
    bg: tuple[int, int, int],
    tolerance: int = _DEFAULT_TOLERANCE,
) -> Image.Image:
    """Binary mask (255) of pixels that differ from ``bg`` by more than ``tolerance``."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, bg))
    r, g, b = diff.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b)
    return mask.point(lambda v: 255 if v > tolerance else 0)


def content_bbox(
    img: Image.Image,
    bg: tuple[int, int, int],
    tolerance: int = _DEFAULT_TOLERANCE,
) -> Box | None:
    return content_mask(img, bg, tolerance).getbbox()


def nested_content_boxes(
    img: Image.Image,
    *,
    tolerance: int = _DEFAULT_TOLERANCE,
    max_passes: int = _MAX_PASSES,
    stop_below_fill: float = _DEFAULT_SOLID_FILL,
) -> list[tuple[Box, float]]:
    """Peel uniform borders pass by pass.

    Returns ``[(box_px, fill_ratio), ...]`` from outermost to innermost, boxes
    in coordinates of ``img``. ``fill_ratio`` is the share of pixels inside the
    box that differ from that pass's background. Peeling stops at the first
    sparse box (fill below ``stop_below_fill``): that is page content, and the
    border of a text block is not a background to peel further.
    """
    out: list[tuple[Box, float]] = []
    region = img
    ox = oy = 0
    for _ in range(max(1, max_passes)):
        bg = border_color(region)
        mask = content_mask(region, bg, tolerance)
        box = mask.getbbox()
        if box is None:
            break
        area = (box[2] - box[0]) * (box[3] - box[1])
        filled = mask.crop(box).histogram()[255]
        fill = filled / area if area > 0 else 0.0
        abs_box: Box = (box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy)
        if out and abs_box == out[-1][0]:
            break  # nothing peeled; further passes would repeat
        out.append((abs_box, fill))
        if fill < stop_below_fill:
            break
        if box == (0, 0, region.width, region.height):
            break
        region = region.crop(box)
        ox, oy = abs_box[0], abs_box[1]
    return out


def _ratios(box: Box, size: tuple[int, int]) -> RatioBox:
    w, h = size
    l, t, r, b = box
    return (l / w, t / h, r / w, b / h)


def analyze_page(
    img: Image.Image,
    *,
    tolerance: int = _DEFAULT_TOLERANCE,
    solid_fill: float = _DEFAULT_SOLID_FILL,
) -> PageBoxes:
    """Content box and outline candidate of one captured page."""
    work = _analysis_image(img)
    passes = nested_content_boxes(work, tolerance=tolerance, stop_below_fill=solid_fill)
    result = PageBoxes(passes=[(_ratios(b, work.size), f) for b, f in passes])
    if not passes:
        return result
    result.content = result.passes[0][0]
    for box, fill in result.passes:
        if fill >= solid_fill:
            result.solid = box
            break
    return result


def outline_from_page_boxes(
    pages: Sequence[PageBoxes],
    *,
    margin: float = 0.0,
) -> PageOutline:
    """Median of the per-page solid boxes; union of content boxes as fallback."""
    solid = [p.solid for p in pages if p.solid is not None]
    content = [p.content for p in pages if p.content is not None]
    if solid:
        l = median(b[0] for b in solid)
        t = median(b[1] for b in solid)
        r = median(b[2] for b in solid)
        btm = median(b[3] for b in solid)
        source = "solid"
    elif content:
        l = min(b[0] for b in content)
        t = min(b[1] for b in content)
        r = max(b[2] for b in content)
        btm = max(b[3] for b in content)
        source = "content_union"
    else:
        return PageOutline(n_pages=0)
    m = max(0.0, float(margin))
    return PageOutline(
        left=max(0.0, l - m),
        top=max(0.0, t - m),
        right=min(1.0, r + m),
        bottom=min(1.0, btm + m),
        source=source,
        n_pages=len(content),
        n_solid=len(solid),
    )


# --- chrome ----------------------------------------------------------------


def _row_signature(row: Image.Image, tolerance: int) -> RowSig:
    extrema = row.getextrema()
    uniform = all(hi - lo <= tolerance for lo, hi in extrema)
    mean = tuple(int(round(v)) for v in ImageStat.Stat(row).mean)
    return hashlib.sha1(row.tobytes()).digest(), uniform, mean  # type: ignore[return-value]


def page_bands(
    img: Image.Image,
    *,
    span: tuple[float, float] = (0.0, 1.0),
    band: float = _CHROME_BAND,
    tolerance: int = _DEFAULT_TOLERANCE,
) -> PageBands:
    """Edge-row signatures of one page, restricted to the horizontal ``span``
    (ratios) so reader side bars do not make blank rows look like content."""
    full = img.convert("RGB")
    w, h = full.size
    x0 = max(0, min(w - 1, int(round(w * span[0]))))
    x1 = max(x0 + 1, min(w, int(round(w * span[1]))))
    n = max(1, int(h * band))
    top = [_row_signature(full.crop((x0, y, x1, y + 1)), tolerance) for y in range(n)]
    bottom = [
        _row_signature(full.crop((x0, y, x1, y + 1)), tolerance)
        for y in range(h - 1, h - 1 - n, -1)
    ]
    py = int(h * 0.2)
    probe = full.crop((x0, py, x1, py + 1))
    bg = tuple(int(v) for v in ImageStat.Stat(probe).median)
    return PageBands(top, bottom, bg, h)  # type: ignore[arg-type]


def _color_close(a: Sequence[int], b: Sequence[int], tolerance: int) -> bool:
    return all(abs(int(x) - int(y)) <= tolerance for x, y in zip(a, b))


def chrome_bands(
    bands: Sequence[PageBands],
    *,
    share: float = _CHROME_SHARE,
    tolerance: int = _DEFAULT_TOLERANCE,
) -> tuple[float, float]:
    """Height of reader chrome at the top and bottom edge, as ratios.

    A row belongs to chrome when some pixel pattern appears at that row on at
    least ``share`` of the pages and that pattern is not blank page background
    (uniform and close to the page colour). Scanning stops at the first row
    without such a pattern, so only an edge-anchored band is ever reported.
    """
    usable = [b for b in bands if b.top_rows]
    if len(usable) < 2:
        return 0.0, 0.0
    need = max(2, int(round(len(usable) * share)))
    height = median(b.height for b in usable)

    # Blank colour = the most common colour among uniform edge rows over all
    # pages (page margins dominate; a cover or a few full-bleed openers do not).
    tally_bg: dict[tuple[int, int, int], int] = {}
    for b in usable:
        for _, uniform, mean in (*b.top_rows, *b.bottom_rows):
            if uniform:
                key = tuple(int(v) // 8 * 8 for v in mean)  # type: ignore[assignment]
                tally_bg[key] = tally_bg.get(key, 0) + 1  # type: ignore[index]
    bg = max(tally_bg.items(), key=lambda kv: kv[1])[0] if tally_bg else (255, 255, 255)
    bg_tol = tolerance + 8  # quantisation step

    def _scan(rows_of: Callable[[PageBands], list[RowSig]]) -> int:
        """Contiguous run of rows (from the edge) where some pattern is shared
        by >= ``need`` pages and is not the blank colour. The run counts only
        if it holds at least one non-uniform row (icons / text): a stack of
        plain coloured rows is a page design, not a toolbar."""
        depth = min(len(rows_of(b)) for b in usable)
        count = 0
        saw_pattern = False
        for i in range(depth):
            tally: dict[bytes, int] = {}
            sig_by_hash: dict[bytes, RowSig] = {}
            for b in usable:
                sig = rows_of(b)[i]
                tally[sig[0]] = tally.get(sig[0], 0) + 1
                sig_by_hash.setdefault(sig[0], sig)
            chrome_here = False
            for h, n in tally.items():
                if n < need:
                    continue
                _, uniform, mean = sig_by_hash[h]
                if uniform and _color_close(mean, bg, bg_tol):
                    continue  # blank margin shared by many pages
                chrome_here = True
                saw_pattern = saw_pattern or not uniform
                break
            if not chrome_here:
                break
            count += 1
        return count if saw_pattern else 0

    top = _scan(lambda b: b.top_rows)
    bottom = _scan(lambda b: b.bottom_rows)
    if not height:
        return 0.0, 0.0
    return top / height, bottom / height


def apply_chrome_bands(
    outline: PageOutline,
    bands: Sequence[PageBands],
    *,
    share: float = _CHROME_SHARE,
    tolerance: int = _DEFAULT_TOLERANCE,
) -> PageOutline:
    """Fold reader chrome found by ``chrome_bands`` into the outline's top/bottom."""
    if outline.source == "none":
        return outline
    top, bottom = chrome_bands(bands, share=share, tolerance=tolerance)
    outline.chrome_top = top
    outline.chrome_bottom = bottom
    if top > 0.0:
        outline.top = max(outline.top, min(top, _MAX_EDGE_TRIM))
    if bottom > 0.0:
        outline.bottom = min(outline.bottom, max(1.0 - bottom, 1.0 - _MAX_EDGE_TRIM))
    return outline


# --- driver ----------------------------------------------------------------


def _open_each(
    sources: Iterable[Path | str | Image.Image],
    fn: Callable[[Image.Image], object],
    progress: ProgressFn | None,
) -> list:
    out = []
    for src in sources:
        if isinstance(src, Image.Image):
            out.append(fn(src))
            continue
        try:
            with Image.open(src) as img:
                out.append(fn(img))
        except (OSError, ValueError) as exc:
            if progress:
                progress(f"AUTO_CROP_SKIP {src} {exc!r}")
    return out


def page_outline_from_images(
    sources: Iterable[Path | str | Image.Image],
    *,
    tolerance: int = _DEFAULT_TOLERANCE,
    solid_fill: float = _DEFAULT_SOLID_FILL,
    margin: float = 0.0,
    detect_chrome: bool = True,
    progress: ProgressFn | None = None,
) -> PageOutline:
    """Scan captured pages and return the shared page outline (two passes:
    outline, then chrome rows within the outline's horizontal span)."""
    sources = list(sources)
    pages: list[PageBoxes] = _open_each(
        sources,
        lambda img: analyze_page(img, tolerance=tolerance, solid_fill=solid_fill),
        progress,
    )
    outline = outline_from_page_boxes(pages, margin=margin)
    if not detect_chrome or outline.source == "none":
        return outline
    span = (outline.left, outline.right)
    bands: list[PageBands] = _open_each(
        sources,
        lambda img: page_bands(img, span=span, tolerance=tolerance),
        progress,
    )
    return apply_chrome_bands(outline, bands, tolerance=tolerance)


def outline_to_trim(outline: PageOutline, base: PdfTrim | None = None) -> PdfTrim:
    """Crop edges from ``outline``; white-fill bands are kept from ``base``."""
    base = base or PdfTrim()
    if outline.source == "none":
        return PdfTrim(
            left=base.left,
            right=base.right,
            top=base.top,
            bottom=base.bottom,
            fill_top=base.fill_top,
            fill_bottom=base.fill_bottom,
        )

    def _edge(v: float) -> float:
        return round(max(0.0, min(_MAX_EDGE_TRIM, v)), 4)

    trim = PdfTrim(
        left=_edge(outline.left),
        right=_edge(1.0 - outline.right),
        top=_edge(outline.top),
        bottom=_edge(1.0 - outline.bottom),
        fill_top=base.fill_top,
        fill_bottom=base.fill_bottom,
    )
    trim.validate()
    return trim
