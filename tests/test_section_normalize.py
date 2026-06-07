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
