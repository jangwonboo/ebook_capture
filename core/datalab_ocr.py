"""Datalab OCR (https://www.datalab.to): hosted Marker, typed layout chunks.

Ported from ``parallax/vendor/vlmparse/backends/datalab.py``. The rules below
(429 is a queue wait, transport errors back off, billing is in cents, request
``chunks`` not markdown) were each learned on a real book; keep them.

A page image (or a one-page PDF) goes to ``POST /api/v1/convert`` and comes
back as ``chunks``: one block per layout element with a ``block_type``. We only
map those types onto the section types this repo's assembler already knows
(``title`` / ``section_title`` / ``body`` / ``caption`` / ``footnote`` /
``header`` / ``page_number`` / ``toc``), so ``core.assemble_markdown`` builds
the chapter / paragraph Markdown exactly as it does for Gemini output.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import threading
import time
from html import unescape
from pathlib import Path
from typing import Any

URL = "https://www.datalab.to/api/v1/convert"
PLACEHOLDER = "your-datalab-api-key-here"
MODES = ("fast", "balanced", "accurate")
DEFAULT_MODE = "accurate"
ENGINE_NAME = "datalab"

# Reader chrome and model-written figure descriptions. ``PageHeader`` /
# ``PageNumber`` are kept as sections (the assembler uses printed section
# numbers) but never reach the Markdown body.
TYPE_MAP = {
    "Text": "body",
    "TextInlineMath": "body",
    "ListGroup": "body",
    "ListItem": "body",
    "Caption": "caption",
    "Footnote": "footnote",
    "PageHeader": "header",
    "PageFooter": "page_number",
    "PageNumber": "page_number",
    # Datalab tags endnote lists as TableOfContents too; keep them as body.
    "TableOfContents": "body",
    "Table": "table",
    "TableGroup": "table",
    "Form": "table",
    "Equation": "equation",
    "Code": "code",
    "Handwriting": "body",
    "Span": "body",
    "Line": "body",
}
# Picture / Figure chunks carry a description the model invented, not page
# text. Dropping them keeps invented captions out of the body (parallax saw a
# cover illustration description land as an h1).
DROP_TYPES = frozenset({"Picture", "Figure", "FigureGroup", "PictureGroup"})

HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
INLINE_TAG_RE = re.compile(r"</?(?:b|i|u|em|strong|span|a|s|mark|small|sub|code)\b[^>]*>", re.I)
H_TAG_RE = re.compile(r"<h([1-6])")
# Marker wraps LaTeX in <math> (not MathML). Strip tags *after* converting it
# or the delimiters vanish and ``\Delta e`` ends up as prose.
MATH_RE = re.compile(r"<math\b([^>]*)>(.*?)</math>", re.I | re.S)
DISPLAY_ATTR_RE = re.compile(r"""display\s*=\s*["']?block""", re.I)


def display_math(body: str) -> str:
    """``$$`` fenced block with the fences on their own lines — the form every
    renderer accepts (Typora ignores single-line ``$$…$$``; GitHub, Obsidian,
    VS Code and pandoc take both). Each ``\\\\`` row break in an aligned
    environment starts a new line so the source stays readable."""
    body = re.sub(r"\s+", " ", body).strip()
    body = re.sub(r"\s*\\\\\s+", lambda _m: " \\\\\n", body)
    return f"$$\n{body}\n$$"
LI_RE = re.compile(r"<li\b[^>]*>", re.I)
BR_RE = re.compile(r"<br\s*/?>|</p>|</div>|</tr>", re.I)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
SUP_RE = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.I | re.S)
FOOTNOTE_MARK_RE = re.compile(r"^[\d\s,*†‡§¶\[\]()a-z]*$", re.I)


def _sup_replacement(m: re.Match) -> str:
    inner = HTML_TAG_RE.sub("", m.group(1)).strip()
    return "" if FOOTNOTE_MARK_RE.match(inner) else inner


class DatalabError(RuntimeError):
    pass


# ── key ───────────────────────────────────────────────────────────────────
def _load_env_file() -> None:
    """Pull ``.env`` (cwd, repo root) into the environment; same files Gemini uses."""
    from core.google_ocr import _load_env

    try:
        _load_env()
    except RuntimeError:
        pass


def _env_key() -> str | None:
    key = os.environ.get("DATALAB_API_KEY", "").strip().strip('"').strip("'")
    return key if key and key != PLACEHOLDER else None


