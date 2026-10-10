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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageChops

from core.config import PdfTrim

ProgressFn = Callable[[str], None]

Box = tuple[int, int, int, int]
RatioBox = tuple[float, float, float, float]

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
    """Per-page analysis result (ratios of the capture)."""

    content: RatioBox | None = None  # first-pass bounding box
    solid: RatioBox | None = None  # outermost solid box (page outline candidate)
    passes: list[tuple[RatioBox, float]] = field(default_factory=list)


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


def page_outline_from_images(
    paths: Iterable[Path | str],
    *,
    tolerance: int = _DEFAULT_TOLERANCE,
    solid_fill: float = _DEFAULT_SOLID_FILL,
    margin: float = 0.0,
    progress: ProgressFn | None = None,
) -> PageOutline:
    """Scan captured pages and return the shared page outline."""
    pages: list[PageBoxes] = []
    for path in paths:
        try:
            with Image.open(path) as src:
                pages.append(analyze_page(src, tolerance=tolerance, solid_fill=solid_fill))
        except (OSError, ValueError) as exc:
            if progress:
                progress(f"AUTO_CROP_SKIP {path} {exc!r}")
    return outline_from_page_boxes(pages, margin=margin)


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
