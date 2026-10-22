"""Normalize OCR sections for book assembly (section numbers, headings)."""

from __future__ import annotations

import re

from core.ocr_json_loader import SectionBlock

# A chapter *label* on its own line: "2장", "제2장", "Chapter 2", "PART 1", "2부".
# Labels followed by a title on the same line ("Chapter 9 • 제안") are TOC
# entries, not chapter starts, and deliberately do not match.
CHAPTER_NUM_RE = re.compile(
    r"^(?:제\s*)?\d+\s*장$|^chapter\s+\d+$|^part\s+\d+$|^\d+\s*부$",
    re.IGNORECASE,
)
SECTION_NUM_RE = re.compile(r"^\d{1,2}\.?$")
BACKMATTER_HEADINGS = frozenset(
    {
        "결론",
        "부록",
        "참고문헌",
        "에필로그",
        "주",
        "미주",
        "후주",
        "감사의 글",
        "감사의 말",
        "옮긴이의 글",
        "옮긴이의 말",
        "역자 후기",
        "찾아보기",
        "색인",
        "appendix",
        "references",
        "bibliography",
        "epilogue",
        "notes",
        "endnotes",
        "acknowledgments",
        "acknowledgements",
        "index",
    }
)
SKIP_ASSEMBLY_TYPES = frozenset({"header", "page_number"})


def first_line(text: str) -> str:
    return text.strip().split("\n")[0].strip()


def chapter_marker_in_text(text: str) -> bool:
    return bool(CHAPTER_NUM_RE.match(first_line(text)))


def has_chapter_marker(titles: list[str]) -> bool:
    """Exactly one label among the leading titles. Two or more is a TOC page."""
    return sum(1 for t in titles if chapter_marker_in_text(t)) == 1


def promote_chapter_label_header(sections: list[SectionBlock]) -> list[SectionBlock]:
    """Layout OCR (Datalab) tags the small "Chapter N" label above a chapter
    opening as a page header. When such a header leads the page and a heading
    follows, treat both as chapter titles so the usual ``N장`` rule applies."""
    if not sections:
        return sections
    first = sections[0]
    # Back-matter opener tagged as a header ("주", "감사의 글", "참고문헌").
    if first.type in {"header", "page_number"} and is_backmatter_heading(first.text):
        return [SectionBlock(type="title", text=first_line(first.text))] + list(sections[1:])
    if len(sections) < 2:
        return sections
    second = sections[1]
    if first.type not in {"header", "page_number", "title"}:
        return sections
    if not chapter_marker_in_text(first.text):
        return sections
    if second.type not in {"title", "section_title", "subtitle"}:
        return sections
    if first.type == "title" and second.type == "title":
        return sections  # already the plain ``N장`` + title form
    promoted = [
        SectionBlock(type="title", text=first_line(first.text)),
        SectionBlock(type="title", text=second.text),
    ]
    return promoted + list(sections[2:])


def is_backmatter_heading(text: str) -> bool:
    line = first_line(text)
    lowered = line.lower()
    return lowered in BACKMATTER_HEADINGS or line in BACKMATTER_HEADINGS


def _is_subtitle(text: str, next_section: SectionBlock | None) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 60:
        return False
    if stripped.count("\n") > 1:
        return False
    if next_section is not None and next_section.type not in {"body", "figure"}:
        return False
    return True


def prepare_page_sections(sections: list[SectionBlock]) -> list[SectionBlock]:
    """Attach section numbers and downgrade inline titles to section headings."""
    prepared: list[SectionBlock] = []
    i = 0
    while i < len(sections):
        sec = sections[i]
        if sec.type in ("page_number", "header") and SECTION_NUM_RE.match(sec.text.strip()):
            num = sec.text.strip().rstrip(".")
            if i + 1 < len(sections) and sections[i + 1].type == "title":
                title_text = sections[i + 1].text.replace("\n", " ").strip()
                prepared.append(
                    SectionBlock(
                        type="section_title",
                        text=f"{num}. {title_text}",
                    )
                )
                i += 2
                continue
            i += 1
            continue

        if sec.type in ("section_title", "subtitle"):
            prepared.append(sec)
            i += 1
            continue

        if sec.type == "title":
            if chapter_marker_in_text(sec.text):
                prepared.append(sec)
            else:
                prepared.append(
                    SectionBlock(
                        type="section_title",
                        text=sec.text.replace("\n", " ").strip(),
                    )
                )
            i += 1
            continue

        if sec.type in SKIP_ASSEMBLY_TYPES:
            i += 1
            continue

        if sec.type == "other":
            nxt = sections[i + 1] if i + 1 < len(sections) else None
            if _is_subtitle(sec.text, nxt):
                prepared.append(SectionBlock(type="subtitle", text=sec.text.strip()))
                i += 1
                continue

        prepared.append(sec)
        i += 1
    return prepared


def leading_titles(sections: list[SectionBlock]) -> tuple[list[str], list[SectionBlock]]:
    titles: list[str] = []
    rest: list[SectionBlock] = []
    in_titles = True
    for section in sections:
        if in_titles and section.type == "title":
            titles.append(section.text)
            continue
        in_titles = False
        rest.append(section)
    return titles, rest


def is_chapter_start_page(sections: list[SectionBlock]) -> bool:
    titles, _ = leading_titles(sections)
    return has_chapter_marker(titles)


def is_backmatter_start_page(sections: list[SectionBlock]) -> bool:
    titles, _ = leading_titles(sections)
    if titles and is_backmatter_heading(titles[0]):
        return True
    for section in sections:
        if section.type in {"title", "section_title"} and is_backmatter_heading(section.text):
            return True
    return False


def backmatter_heading_from_page(sections: list[SectionBlock]) -> str:
    titles, _ = leading_titles(sections)
    if titles and is_backmatter_heading(titles[0]):
        return first_line(titles[0])
    for section in sections:
        if section.type in {"title", "section_title"} and is_backmatter_heading(section.text):
            return first_line(section.text)
    return "Back matter"


def combine_chapter_titles(titles: list[str]) -> str:
    parts = [t.replace("\n", " ").strip() for t in titles if t.strip()]
    if not parts:
        return "Untitled"
    if len(parts) == 1:
        return parts[0]
    if CHAPTER_NUM_RE.match(parts[0]):
        return f"{parts[0]} {parts[1]}".strip()
    return " ".join(parts)