def find_key(explicit: str | None = None) -> str | None:
    """Explicit value, else ``DATALAB_API_KEY`` from the environment, else .env."""
    if explicit and explicit != PLACEHOLDER:
        return explicit
    key = _env_key()
    if key:
        return key
    _load_env_file()
    return _env_key()


# ── billing ───────────────────────────────────────────────────────────────
class Spend:
    """Sums the per-request cost. **Units are cents** (``total_cost: 1`` and
    ``cost_breakdown.final_cost_cents: 1.0`` arrive together); reading it as
    dollars once made a 5-cent trial look like $5."""

    def __init__(self) -> None:
        self.pages = 0
        self.usd = 0.0
        self._lock = threading.Lock()

    def record(self, status: dict) -> None:
        cents = (status.get("cost_breakdown") or {}).get("final_cost_cents")
        if cents is None:
            cents = status.get("total_cost")
        try:
            value = float(cents or 0)
        except (TypeError, ValueError):
            return
        with self._lock:
            self.pages += 1
            self.usd += value / 100.0

    def summary(self) -> str:
        return f"pages={self.pages} usd={self.usd:.2f}"


# ── HTTP ──────────────────────────────────────────────────────────────────
def _verify_context():
    """Reuse the Gemini TLS setup so a corporate CA bundle works here too."""
    try:
        from core.google_ocr import _ssl_context

        return _ssl_context()
    except Exception:
        return True


def read_bytes(
    data: bytes,
    filename: str,
    mime: str,
    key: str,
    *,
    mode: str = DEFAULT_MODE,
    spend: Spend | None = None,
    timeout_s: int = 300,
    poll_interval: float = 2.0,
) -> list[dict]:
    """Submit one page (image or single-page PDF) and poll until its chunks arrive."""
    import httpx

    if mode not in MODES:
        raise DatalabError(f"datalab mode must be one of {', '.join(MODES)}: {mode!r}")
    headers = {"X-API-Key": key}
    with httpx.Client(timeout=60, verify=_verify_context()) as client:
        # 429 is a queue position, not a failure; transport errors (server
        # disconnects) must back off too or pages come back silently empty.
        response = None
        for attempt in range(8):
            try:
                response = client.post(
                    URL,
                    headers=headers,
                    files={"file": (filename, data, mime)},
                    data={"output_format": "chunks", "mode": mode},
                )
            except httpx.TransportError:
                if attempt == 7:
                    raise
                time.sleep(min(60, 5 * 2**attempt))
                continue
            if response.status_code != 429:
                break
            time.sleep(float(response.headers.get("Retry-After") or min(60, 5 * 2**attempt)))
        assert response is not None
        if response.status_code == 401:
            raise DatalabError("Datalab rejected DATALAB_API_KEY (401)")
        if response.status_code == 402:
            raise DatalabError("Datalab credits exhausted (402)")
        response.raise_for_status()
        submitted = response.json()
        if not submitted.get("success", True):
            raise DatalabError(submitted.get("error") or str(submitted))

        check_url = submitted["request_check_url"]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                poll = client.get(check_url, headers=headers)
            except httpx.TransportError:
                continue
            if poll.status_code == 429:
                time.sleep(float(poll.headers.get("Retry-After") or 5))
                continue
            status = poll.json()
            state = status.get("status")
            if state == "complete":
                if status.get("success") is False:
                    raise DatalabError(status.get("error") or "failed")
                if spend is not None:
                    spend.record(status)
                chunks = status.get("chunks") or []
                if isinstance(chunks, dict):
                    chunks = chunks.get("blocks") or []
                return chunks
            if state == "failed":
                raise DatalabError(status.get("error") or "failed")
        raise DatalabError(f"poll timeout ({timeout_s}s)")


# ── chunks → sections ─────────────────────────────────────────────────────
LIST_BULLET_RE = re.compile(r"^- [•●▪■◆◇○∙·◦\-–—]+\s*")
# "- 1. 항목" / "- 1) 항목" / "- 1 항목" — but not "- 1.1 제목" (a section number).
LIST_ORDERED_RE = re.compile(r"^- (\d{1,3})(?:[.)]\s*|\s+)(?=\S)(?!\d)")


