"""Regression tests against the real book OCR output when available."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.book_structure import BACK_MATTER_KIND, CHAPTER_KIND, build_book_structure
from core.ocr_json_loader import load_ocr_pages
from core.paragraph_merge import normalize_paragraphs

REAL_BOOK_TITLE = "AI 시대 다시 시작하는 반도체 공부"
REAL_BOOK_TMP = Path(r"E:/ebook") / REAL_BOOK_TITLE / "tmp"

EXPECTED_CHAPTERS = [
    (9, "1장 무어의 시대"),
    (49, "2장 미세화의 진척과 반도체 제조의 고민"),
    (75, "3장 아래층에서 위층까지: 전공정의 문제 극복하기"),
    (148, "4장 전공정 바깥 세상의 전쟁: 패키징"),
    (184, "5장 바깥세상으로 나오는 전공정: 3차원, 2.5차원 패키징"),
    (231, "6장 패키지 밖으로: 전용 반도체, 새로운 개념"),
    (256, "7장 시점을 바꿔: 사용자가 보는 반도체"),
]

FALSE_CHAPTER_PAGES = {2, 51, 76, 191}

pytestmark = pytest.mark.skipif(
    not REAL_BOOK_TMP.is_dir() or os.getenv("EBOOK_CAPTURE_SKIP_REAL_BOOK") == "1",
    reason="Real book OCR tmp not available on this machine",
)


def _structure():
    pages = normalize_paragraphs(load_ocr_pages(REAL_BOOK_TMP, REAL_BOOK_TITLE))
    return build_book_structure(REAL_BOOK_TITLE, pages)


def test_real_book_chapter_count() -> None:
    structure = _structure()
    chapter_items = [ch for ch in structure.chapters if ch.kind == CHAPTER_KIND]
    assert len(chapter_items) == len(EXPECTED_CHAPTERS)


def test_real_book_chapter_starts() -> None:
    structure = _structure()
    chapter_items = [ch for ch in structure.chapters if ch.kind == CHAPTER_KIND]
    for (page, heading), chapter in zip(EXPECTED_CHAPTERS, chapter_items, strict=True):
        assert chapter.start_page == page
        assert chapter.heading == heading


def test_real_book_no_false_chapter_headings() -> None:
    structure = _structure()
    headings = {ch.heading for ch in structure.chapters}
    assert "노광 잔혹사: 패턴 그리기의 어려움" not in headings
    assert "전공정의 미세화 방식 소자층 기술 사용처 요약" not in headings
    assert "3차원, 2.5차원 패키징의 주요 요소 기술" not in headings


def test_real_book_chapter2_spans_past_page_51() -> None:
    structure = _structure()
    ch2 = next(ch for ch in structure.chapters if ch.heading.startswith("2장"))
    assert ch2.end_page >= 74


def test_real_book_chapter3_has_content() -> None:
    structure = _structure()
    ch3 = next(ch for ch in structure.chapters if ch.heading.startswith("3장"))
    assert len(ch3.blocks) > 0
    assert ch3.end_page >= 147


def test_real_book_conclusion_is_back_matter() -> None:
    structure = _structure()
    conclusion = next((ch for ch in structure.chapters if ch.heading == "결론"), None)
    assert conclusion is not None
    assert conclusion.kind == BACK_MATTER_KIND
    assert conclusion.start_page == 272
