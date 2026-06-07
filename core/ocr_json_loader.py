"""Load per-page structured OCR JSON files from a book tmp directory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_SECTION_TYPES = frozenset({"header", "page_number"})


@dataclass
class SectionBlock:
    type: str
    text: str


@dataclass
class PageRecord:
    page_num: int
    sections: list[SectionBlock] = field(default_factory=list)

    def content_sections(self) -> list[SectionBlock]:
        return [s for s in self.sections if s.type not in SKIP_SECTION_TYPES]

    def has_text(self) -> bool:
        return any(s.text.strip() for s in self.content_sections())


def _parse_page_num(path: Path, title: str) -> int | None:
    pattern = re.compile(rf"^{re.escape(title)}_(\d+)\.ocr\.json$")
    match = pattern.match(path.name)
    if not match:
        return None
    return int(match.group(1))


def _load_one_page(path: Path, page_num: int) -> PageRecord:
    raw = json.loads(path.read_text(encoding="utf-8"))
    sections: list[SectionBlock] = []
    if isinstance(raw, dict):
        for item in raw.get("sections", []):
            if not isinstance(item, dict):
                continue
            section_type = str(item.get("type", "body")).strip().lower() or "body"
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            sections.append(SectionBlock(type=section_type, text=text))
    return PageRecord(page_num=page_num, sections=sections)


def load_ocr_pages(tmp_dir: Path | str, title: str) -> list[PageRecord]:
    """Load and sort all ``{title}_NNNN.ocr.json`` files under tmp_dir."""
    root = Path(tmp_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"OCR tmp directory not found: {root}")

    pages: list[PageRecord] = []
    for path in root.glob(f"{title}_*.ocr.json"):
        page_num = _parse_page_num(path, title)
        if page_num is None:
            continue
        pages.append(_load_one_page(path, page_num))
    pages.sort(key=lambda p: p.page_num)
    if not pages:
        raise FileNotFoundError(
            f"No OCR JSON files matching {title}_NNNN.ocr.json in {root}"
        )
    return pages