def _normalize_list_line(line: str) -> str:
    """``<li>`` items often repeat their marker in the text: ``- • 항목`` or
    ``- 1. 항목``. Keep one marker, and keep numbered items as an ordered list."""
    if not line.startswith("- "):
        return line
    m = LIST_ORDERED_RE.match(line)
    if m:
        return f"{m.group(1)}. {line[m.end():]}"
    return LIST_BULLET_RE.sub("- ", line)


def html_to_text(html: str) -> str:
    """Strip tags but keep paragraph / list breaks and ``$…$`` math."""

    def keep_math(m: re.Match) -> str:
        body = unescape(HTML_TAG_RE.sub("", m.group(2))).strip()
        if not body:
            return ""
        if DISPLAY_ATTR_RE.search(m.group(1)):
            return f"\n\n{display_math(body)}\n\n"  # display equation inside a text block
        return f"${body}$"

    text = MATH_RE.sub(keep_math, html)
    text = IMG_TAG_RE.sub("", text)
    # Footnote reference marks (<sup>3</sup>, <sup>*</sup>) are dropped: the
    # reader-side superscript has no anchor in Markdown and only litters
    # sentence ends. Word superscripts stay: a chapter opener's "1장" arrives
    # as <h1>1<sup>장</sup></h1>.
    text = SUP_RE.sub(_sup_replacement, text)
    text = LI_RE.sub("\n- ", text)
    text = BR_RE.sub("\n", text)
    # Inline emphasis carries no spacing of its own: "<b>자연어 처리</b>(NLP)"
    # must not become "자연어 처리 (NLP )". Block-level tags still separate.
    text = INLINE_TAG_RE.sub("", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = unescape(text).replace("**", "")
    raw_lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in text.split("\n")]
    # ``<li><div>8</div><div>Magee (2008)</div></li>`` (endnotes) splits the
    # number from its text; glue them back before normalising markers.
    glued: list[str] = []
    i = 0
    while i < len(raw_lines):
        ln = raw_lines[i]
        if re.fullmatch(r"- \d{1,3}", ln):
            j = i + 1
            while j < len(raw_lines) and not raw_lines[j]:
                j += 1
            if j < len(raw_lines) and not raw_lines[j].startswith("- "):
                glued.append(f"{ln} {raw_lines[j]}")
                i = j + 1
                continue
        glued.append(ln)
        i += 1
    lines = [_normalize_list_line(ln) for ln in glued]
    out: list[str] = []
    for ln in lines:
        if ln:
            out.append(ln)
        elif out and out[-1]:
            out.append("")
    return "\n".join(out).strip()


def equation_text(html: str) -> str:
    """Display equation → ``$$…$$`` (treat the whole block as LaTeX if no <math>)."""
    bodies = [unescape(HTML_TAG_RE.sub("", b)).strip() for _attrs, b in MATH_RE.findall(html)]
    body = " ".join(b for b in bodies if b) or unescape(HTML_TAG_RE.sub("", html)).strip()
    return display_math(body) if body.strip() else ""


TABLE_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)
TABLE_CELL_RE = re.compile(r"<(t[dh])\b([^>]*)>(.*?)</t[dh]>", re.I | re.S)
SPAN_ATTR_RE = re.compile(r"\b(?:row|col)span\s*=\s*[\"']?(\d+)", re.I)


def _cell_text(html: str) -> str:
    """Cell content as one Markdown line: math kept as ``$…$``, breaks as spaces."""
    text = html_to_text(html).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip().replace("|", "\\|")


def table_text(html: str) -> str:
    """A regular grid (no row/col spans, one header row) becomes a Markdown
    pipe table. Anything else keeps its HTML, with the math and images
    normalised, because the structure is the content."""
    html = IMG_TAG_RE.sub("", html)
    rows = []
    regular = True
    for row_html in TABLE_ROW_RE.findall(html):
        cells = TABLE_CELL_RE.findall(row_html)
        if not cells:
            continue
        if any(int(m) > 1 for _, attrs, _ in cells for m in SPAN_ATTR_RE.findall(attrs)):
            regular = False
        rows.append([(tag.lower(), _cell_text(body)) for tag, _attrs, body in cells])
    if not rows:
        return ""
    width = len(rows[0])
    if regular and width >= 2 and len(rows) >= 2 and all(len(r) == width for r in rows):
        header = [c for _, c in rows[0]]
        body = rows[1:]
        if not all(tag == "th" for tag, _ in rows[0]):
            header = [""] * width
            body = rows
        lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(c for _, c in r) + " |" for r in body]
        return "\n".join(lines)
    html = MATH_RE.sub(lambda m: f"${unescape(m.group(2)).strip()}$", html)
    return re.sub(r"\s+", " ", html).strip()


