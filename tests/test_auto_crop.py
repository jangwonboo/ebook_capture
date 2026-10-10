"""Post-capture page-outline detection -> common PDF crop."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from core.auto_crop import (
    PageBoxes,
    PageOutline,
    analyze_page,
    border_color,
    content_bbox,
    nested_content_boxes,
    outline_from_page_boxes,
    outline_to_trim,
    page_outline_from_images,
)
from core.config import PdfTrim

W, H = 200, 300
WHITE = (255, 255, 255)
# Reader letterbox: page occupies x 20..180, y 10..290 (ratios .1/.0333/.9/.9667).
PAGE = (20, 10, 180, 290)
PAGE_R = (0.1, 10 / 300, 0.9, 290 / 300)


def _canvas(color=WHITE) -> Image.Image:
    return Image.new("RGB", (W, H), color)


def _rect(img: Image.Image, box, color) -> None:
    ImageDraw.Draw(img).rectangle([box[0], box[1], box[2] - 1, box[3] - 1], fill=color)


def _full_bleed_page(color=(230, 200, 190), bg=WHITE) -> Image.Image:
    img = _canvas(bg)
    _rect(img, PAGE, color)
    return img


def _text_page(y0: int = 60, y1: int = 240, bg=WHITE) -> Image.Image:
    """White page (PAGE) on ``bg`` with black text lines inside."""
    img = _canvas(bg)
    _rect(img, PAGE, WHITE)
    d = ImageDraw.Draw(img)
    for y in range(y0, y1, 12):
        d.rectangle([40, y, 160, y + 3], fill=(0, 0, 0))
    return img


def _close(a, b, tol=0.01) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_border_color_is_reader_background() -> None:
    assert border_color(_full_bleed_page()) == WHITE


def test_content_bbox_finds_page_rectangle() -> None:
    assert content_bbox(_full_bleed_page(), WHITE) == PAGE


def test_nested_boxes_peel_bars_then_page_then_art() -> None:
    # Black RDP bars (x<20, x>=180) around a white page with pink cover art inset.
    img = _canvas((0, 0, 0))
    _rect(img, (20, 0, 180, 300), WHITE)
    _rect(img, (40, 30, 160, 280), (230, 200, 190))
    passes = nested_content_boxes(img)
    boxes = [b for b, _ in passes]
    fills = [f for _, f in passes]
    assert boxes[0] == (20, 0, 180, 300) and fills[0] > 0.9  # page vs bars
    assert boxes[1] == (40, 30, 160, 280) and fills[1] > 0.9  # art vs page


def test_analyze_text_page_on_white_has_no_solid_box() -> None:
    p = analyze_page(_text_page())
    assert p.solid is None
    assert p.content is not None
    l, t, r, b = p.content
    assert 0.15 < l < 0.25 and 0.75 < r < 0.85  # text extents only


def test_analyze_full_bleed_page_outline_is_solid() -> None:
    p = analyze_page(_full_bleed_page())
    assert p.solid is not None and _close(p.solid, PAGE_R)


def test_analyze_rdp_bars_text_page_outline_is_page_frame() -> None:
    # Black bars either side: the white page is solid against them even
    # though its text is sparse. Outermost solid box = page frame.
    p = analyze_page(_text_page(bg=(0, 0, 0)))
    assert p.solid is not None and _close(p.solid, PAGE_R)


def test_outline_median_of_solid_boxes_majority_wins() -> None:
    page_frame = PAGE_R
    cover_art = (0.2, 0.1, 0.8, 0.93)
    pages = [
        PageBoxes(content=page_frame, solid=cover_art),  # cover: art inset is innermost
        PageBoxes(content=page_frame, solid=page_frame),
        PageBoxes(content=page_frame, solid=page_frame),
        PageBoxes(content=(0.2, 0.2, 0.8, 0.8), solid=None),
    ]
    o = outline_from_page_boxes(pages)
    assert o.source == "solid"
    assert o.n_solid == 3 and o.n_pages == 4
    assert o.as_tuple() == page_frame


def test_outline_falls_back_to_content_union() -> None:
    pages = [
        PageBoxes(content=(0.2, 0.2, 0.8, 0.8)),
        PageBoxes(content=(0.15, 0.25, 0.85, 0.9)),
    ]
    o = outline_from_page_boxes(pages, margin=0.05)
    assert o.source == "content_union"
    assert _close(o.as_tuple(), (0.1, 0.15, 0.9, 0.95), tol=1e-9)


def test_outline_empty_when_no_content() -> None:
    o = outline_from_page_boxes([])
    assert o.source == "none" and o.is_identity()


def test_page_outline_from_images_white_reader(tmp_path: Path) -> None:
    pages = [
        _full_bleed_page(),
        _text_page(),
        _text_page(80, 200),
        _full_bleed_page((40, 40, 60)),
    ]
    paths = []
    for i, img in enumerate(pages):
        p = tmp_path / f"p_{i:04d}.png"
        img.save(p)
        paths.append(p)
    o = page_outline_from_images(paths)
    assert o.source == "solid" and o.n_solid == 2
    assert _close(o.as_tuple(), PAGE_R)


def test_page_outline_from_images_rdp_bars(tmp_path: Path) -> None:
    """Black side bars + white page: every page is solid; cover art inset must
    not shrink the common outline because text pages are the majority."""
    black = (0, 0, 0)
    cover = _text_page(bg=black)
    _rect(cover, (40, 30, 160, 280), (230, 200, 190))
    pages = [cover, _text_page(bg=black), _text_page(70, 230, bg=black)]
    paths = []
    for i, img in enumerate(pages):
        p = tmp_path / f"p_{i:04d}.png"
        img.save(p)
        paths.append(p)
    o = page_outline_from_images(paths)
    assert o.source == "solid" and o.n_solid == 3
    assert _close(o.as_tuple(), PAGE_R)


def test_outline_to_trim_keeps_fill_bands_and_clamps() -> None:
    o = PageOutline(
        left=0.1, top=0.05, right=0.9, bottom=0.98, source="solid", n_pages=3, n_solid=1
    )
    trim = outline_to_trim(o, PdfTrim(fill_top=0.02))
    assert trim.as_dict() == {
        "left": 0.1,
        "right": 0.1,
        "top": 0.05,
        "bottom": 0.02,
        "fill_top": 0.02,
        "fill_bottom": 0.0,
    }
    wide = PageOutline(left=0.6, top=0.0, right=1.0, bottom=1.0, source="content_union", n_pages=1)
    assert outline_to_trim(wide).left == 0.45  # PdfTrim edge ceiling


def test_outline_to_trim_none_source_returns_base() -> None:
    base = PdfTrim(top=0.035)
    assert outline_to_trim(PageOutline(), base).as_dict() == base.as_dict()
