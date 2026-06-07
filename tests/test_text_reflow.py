"""Tests for OCR body text reflow and paragraph normalization."""

from __future__ import annotations

import unittest

from core.paragraph_merge import (
    merge_cross_page_paragraphs,
    normalize_paragraphs,
    paragraph_ends,
)
from core.text_reflow import join_wrapped_lines, reflow_body_text


class ReflowTests(unittest.TestCase):
    def test_korean_mid_word_break(self) -> None:
        text = "당연하다. 소프\n트웨어는 그냥"
        out = reflow_body_text(text)
        self.assertIn("소프트웨어는", out)
        self.assertNotIn("소프\n", out)

    def test_korean_particle_break(self) -> None:
        text = "시중의 많은 책과 인터넷의\n정보들이 백과사전식"
        out = reflow_body_text(text)
        self.assertIn("인터넷의 정보들이", out)

    def test_english_hyphen_break(self) -> None:
        self.assertEqual(join_wrapped_lines("semi-", "conductor"), "semiconductor")

    def test_preserves_paragraph_breaks(self) -> None:
        text = "첫 문단입니다.\n\n두 번째 문단입니다."
        out = reflow_body_text(text)
        self.assertEqual(out, "첫 문단입니다.\n\n두 번째 문단입니다.")


class RealBookReflowRegression(unittest.TestCase):
    """Examples from AI 시대 다시 시작하는 반도체 공부."""

    PAGE_13_BODY = (
        "그런데 여기서 한 가지 짚고 넘어가야 할 점이 있다. 분명 주인은 소프트웨어를\n"
        "제대로 만들었는데, 여전히 가게에서는 실수가 빈번하게 일어난다. 당연하다. 소프\n"
        "트웨어는 그냥 일하는 순서일 뿐이고, 아르바이트생이 순서도를 실수 없이 수행한\n"
        "다는 보장은 없기 때문이다."
    )

    def test_page_13_soft_breaks(self) -> None:
        out = reflow_body_text(self.PAGE_13_BODY)
        self.assertIn("소프트웨어를 제대로", out)
        self.assertIn("소프트웨어는 그냥", out)
        self.assertIn("수행한다는 보장", out)
        self.assertNotIn("소프\n", out)

    def test_cross_page_internet_break(self) -> None:
        from core.ocr_json_loader import PageRecord, SectionBlock

        pages = [
            PageRecord(
                page_num=5,
                sections=[
                    SectionBlock(
                        type="body",
                        text="하지만 안타깝게도 시중의 많은 책과 인터넷의",
                    )
                ],
            ),
            PageRecord(
                page_num=6,
                sections=[
                    SectionBlock(
                        type="body",
                        text="정보들이 백과사전식 구성을 따르고 있습니다.",
                    )
                ],
            ),
        ]
        merged = normalize_paragraphs(pages)
        bodies = [s for p in merged for s in p.sections if s.type == "body"]
        self.assertEqual(len(bodies), 1)
        self.assertIn("인터넷의 정보들이", bodies[0].text)

    def test_cross_page_eniac_break(self) -> None:
        from core.ocr_json_loader import PageRecord, SectionBlock

        pages = [
            PageRecord(
                page_num=18,
                sections=[
                    SectionBlock(
                        type="body",
                        text="고작 1억분의 1의 계산밖에",
                    )
                ],
            ),
            PageRecord(
                page_num=19,
                sections=[
                    SectionBlock(
                        type="body",
                        text="하지 못하는 수준이다. 현재 관점에서 보면",
                    )
                ],
            ),
        ]
        merged = normalize_paragraphs(pages)
        bodies = [s for p in merged for s in p.sections if s.type == "body"]
        self.assertEqual(len(bodies), 1)
        self.assertIn("계산밖에 하지 못하는", bodies[0].text)


if __name__ == "__main__":
    unittest.main()
