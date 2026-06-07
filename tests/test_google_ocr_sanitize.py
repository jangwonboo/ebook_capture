"""Tests for Google OCR JSON helpers (no API calls)."""

from __future__ import annotations

import pytest

from core.google_ocr import (
    page_structure_to_text,
    resolve_ocr_prompt,
    sanitize_page_structure,
)


def test_sanitize_empty_page_returns_empty_structure() -> None:
    result = sanitize_page_structure({"page": 8, "text": "", "sections": []}, 8)
    assert result["page"] == 8
    assert result["text"] == ""
    assert result["sections"] == []


def test_sanitize_falls_back_to_top_level_text() -> None:
    result = sanitize_page_structure({"text": "Hello world", "sections": []}, 1)
    assert result["sections"] == [{"type": "body", "text": "Hello world"}]
    assert "Hello" in result["text"]


def test_sanitize_normalizes_sections() -> None:
    raw = {
        "sections": [
            {"type": "TITLE", "text": "Chapter"},
            {"type": "body", "text": "Paragraph one."},
        ]
    }
    result = sanitize_page_structure(raw, 3)
    assert result["sections"][0]["type"] == "title"
    assert result["page"] == 3


def test_sanitize_blocks_alternate_keys() -> None:
    raw = {"blocks": [{"type": "body", "text": "From blocks key"}]}
    result = sanitize_page_structure(raw, 2)
    assert result["sections"][0]["text"] == "From blocks key"


def test_page_structure_to_text_prefers_top_level() -> None:
    data = {"text": "Full page", "sections": [{"type": "body", "text": "ignored"}]}
    assert page_structure_to_text(data) == "Full page"


def test_page_structure_to_text_from_sections() -> None:
    data = {"text": "", "sections": [{"type": "body", "text": "Only section"}]}
    assert "Only section" in page_structure_to_text(data)


def test_resolve_ocr_prompt_placeholders() -> None:
    prompt = resolve_ocr_prompt(lang_hint="kor", page_num=42, custom_prompt="Lang={lang_hint} Page={page_num}")
    assert "kor" in prompt
    assert "42" in prompt


def test_resolve_ocr_prompt_uses_bundled_default(repo_root) -> None:
    prompt = resolve_ocr_prompt(lang_hint="eng", page_num=1)
    assert len(prompt) > 100
    assert "eng" in prompt