def code_text(html: str) -> str:
    body = unescape(BR_RE.sub("\n", HTML_TAG_RE.sub("", html))).rstrip()
    return f"```\n{body}\n```" if body.strip() else ""


def _header_level(html: str) -> int:
    m = H_TAG_RE.search(html)
    return int(m.group(1)) if m else 2


# Heading classification by *position*, not font size. Reflow ebook readers
# render numbered lists, pull quotes and endnotes in large type, and Marker
# then tags them SectionHeader with an arbitrary h1/h2. The bbox is reliable:
# chapter/section headings sit centred, sub-headings hug the left margin,
# and a "heading" spanning the full column is a body paragraph.
HEADING_FULL_WIDTH_RATIO = 0.80
HEADING_CENTER_TOLERANCE = 0.05
ORNAMENT_RE = re.compile(r"^[\s•●▪■◆◇○∙·.…⋮*\-–—]+$")
DIGITS_RE = re.compile(r"^\d{1,3}$")
# A chapter opener set as a big bare number ("01" over the chapter title).
CHAPTER_NUMBER_LABEL_RE = re.compile(r"^\d{1,2}$")
PRE_RE = re.compile(r"\s*<pre\b", re.I)
# Dotted section numbers at the start of a heading: "4.3 제목", "4.3.3.1 학습 단계".
SECTION_NUMBER_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+)\.?\s+\S")
# A section number set apart from its title ("4.8" in the running head, title
# in the next SectionHeader): glued to that title.
BARE_SECTION_NUMBER_RE = re.compile(r"^\d{1,2}(?:\.\d{1,2})+$")
COLUMN_LABEL_RE = re.compile(r"^\s*C\s*O\s*L\s*U\s*M\s*N\s*$", re.I)
# Running head set in capitals ("MACHINE LEARNING FOR DATA ANALYSIS") that
# Marker sometimes tags as a SectionHeader instead of a PageHeader.
RUNNING_HEAD_RE = re.compile(r"^[A-Z][A-Z0-9 ,.:&'-]{8,}$")
# A table-of-contents line: heading text followed by its page number.
TOC_ENTRY_RE = re.compile(r"(?:\.{2,}|…+)\s*\d{1,3}$|\s\d{2,3}$")
# Marker glyphs printed before captions ("♥ 그림 4-12 …", "▼ 표 4-1 …").
CAPTION_MARK_RE = re.compile(r"^[♥♡▼▽▾▸▶►◆◇■□●○✔✓]+\s*")
# "3. 정서적 결핍: ..." — a numbered list item set in display type.
NUMBERED_ITEM_RE = re.compile(r"^\d{1,3}\.\s+\S")
# "Chapter 2. 권력은 ..." / "Chapter 1 • ..." — a chapter reference with its
# title on the same line (TOC entry, endnote sub-heading): a sub-heading.
CHAPTER_REF_RE = re.compile(
    r"^(?:chapter|part|제?\s*\d+\s*장)\s*\d*\s*[.•·:–-]", re.IGNORECASE
)


def _page_geometry(chunks: list[dict]) -> tuple[float, float] | None:
    """(page centre x, page width) estimated from every bbox on the page."""
    xs0 = [float(c["bbox"][0]) for c in chunks if c.get("bbox")]
    xs1 = [float(c["bbox"][2]) for c in chunks if c.get("bbox")]
    if not xs0:
        return None
    left, right = min(xs0), max(xs1)
    if right - left < 1:
        return None
    return (left + right) / 2.0, right - left


