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
H_TAG_RE = re.compile(r"<h([1-6])")
# Marker wraps LaTeX in <math> (not MathML). Strip tags *after* converting it
# or the delimiters vanish and ``\Delta e`` ends up as prose.
MATH_RE = re.compile(r"<math\b[^>]*>(.*?)</math>", re.I | re.S)
LI_RE = re.compile(r"<li\b[^>]*>", re.I)
BR_RE = re.compile(r"<br\s*/?>|</p>|</div>|</tr>", re.I)
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
SUP_RE = re.compile(r"<sup\b[^>]*>(.*?)</sup>", re.I | re.S)


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
LIST_ORDERED_RE = re.compile(r"^- (\d{1,3})(?:[.)]\s*|\s+)(?=\S)")


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
        body = unescape(HTML_TAG_RE.sub("", m.group(1))).strip()
        return f"${body}$" if body else ""

    text = MATH_RE.sub(keep_math, html)
    text = IMG_TAG_RE.sub("", text)
    # Footnote reference numbers (<sup>3</sup>) are dropped: the reader-side
    # superscript has no anchor in Markdown and only litters sentence ends.
    text = SUP_RE.sub("", text)
    text = LI_RE.sub("\n- ", text)
    text = BR_RE.sub("\n", text)
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
    bodies = [unescape(HTML_TAG_RE.sub("", b)).strip() for b in MATH_RE.findall(html)]
    body = " ".join(b for b in bodies if b) or unescape(HTML_TAG_RE.sub("", html)).strip()
    body = re.sub(r"\s+", " ", body)
    return f"$${body}$$" if body else ""


def table_text(html: str) -> str:
    """Tables keep their HTML: structure is the content. Images are dropped."""
    html = IMG_TAG_RE.sub("", html)
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
    if chapter_marker_in_text(text):
        return "title"
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


def chunks_to_sections(chunks: list[dict]) -> list[dict[str, str]]:
    """Map Datalab chunks onto this repo's OCR section list."""
    sections: list[dict[str, str]] = []
    geometry = _page_geometry(chunks)
    prev_type = ""
    for chunk in chunks:
        block_type = str(chunk.get("block_type") or "")
        html = str(chunk.get("html") or "")
        if block_type in DROP_TYPES:
            prev_type = block_type
            continue
        if block_type == "SectionHeader":
            text = html_to_text(html).replace("\n", " ").strip()
            text = re.sub(r"^[•●▪■◆◇○\-–—]+\s*", "", text)
            kind = classify_heading(
                text, chunk.get("bbox"), geometry,
                after_figure=prev_type in DROP_TYPES or bool(chunk.get("images")),
            )
            if kind is not None:
                sections.append({"type": kind, "text": text})
            prev_type = block_type
            continue
        section_type = TYPE_MAP.get(block_type, "body")
        if section_type == "table":
            text = table_text(html)
        elif section_type == "equation":
            text = equation_text(html)
        elif section_type == "code":
            text = code_text(html)
        else:
            text = html_to_text(html)
        if text and not (section_type == "body" and ORNAMENT_RE.match(text)):
            sections.append({"type": section_type, "text": text})
        prev_type = block_type
    return sections


def rebuild_page_structure(page: dict[str, Any]) -> dict[str, Any]:
    """Re-derive ``sections``/``text`` from the stored ``blocks_raw`` (bbox kept),
    so classification fixes apply to existing ``.ocr.json`` without re-OCR."""
    chunks = page.get("blocks_raw") or []
    sections = chunks_to_sections(chunks)
    out = dict(page)
    out["sections"] = sections
    out["text"] = sections_to_text(sections)
    return out


def _strip_images(chunks: list[dict]) -> list[dict[str, Any]]:
    """Raw chunks kept for debugging, minus the base64 image payloads."""
    kept: list[dict[str, Any]] = []
    for chunk in chunks:
        kept.append(
            {
                "block_type": chunk.get("block_type"),
                "html": chunk.get("html"),
                "bbox": chunk.get("bbox"),
                "page": chunk.get("page"),
            }
        )
    return kept


def sections_to_text(sections: list[dict[str, str]]) -> str:
    """Plain page text: content sections joined by blank lines (no chrome)."""
    parts = [s["text"] for s in sections if s["type"] not in {"header", "page_number"}]
    return "\n\n".join(parts).strip()


def chunks_to_page_structure(chunks: list[dict], page_num: int) -> dict[str, Any]:
    sections = chunks_to_sections(chunks)
    return {
        "page": int(page_num),
        "text": sections_to_text(sections),
        "sections": sections,
        "engine": ENGINE_NAME,
        "blocks_raw": _strip_images(chunks),
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
    return chunks_to_page_structure(chunks, page_num)


def extract_page_structure_from_pdf_page(
    pdf_path: Path | str,
    page_index: int,
    *,
    page_num: int = 1,
    mode: str = DEFAULT_MODE,
    api_key: str | None = None,
    spend: Spend | None = None,
    timeout_s: int = 300,
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
    return chunks_to_page_structure(chunks, page_num)
