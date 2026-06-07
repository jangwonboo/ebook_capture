"""Tests for core.ocr_json_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.ocr_json_loader import SKIP_SECTION_TYPES, load_ocr_pages


def test_load_sample_book_pages(sample_book_tmp: Path) -> None:
    pages = load_ocr_pages(sample_book_tmp, "SampleBook")
    nums = [p.page_num for p in pages]
    assert nums == sorted(nums)
    assert 9 in nums
    assert 10 in nums


def test_skip_header_and_page_number() -> None:
    assert "header" in SKIP_SECTION_TYPES
    assert "page_number" in SKIP_SECTION_TYPES


def test_empty_page_has_no_content(sample_book_tmp: Path) -> None:
    pages = load_ocr_pages(sample_book_tmp, "SampleBook")
    empty = next(p for p in pages if p.page_num == 8)
    assert not empty.has_text()


def test_missing_tmp_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="tmp directory not found"):
        load_ocr_pages(tmp_path / "missing", "SampleBook")


def test_no_json_files_raises(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    with pytest.raises(FileNotFoundError, match="No OCR JSON"):
        load_ocr_pages(tmp_path / "tmp", "SampleBook")