def classify_heading(
    text: str,
    bbox: list[float] | None,
    geometry: tuple[float, float] | None,
    *,
    after_figure: bool = False,
) -> str | None:
    """Section type for a SectionHeader chunk, or None to drop it."""
    from core.section_normalize import chapter_marker_in_text

    if not text or ORNAMENT_RE.match(text) or DIGITS_RE.match(text):
        return None
    if COLUMN_LABEL_RE.match(text):
        return None  # "C O L U M N" box label: a design element, the box title follows
    if RUNNING_HEAD_RE.match(text):
        return "header"
    if TOC_ENTRY_RE.search(text) and not chapter_marker_in_text(text):
        return "body"  # "1.1 인공지능이란? 016": a contents line, not a heading
    if chapter_marker_in_text(text):
        return "title"
    m = SECTION_NUMBER_RE.match(text)
    if m:
        # "4.3 제목" is a section, "4.3.1 제목" (and deeper) a sub-section,
        # wherever it sits (a numbered heading right under a figure is no caption).
        return "section_title" if m.group(1).count(".") == 1 else "subtitle"
    if after_figure:
        return "caption"
    if NUMBERED_ITEM_RE.match(text):
        return "body"
    if CHAPTER_REF_RE.match(text):
        return "subtitle"
    if bbox and geometry:
        x0, _, x1, _ = (float(v) for v in bbox[:4])
        center, width = geometry
        if (x1 - x0) >= HEADING_FULL_WIDTH_RATIO * width:
            return "body"
        if abs((x0 + x1) / 2.0 - center) <= HEADING_CENTER_TOLERANCE * width:
            return "section_title"
        return "subtitle"
    return "section_title"


#: Smaller images are decorations (bullets, rules), not figures.
MIN_FIGURE_PX = 64
ASSETS_DIRNAME = "assets"


def harvest_images(chunk: dict, assets_dir: Path | None) -> list[str]:
    """Save the images carried by a chunk; return their paths relative to the
    Markdown file (``assets/<sha1>.jpg``).

    Every chunk is checked, not only Picture blocks: a cover illustration can
    arrive embedded in a SectionHeader. Ids are content hashes because
    Datalab's file names are layout-based and collide between pages. When the
    chunk comes from a stored ``blocks_raw`` the field is already a list of
    saved paths and is returned as is."""
    images = chunk.get("images")
    if not images:
        return []
    if isinstance(images, list):
        return [str(p) for p in images]
    if assets_dir is None:
        return []
    from PIL import Image

    out: list[str] = []
    for _name, b64 in images.items():
        try:
            data = base64.b64decode(b64)
            with Image.open(io.BytesIO(data)) as im:
                w, h = im.size
                fmt = (im.format or "").lower()
        except Exception:
            continue
        if min(w, h) < MIN_FIGURE_PX:
            continue
        ext = "png" if fmt == "png" else "jpg"
        name = f"{hashlib.sha1(data).hexdigest()[:16]}.{ext}"
        assets_dir.mkdir(parents=True, exist_ok=True)
        target = assets_dir / name
        if not target.exists():
            target.write_bytes(data)
        out.append(f"{ASSETS_DIRNAME}/{name}")
    return out


def _figure_sections(paths: list[str], alt: str = "") -> list[dict[str, str]]:
    """One ``figure`` section per saved image. The alt text stays a plain
    label: what Datalab puts in the Picture block is a description the model
    wrote, not text printed on the page."""
    return [{"type": "figure", "text": f"![그림]({p})"} for p in paths]


