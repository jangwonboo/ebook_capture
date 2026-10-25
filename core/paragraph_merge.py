"""Merge body paragraphs split across consecutive OCR pages."""

from __future__ import annotations

import re

from core.ocr_json_loader import SKIP_SECTION_TYPES, PageRecord, SectionBlock

_KO_CONTINUATION_PREFIXES = (
    "로는 ",
    "로 ",
    "는 ",
    "은 ",
    "이 ",
    "가 ",
    "을 ",
    "를 ",
    "에 ",
    "의 ",
    "와 ",
    "과 ",
    "도 ",
    "만 ",
    "에서 ",
    "으로 ",
    "까지 ",
    "부터 ",
    "하여 ",
    "하면 ",
)

_KO_CONTINUATION_START_RE = re.compile(
    r"^(로[는은]?|[은는이가을를에의와과도만])"
)

_SENTENCE_ENDINGS = (
    ".",
    "!",
    "?",
    "…",
    "다.",
    "요.",
    "니다.",
    "음.",
    "람.",
    "함.",
    "됨.",
    '."',
    ".'",
)


_TRAILING_FOOTNOTE_RE = re.compile(r"(?:\s*\^[^^\s]{1,6}\^)+\s*$")

# Within one page, a body block this short with no sentence ending is a
# label / TOC line / caption fragment, not the tail of a wrapped paragraph.
_MIN_MERGE_PREV_CHARS = 40


def paragraph_ends(text: str) -> bool:
    # Footnote markers (``보았다.^6^``) sit after the period; ignore them.
    stripped = _TRAILING_FOOTNOTE_RE.sub("", text.rstrip()).rstrip()
    if not stripped:
        return True
    for ending in _SENTENCE_ENDINGS:
        if stripped.endswith(ending):
            return True
    return False


def looks_like_new_paragraph(text: str) -> bool:
    """True when text clearly starts a new block (list item, diagram label, etc.)."""
    stripped = text.strip()
    if not stripped:
        return True
    if re.match(r"^\d+[\).]\s", stripped):
        return True
    if re.match(r"^[•·∙●○◦\-]\s", stripped):
        return True
    if re.match(r"^[A-Z0-9]{2,}\s*$", stripped):
        return True
    if re.match(r"^[A-Z][A-Z0-9\s\-]{4,}$", stripped):
        return True
    return False


