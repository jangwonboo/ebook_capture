"""Detect chapter boundaries and build a book outline from OCR pages."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from core.ocr_json_loader import PageRecord, SectionBlock
from core.section_normalize import (
    backmatter_heading_from_page,
    combine_chapter_titles,
    is_backmatter_heading,
    is_backmatter_start_page,
    is_chapter_start_page,
    leading_titles,
    prepare_page_sections,
)

CHAPTER_KIND = "chapter"
FRONT_MATTER_KIND = "front_matter"
BACK_MATTER_KIND = "back_matter"


@dataclass
class ContentBlock:
    section_type: str
    text: str
    page_num: int


@dataclass
class ChapterDoc:
    heading: str
    slug: str
    start_page: int
    end_page: int
    kind: str = CHAPTER_KIND
    blocks: list[ContentBlock] = field(default_factory=list)


@dataclass
class BookStructure:
    title: str
    chapters: list[ChapterDoc] = field(default_factory=list)

    @property
    def page_range(self) -> tuple[int, int] | None:
        if not self.chapters:
            return None
        return self.chapters[0].start_page, self.chapters[-1].end_page


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.strip().lower())
    slug = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug or "section"


def _content_after_chapter_headings(sections: list[SectionBlock]) -> list[SectionBlock]:
    _, rest = leading_titles(sections)
    return rest


def _content_after_backmatter_heading(sections: list[SectionBlock]) -> list[SectionBlock]:
    if sections and sections[0].type in {"title", "section_title"}:
        if is_backmatter_heading(sections[0].text):
            return sections[1:]
    return sections


def _append_prepared_blocks(
    chapter: ChapterDoc,
    page_num: int,
    sections: list[SectionBlock],
) -> None:
    for section in sections:
        chapter.blocks.append(
            ContentBlock(
                section_type=section.type,
                text=section.text,
                page_num=page_num,
            )
        )


def _flush_chapter(
    chapters: list[ChapterDoc],
    chapter: ChapterDoc | None,
    end_page: int,
) -> None:
    if chapter is None:
        return
    chapter.end_page = end_page
    chapters.append(chapter)


def build_book_structure(title: str, pages: list[PageRecord]) -> BookStructure:
    """Group OCR pages into chapters using ``N장`` markers and back-matter headings."""
    chapters: list[ChapterDoc] = []
    front_matter = ChapterDoc(
        heading="Front matter",
        slug="front-matter",
        start_page=pages[0].page_num if pages else 1,
        end_page=pages[0].page_num if pages else 1,
        kind=FRONT_MATTER_KIND,
    )
    current: ChapterDoc | None = None
    front_matter_inserted = False

    for page in pages:
        raw_sections = page.sections
        prepared = prepare_page_sections(raw_sections)
        if not prepared:
            continue

        if is_chapter_start_page(raw_sections):
            titles, _ = leading_titles(raw_sections)
            heading = combine_chapter_titles(titles)
            if current is not None:
                _flush_chapter(chapters, current, page.page_num - 1)
            elif front_matter.blocks and not front_matter_inserted:
                front_matter.end_page = page.page_num - 1
                chapters.append(front_matter)
                front_matter_inserted = True
            current = ChapterDoc(
                heading=heading,
                slug=slugify(heading),
                start_page=page.page_num,
                end_page=page.page_num,
                kind=CHAPTER_KIND,
            )
            _append_prepared_blocks(
                current,
                page.page_num,
                _content_after_chapter_headings(prepared),
            )
            continue

        if is_backmatter_start_page(raw_sections):
            if current is not None:
                _flush_chapter(chapters, current, page.page_num - 1)
                current = None
            elif front_matter.blocks and not front_matter_inserted:
                front_matter.end_page = page.page_num - 1
                chapters.append(front_matter)
                front_matter_inserted = True
            heading = backmatter_heading_from_page(raw_sections)
            current = ChapterDoc(
                heading=heading,
                slug=slugify(heading),
                start_page=page.page_num,
                end_page=page.page_num,
                kind=BACK_MATTER_KIND,
            )
            _append_prepared_blocks(
                current,
                page.page_num,
                _content_after_backmatter_heading(prepared),
            )
            continue

        if current is None:
            _append_prepared_blocks(front_matter, page.page_num, prepared)
            front_matter.end_page = page.page_num
            continue

        current.end_page = page.page_num
        _append_prepared_blocks(current, page.page_num, prepared)

    if current is not None:
        chapters.append(current)
    elif front_matter.blocks and not front_matter_inserted:
        chapters.append(front_matter)

    if not chapters:
        all_blocks: list[ContentBlock] = []
        for page in pages:
            prepared = prepare_page_sections(page.sections)
            for section in prepared:
                all_blocks.append(
                    ContentBlock(
                        section_type=section.type,
                        text=section.text,
                        page_num=page.page_num,
                    )
                )
        if all_blocks:
            chapters.append(
                ChapterDoc(
                    heading=title,
                    slug=slugify(title),
                    start_page=pages[0].page_num,
                    end_page=pages[-1].page_num,
                    kind=CHAPTER_KIND,
                    blocks=all_blocks,
                )
            )

    return BookStructure(title=title, chapters=chapters)


def structure_to_mapping(structure: BookStructure) -> dict:
    page_range = structure.page_range
    return {
        "title": structure.title,
        "page_range": list(page_range) if page_range else [],
        "chapters": [
            {
                "heading": ch.heading,
                "slug": ch.slug,
                "kind": ch.kind,
                "start_page": ch.start_page,
                "end_page": ch.end_page,
                "block_count": len(ch.blocks),
            }
            for ch in structure.chapters
        ],
    }