def chunks_to_sections(
    chunks: list[dict], assets_dir: Path | None = None
) -> list[dict[str, str]]:
    """Map Datalab chunks onto this repo's OCR section list."""
    from core.section_normalize import chapter_marker_in_text

    sections: list[dict[str, str]] = []
    geometry = _page_geometry(chunks)
    prev_type = ""
    pending_number = ""  # "4.8" seen on its own, waiting for its title
    chapter_title_pending = False  # "01" label emitted; the next heading is the chapter title
    for i, chunk in enumerate(chunks):
        block_type = str(chunk.get("block_type") or "")
        html = str(chunk.get("html") or "")
        # Figure data is kept even when the block's text is dropped.
        paths = harvest_images(chunk, assets_dir)
        if paths:
            alt = html_to_text(html) if block_type in DROP_TYPES else ""
            sections.extend(_figure_sections(paths, alt))
        if block_type in ("PageHeader", "SectionHeader"):
            bare = html_to_text(html).strip()
            if BARE_SECTION_NUMBER_RE.match(bare):
                pending_number = bare
                prev_type = block_type
                continue
            if CHAPTER_NUMBER_LABEL_RE.match(bare) and _opens_chapter(chunks, i, sections, geometry):
                # "01" set large over the chapter title (either block may be
                # tagged PageHeader by the layout model): the chapter label.
                sections.append({"type": "title", "text": f"{int(bare)}장"})
                chapter_title_pending = True
                prev_type = block_type
                continue
            if chapter_title_pending and block_type == "PageHeader":
                text = bare.replace("\n", " ")
                sections.append({"type": "title", "text": text})
                chapter_title_pending = False
                prev_type = block_type
                continue
        chapter_title_pending = False
        if block_type in DROP_TYPES:
            prev_type = block_type
            continue
        if block_type == "SectionHeader":
            text = html_to_text(html).replace("\n", " ").strip()
            text = re.sub(r"^[•●▪■◆◇○\-–—]+\s*", "", text)
            if RUNNING_HEAD_RE.match(text):
                sections.append({"type": "header", "text": text})
                prev_type = block_type
                continue  # the pending section number waits for the real title
            if pending_number and not SECTION_NUMBER_RE.match(text):
                text = f"{pending_number} {text}"
            pending_number = ""
            kind = classify_heading(
                text, chunk.get("bbox"), geometry,
                after_figure=prev_type in DROP_TYPES or bool(chunk.get("images")),
            )
            if kind is not None:
                if (
                    kind != "title"
                    and sections
                    and sections[-1]["type"] == "title"
                    and chapter_marker_in_text(sections[-1]["text"])
                ):
                    kind = "title"  # the heading right after a "N장" label is the chapter title
                sections.append({"type": kind, "text": text})
            prev_type = block_type
            continue
        section_type = TYPE_MAP.get(block_type, "body")
        if section_type == "body" and PRE_RE.match(html):
            section_type = "code"  # code listings arrive as Text wrapped in <pre>
        elif section_type == "body" and RUNNING_HEAD_RE.match(html_to_text(html).strip()):
            section_type = "header"  # running head tagged as Text
        if section_type == "table":
            text = table_text(html)
        elif section_type == "equation":
            text = equation_text(html)
        elif section_type == "code":
            text = code_text(html)
        else:
            text = html_to_text(html)
        if section_type == "caption":
            text = CAPTION_MARK_RE.sub("", text)
        if text and not (section_type == "body" and ORNAMENT_RE.match(text)):
            sections.append({"type": section_type, "text": text})
        prev_type = block_type
    return _demote_stray_chapter_labels(sections)


#: A chapter number / title set in display type is at least this tall,
#: relative to the page width (page numbers in the running head are ~0.03).
CHAPTER_LABEL_MIN_HEIGHT_RATIO = 0.045


def _is_display_size(chunk: dict, geometry: tuple[float, float] | None) -> bool | None:
    """True/False when the block's height can be compared to the page width, None otherwise."""
    bbox = chunk.get("bbox")
    if not bbox or not geometry:
        return None
    _, width = geometry
    return (float(bbox[3]) - float(bbox[1])) >= CHAPTER_LABEL_MIN_HEIGHT_RATIO * width


def _opens_chapter(
    chunks: list[dict],
    i: int,
    sections: list[dict[str, str]],
    geometry: tuple[float, float] | None,
) -> bool:
    """True when the bare number at ``chunks[i]`` is a chapter label: set in
    display size, leading the page (only running heads / figures before it),
    with the chapter title — a heading, or another display-size block — next.
    A page number in the running head is small and fails the size test."""
    big = _is_display_size(chunks[i], geometry)
    if big is False or (big is None and not H_TAG_RE.search(str(chunks[i].get("html") or ""))):
        return False
    if any(s["type"] not in ("header", "page_number", "figure") for s in sections):
        return False
    if i + 1 >= len(chunks):
        return False
    nxt_chunk = chunks[i + 1]
    kind = nxt_chunk.get("block_type")
    if kind == "PageHeader":
        if not _is_display_size(nxt_chunk, geometry):
            return False
    elif kind != "SectionHeader":
        return False
    nxt = html_to_text(str(nxt_chunk.get("html") or "")).replace("\n", " ").strip()
    if not nxt or DIGITS_RE.match(nxt) or ORNAMENT_RE.match(nxt):
        return False
    if SECTION_NUMBER_RE.match(nxt) or RUNNING_HEAD_RE.match(nxt) or TOC_ENTRY_RE.search(nxt):
        return False
    return True


def _demote_stray_chapter_labels(sections: list[dict[str, str]]) -> list[dict[str, str]]:
    """A bare "N장" title is a chapter opener only when the chapter title
    follows it. On its own (a screenshot label in the front matter, a cross
    reference set large) it is plain text."""
    from core.section_normalize import chapter_marker_in_text

    out = list(sections)
    for i, sec in enumerate(out):
        if sec["type"] != "title" or not chapter_marker_in_text(sec["text"]):
            continue
        nxt = out[i + 1] if i + 1 < len(out) else None
        # Last block on the page: the title may sit on the next page (a label
        # alone on a part-opening page), so it is left as it is.
        if nxt is not None and nxt["type"] != "title":
            out[i] = {"type": "body", "text": sec["text"]}
    return out