def looks_like_continuation(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first = stripped[0]
    if first in ")]}\"'”’":
        return True
    if first.isascii() and first.islower():
        return True
    if _KO_CONTINUATION_START_RE.match(stripped):
        return True
    for prefix in _KO_CONTINUATION_PREFIXES:
        if stripped.startswith(prefix):
            return True
    if re.match(r"^[0-9]+[\).]", stripped):
        return False
    if re.match(r"^[가-힣]{1,2}[,.]", stripped):
        return True
    return False


def _both_short(prev: SectionBlock, nxt: SectionBlock) -> bool:
    """Two short lines are list / TOC entries, not one paragraph split in two,
    unless the first one ends mid-phrase (particle, comma, ``밖에`` ...) —
    a real page break ("고작 1억분의 1의 계산밖에" | "하지 못하는 수준이다")
    leaves such a dangling tail, a TOC line ("위계의 장점") does not."""
    from core.text_reflow import _ends_with_space_joiner

    if len(prev.text.strip()) >= _MIN_MERGE_PREV_CHARS:
        return False
    if len(nxt.text.strip()) >= _MIN_MERGE_PREV_CHARS:
        return False
    if looks_like_continuation(nxt.text):
        return False
    return not _ends_with_space_joiner(prev.text)


def _should_merge_bodies(prev: SectionBlock, nxt: SectionBlock) -> bool:
    if prev.type != "body" or nxt.type != "body":
        return False
    if paragraph_ends(prev.text):
        return False
    if looks_like_new_paragraph(nxt.text):
        return False
    if _both_short(prev, nxt):
        return False
    return True


def _merge_two_body(prev: SectionBlock, nxt: SectionBlock) -> SectionBlock:
    from core.text_reflow import join_wrapped_lines

    merged = join_wrapped_lines(prev.text.rstrip(), nxt.text.lstrip())
    return SectionBlock(type="body", text=merged)


def merge_within_page_paragraphs(page: PageRecord) -> PageRecord:
    """Join consecutive body sections split by OCR on the same page."""
    merged: list[SectionBlock] = []
    for sec in page.sections:
        if merged and _should_merge_bodies(merged[-1], sec):
            merged[-1] = _merge_two_body(merged[-1], sec)
        else:
            merged.append(sec)
    return PageRecord(page_num=page.page_num, sections=merged)


def merge_cross_page_paragraphs(pages: list[PageRecord]) -> list[PageRecord]:
    """Join body sections when a page break clearly splits one paragraph."""
    if not pages:
        return []

    merged_pages: list[PageRecord] = []
    carry: SectionBlock | None = None

    for page in pages:
        sections = list(page.content_sections())
        if carry is not None:
            if sections and sections[0].type == "body":
                sections[0] = _merge_two_body(carry, sections[0])
                carry = None
            else:
                if merged_pages:
                    merged_pages[-1].sections.append(carry)
                else:
                    merged_pages.append(
                        PageRecord(page_num=page.page_num, sections=[carry])
                    )
                carry = None

        if (
            merged_pages
            and sections
            and sections[0].type == "body"
            and merged_pages[-1].sections
            and _should_merge_bodies(merged_pages[-1].sections[-1], sections[0])
        ):
            last_page = merged_pages[-1]
            last_body = last_page.sections[-1]
            last_page.sections[-1] = _merge_two_body(last_body, sections[0])
            sections = sections[1:]
            if not sections:
                continue
            page = PageRecord(page_num=page.page_num, sections=sections)

        if sections:
            merged_pages.append(page)

    if carry is not None and merged_pages:
        merged_pages[-1].sections.append(carry)

    return merged_pages


_FENCE_RE = re.compile(r"^```[^\n]*\n?|\n?```\s*$")


def _unfence(text: str) -> str:
    return _FENCE_RE.sub("", text).strip("\n")


def _merge_two_code(prev: SectionBlock, nxt: SectionBlock) -> SectionBlock:
    a, b = _unfence(prev.text), _unfence(nxt.text)
    body = f"{a}\n{b}" if a and b else a or b
    return SectionBlock(type="code", text=f"```\n{body}\n```")


def merge_code_blocks(pages: list[PageRecord]) -> list[PageRecord]:
    """Join code blocks that follow each other with nothing but running
    heads / page numbers between them — one listing that the layout engine
    cut at a page break or into one block per visual line group. Only the
    fence is removed at the seam; the lines themselves are left as OCR gave
    them."""
    out: list[PageRecord] = []
    last_code: SectionBlock | None = None  # trailing code block of the previous page
    last_page: PageRecord | None = None
    for page in pages:
        sections: list[SectionBlock] = []
        for sec in page.sections:
            if sec.type in SKIP_SECTION_TYPES:
                sections.append(sec)
                continue
            if sec.type == "code":
                if sections and sections[-1].type == "code":
                    sections[-1] = _merge_two_code(sections[-1], sec)
                    continue
                if last_code is not None and not any(
                    s.type not in SKIP_SECTION_TYPES for s in sections
                ):
                    # First content block of this page continues the previous page's listing.
                    merged = _merge_two_code(last_code, sec)
                    assert last_page is not None
                    last_page.sections[last_page.sections.index(last_code)] = merged
                    last_code = merged
                    continue
            last_code = None
            sections.append(sec)
        content = [s for s in sections if s.type not in SKIP_SECTION_TYPES]
        while content and content[-1].type == "footnote":
            content.pop()  # page-bottom footnotes do not end a listing
        if content and content[-1].type == "code":
            last_code = content[-1]
        elif content:
            last_code = None
        if not content and last_code is not None:
            pass  # a page of running heads only: keep waiting for the continuation
        new_page = PageRecord(page_num=page.page_num, sections=sections)
        out.append(new_page)
        if content:
            last_page = new_page
        elif last_page is None:
            last_page = new_page
    return out


def normalize_paragraphs(pages: list[PageRecord]) -> list[PageRecord]:
    """Reflow layout line breaks and merge split body paragraphs / code listings."""
    from core.text_reflow import reflow_page_sections

    reflowed = [
        PageRecord(page_num=page.page_num, sections=reflow_page_sections(page.sections))
        for page in pages
    ]
    within = [merge_within_page_paragraphs(page) for page in reflowed]
    return merge_code_blocks(merge_cross_page_paragraphs(within))
