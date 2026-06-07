"""Tests for OCR JSON → Markdown assembly (MVP)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

from core.assemble_markdown import assemble_markdown
from core.book_structure import BACK_MATTER_KIND, build_book_structure, slugify
from core.markdown_render import render_markdown
from core.ocr_json_loader import load_ocr_pages
from core.paragraph_merge import (
    looks_like_continuation,
    merge_cross_page_paragraphs,
    normalize_paragraphs,
    paragraph_ends,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sample_book" / "tmp"


class ParagraphMergeTests(unittest.TestCase):
    def test_continuation_detection(self) -> None:
        self.assertTrue(looks_like_continuation("로는 0) 에너지만을"))
        self.assertFalse(looks_like_continuation("독자 여러분은"))

    def test_incomplete_sentence(self) -> None:
        self.assertFalse(paragraph_ends("상태가 변화"))
        self.assertTrue(paragraph_ends("변화한다."))

    def test_merge_pages_19_20(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        subset = [p for p in pages if p.page_num in {19, 20}]
        merged = merge_cross_page_paragraphs(subset)
        self.assertEqual(len(merged), 1)
        bodies = [s for s in merged[0].sections if s.type == "body"]
        self.assertEqual(len(bodies), 1)
        self.assertIn("변화", bodies[0].text)
        self.assertIn("로는 0)", bodies[0].text)


class BookStructureTests(unittest.TestCase):
    def test_chapter_from_title_page(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        structure = build_book_structure("SampleBook", pages)
        headings = [ch.heading for ch in structure.chapters if ch.kind == "chapter"]
        self.assertIn("1장 무어의 시대", headings)

    def test_section_page_stays_inside_chapter(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        structure = build_book_structure("SampleBook", pages)
        headings = [ch.heading for ch in structure.chapters]
        self.assertNotIn("03. 노광 잔혹사: 패턴 그리기의 어려움", headings)
        self.assertNotIn("노광 잔혹사: 패턴 그리기의 어려움", headings)

    def test_conclusion_is_back_matter(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        structure = build_book_structure("SampleBook", pages)
        conclusion = next((ch for ch in structure.chapters if ch.heading == "결론"), None)
        self.assertIsNotNone(conclusion)
        self.assertEqual(conclusion.kind, "back_matter")

    def test_slugify_korean(self) -> None:
        self.assertEqual(slugify("1장 무어의 시대"), "1장-무어의-시대")


class MarkdownRenderTests(unittest.TestCase):
    def test_render_contains_toc_and_chapter(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        structure = build_book_structure("SampleBook", normalize_paragraphs(pages))
        md = render_markdown(structure)
        self.assertIn("# SampleBook", md)
        self.assertIn("## 목차", md)
        self.assertIn("## 1장 무어의 시대", md)

    def test_body_only_omits_section_headings_and_figures(self) -> None:
        pages = load_ocr_pages(FIXTURES, "SampleBook")
        structure = build_book_structure("SampleBook", normalize_paragraphs(pages))
        md = render_markdown(structure, body_only=True)
        self.assertIn("무어의 법칙", md)
        self.assertNotIn("### ", md)
        self.assertNotIn("**Figure**", md)
        self.assertNotIn("**Footnote**", md)
        self.assertIn("## 1장 무어의 시대", md)


class AssembleIntegrationTests(unittest.TestCase):
    def test_assemble_writes_md_and_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            md_path = out_dir / "SampleBook.md"
            struct_path = out_dir / "SampleBook_structure.json"
            assemble_markdown(
                title="SampleBook",
                tmp_dir=FIXTURES,
                output_md_path=md_path,
                structure_json_path=struct_path,
            )
            self.assertTrue(md_path.is_file())
            self.assertTrue(struct_path.is_file())
            md = md_path.read_text(encoding="utf-8")
            self.assertIn("무어의 법칙", md)
            data = json.loads(struct_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(data["chapters"]), 1)


@pytest.mark.integration
def test_assemble_md_cli_smoke(tmp_path: Path) -> None:
    """End-to-end via CLI handler on fixture data."""
    import shutil

    from cli import _cmd_run

    book_dir = tmp_path / "SampleBook" / "tmp"
    book_dir.mkdir(parents=True)
    for src in FIXTURES.glob("SampleBook_*.ocr.json"):
        shutil.copy(src, book_dir / src.name)

    class Args:
        config = None
        title = "SampleBook"
        base_dir = tmp_path
        style = "full"
        yes = True
        output_mode = "text"
        active_window = False

    rc = _cmd_run(Args())
    assert rc == 0
    assert (tmp_path / "SampleBook" / "SampleBook.md").is_file()


if __name__ == "__main__":
    unittest.main()