def rebuild_page_structure(page: dict[str, Any]) -> dict[str, Any]:
    """Re-derive ``sections``/``text`` from the stored ``blocks_raw`` (bbox kept),
    so classification fixes apply to existing ``.ocr.json`` without re-OCR."""
    chunks = page.get("blocks_raw") or []
    sections = chunks_to_sections(chunks)
    out = dict(page)
    out["sections"] = sections
    out["text"] = sections_to_text(sections)
    return out


def _strip_images(chunks: list[dict], assets_dir: Path | None = None) -> list[dict[str, Any]]:
    """Raw chunks kept for rebuilds, with image payloads replaced by the
    paths of the files ``harvest_images`` saved (so a rebuild needs no API)."""
    kept: list[dict[str, Any]] = []
    for chunk in chunks:
        item: dict[str, Any] = {
            "block_type": chunk.get("block_type"),
            "html": chunk.get("html"),
            "bbox": chunk.get("bbox"),
            "page": chunk.get("page"),
        }
        paths = harvest_images(chunk, assets_dir)
        if paths:
            item["images"] = paths
        kept.append(item)
    return kept


def sections_to_text(sections: list[dict[str, str]]) -> str:
    """Plain page text: content sections joined by blank lines (no chrome)."""
    parts = [s["text"] for s in sections if s["type"] not in {"header", "page_number"}]
    return "\n\n".join(parts).strip()


def chunks_to_page_structure(
    chunks: list[dict], page_num: int, assets_dir: Path | None = None
) -> dict[str, Any]:
    sections = chunks_to_sections(chunks, assets_dir)
    return {
        "page": int(page_num),
        "text": sections_to_text(sections),
        "sections": sections,
        "engine": ENGINE_NAME,
        "blocks_raw": _strip_images(chunks, assets_dir),
    }


# ── entry points (same shape as core.google_ocr) ──────────────────────────
def extract_page_structure_from_image(
    image_path: Path | str,
    *,
    page_num: int = 1,
    mode: str = DEFAULT_MODE,
    api_key: str | None = None,
    spend: Spend | None = None,
    timeout_s: int = 300,
    assets_dir: Path | str | None = None,
) -> dict[str, Any]:
    path = Path(image_path)
    key = find_key(api_key)
    if not key:
        raise RuntimeError(
            "DATALAB_API_KEY is not set (environment or .env; https://www.datalab.to)"
        )
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    try:
        chunks = read_bytes(
            path.read_bytes(), path.name, mime, key, mode=mode, spend=spend, timeout_s=timeout_s
        )
    except DatalabError as exc:
        raise RuntimeError(f"Datalab OCR failed: {exc}") from exc
    except Exception as exc:  # httpx errors
        raise RuntimeError(f"Datalab OCR API call failed: {exc}") from exc
    return chunks_to_page_structure(
        chunks, page_num, Path(assets_dir) if assets_dir else None
    )


def extract_page_structure_from_pdf_page(
    pdf_path: Path | str,
    page_index: int,
    *,
    page_num: int = 1,
    mode: str = DEFAULT_MODE,
    api_key: str | None = None,
    spend: Spend | None = None,
    timeout_s: int = 300,
    assets_dir: Path | str | None = None,
) -> dict[str, Any]:
    """OCR one page of a PDF (0-based ``page_index``) by sending a one-page PDF."""
    from core.pdf_input import extract_pdf_page_bytes

    key = find_key(api_key)
    if not key:
        raise RuntimeError(
            "DATALAB_API_KEY is not set (environment or .env; https://www.datalab.to)"
        )
    data = extract_pdf_page_bytes(pdf_path, page_index)
    try:
        chunks = read_bytes(
            data,
            f"{Path(pdf_path).stem}_p{page_num:04d}.pdf",
            "application/pdf",
            key,
            mode=mode,
            spend=spend,
            timeout_s=timeout_s,
        )
    except DatalabError as exc:
        raise RuntimeError(f"Datalab OCR failed: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Datalab OCR API call failed: {exc}") from exc
    return chunks_to_page_structure(
        chunks, page_num, Path(assets_dir) if assets_dir else None
    )
