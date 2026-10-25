"""Tests for section normalization and chapter detection rules."""

from __future__ import annotations

from core.ocr_json_loader import SectionBlock
from core.section_normalize import (
    is_backmatter_start_page,
    is_chapter_start_page,
    prepare_page_sections,
)


def test_section_number_plus_title_becomes_section_title() -> None:
    raw = [
        SectionBlock(type="page_number", text="03."),
        SectionBlock(type="title", text="노광 잔혹사: 패턴 그리기의 어려움"),
        SectionBlock(type="other", text="간략한 노광의 역사"),
        SectionBlock(type="body", text="본문 시작"),
    ]
    prepared = prepare_page_sections(raw)
    assert prepared[0].type == "section_title"
    assert prepared[0].text.startswith("03.")
    assert prepared[1].type == "subtitle"
    assert prepared[2].type == "body"


def test_chapter_label_header_promotes_to_chapter_start() -> None:
    from core.section_normalize import promote_chapter_label_header

    raw = [
        SectionBlock(type="header", text="Chapter 2"),
        SectionBlock(type="title", text="권력은\n어디에서 오는가"),
        SectionBlock(type="body", text="본문"),
    ]
    promoted = promote_chapter_label_header(raw)
    assert [s.type for s in promoted] == ["title", "title", "body"]
    assert is_chapter_start_page(promoted)
    # A plain running header is left alone.
    plain = [SectionBlock(type="header", text="권력중독"), SectionBlock(type="title", text="x")]
    assert promote_chapter_label_header(plain) == plain


def test_backmatter_header_promotes_and_repeats_do_not_split() -> None:
    from core.book_structure import build_book_structure
    from core.ocr_json_loader import PageRecord
    from core.section_normalize import promote_chapter_label_header

    raw = [SectionBlock(type="header", text="주"), SectionBlock(type="subtitle", text="서문"),
           SectionBlock(type="body", text="1 철학적 관점")]
    promoted = promote_chapter_label_header(raw)
    assert promoted[0].type == "title" and is_backmatter_start_page(promoted)
    pages = [
        PageRecord(1, [SectionBlock("title", "1장"), SectionBlock("title", "시작"), SectionBlock("body", "본문.")]),
        PageRecord(2, [SectionBlock("header", "참고문헌"), SectionBlock("body", "A (2020).")]),
        PageRecord(3, [SectionBlock("header", "참고문헌"), SectionBlock("body", "B (2021).")]),
    ]
    structure = build_book_structure("책", pages)
    assert [(c.kind, c.start_page, c.end_page) for c in structure.chapters] == [
        ("chapter", 1, 1), ("back_matter", 2, 3)]
    # The chapter title is not repeated as a section heading inside the chapter.
    assert [b.text for b in structure.chapters[0].blocks] == ["본문."]


def test_book_without_chapter_markers_is_one_chapter_not_front_matter() -> None:
    from core.book_structure import build_book_structure
    from core.ocr_json_loader import PageRecord

    pages = [PageRecord(1, [SectionBlock("section_title", "4.1 머신 러닝이란?"), SectionBlock("body", "본문.")]),
             PageRecord(2, [SectionBlock("body", "계속.")])]
    s = build_book_structure("4장", pages)
    assert [(c.kind, c.heading) for c in s.chapters] == [("chapter", "4장")]


def test_toc_page_with_many_labels_is_not_chapter_start() -> None:
    raw = [
        SectionBlock(type="title", text="1장"),
        SectionBlock(type="title", text="2장"),
        SectionBlock(type="body", text="목차"),
    ]
    assert not is_chapter_start_page(raw)
    raw2 = [SectionBlock(type="title", text="Chapter 9 • 사회를 위한 제안")]
    assert not is_chapter_start_page(raw2)
    raw3 = [SectionBlock(type="title", text="PART 1"), SectionBlock(type="title", text="우리는 왜")]
    assert is_chapter_start_page(raw3)


def test_chapter_page_only_n_jang() -> None:
    raw = [
        SectionBlock(type="title", text="2장"),
        SectionBlock(type="title", text="미세화의 진척과\n반도체 제조의 고민"),
    ]
    prepared = prepare_page_sections(raw)
    assert is_chapter_start_page(prepared)
    assert not is_backmatter_start_page(prepared)


def test_inline_title_is_not_chapter() -> None:
    raw = [
        SectionBlock(type="section_title", text="노광 잔혹사: 패턴 그리기의 어려움"),
        SectionBlock(type="body", text="본문"),
    ]
    prepared = prepare_page_sections(raw)
    assert not is_chapter_start_page(prepared)


def test_backmatter_conclusion() -> None:
    raw = [
        SectionBlock(type="title", text="결론"),
        SectionBlock(type="body", text="마치며"),
    ]
    prepared = prepare_page_sections(raw)
    assert is_backmatter_start_page(prepared)
    assert not is_chapter_start_page(prepared)
