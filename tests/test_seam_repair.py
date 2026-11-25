"""Page-seam glue from the book's own vocabulary, and two-line headings."""

from __future__ import annotations

from core.ocr_json_loader import PageRecord, SectionBlock
from core.paragraph_merge import normalize_paragraphs
from core.seam_repair import (
    is_lead_in,
    join_at_seam,
    merge_split_headings,
    seam_glue,
    word_starts,
)

# A small "book": enough running text for the vocabulary to know which
# fragments are words and which are halves of a word.
BOOK = [
    "그는 순탄하지 않은 길을 걸었다. 삶의 의미를 찾는 일은 순간마다 달랐다.",
    "케임브리지대학교에서 그는 행복을 말했다. 행복은 조건이 아니라 태도였다.",
    "극단적 선택이 아니라 상황을 읽는 힘이 필요하다. 상황은 늘 바뀐다.",
    "우리는 서로를 이해하고 싶어 한다. 이해는 느리게 온다. 걸음을 멈추지 마라.",
    "의미는 스스로 만드는 것이다. 한 걸음 더 내디뎌야 한다. 걸음마다 뜻이 있다.",
]
STARTS = word_starts(BOOK)


def test_cut_inside_a_word_is_joined_without_a_space() -> None:
    assert seam_glue("자기 통제의 길은 순", "탄하지 않았다.", STARTS) == ""  # 순탄하지 occurs elsewhere
    assert seam_glue("1911년 케", "임브리지대학교로 떠난다.", STARTS) == ""
    assert seam_glue("온전한 행", "복을 경험할 수 있다.", STARTS) == ""
    assert seam_glue("우리가 이", "해하고 표현할 수 있는", STARTS) == ""


def test_cut_between_words_keeps_the_space() -> None:
    assert seam_glue("진정한 자아와 삶의", "의미를 찾아갔다.", STARTS) == " "
    assert seam_glue("역사를 돌아보면 극단적", "상황에서도 절망을", STARTS) == " "
    assert seam_glue("다시 한", "걸음 내디뎌야 한다.", STARTS) == " "


def test_bare_particle_or_ending_attaches() -> None:
    assert seam_glue("흔들리는 나뭇잎처럼 우리", "는 외부의 변화에", STARTS) == ""
    assert seam_glue("적용될 수 있는지 고민했", "다. 그래서 철학적", STARTS) == ""
    assert seam_glue("어떻게 연결될 수 있는가’", "를 직접 경험하려 했다.", STARTS) == ""
    assert seam_glue("지탱해 주지 못하", "며, 설령 한때", STARTS) == ""


def test_verb_ending_attaches_to_a_bare_noun_only() -> None:
    assert seam_glue("시도하기도 했지만 끝내 정착", "하지 못했다.", STARTS) == ""
    # "밖에" already carries a particle: the verb starts a new word.
    assert seam_glue("고작 1억분의 1의 계산밖에", "하지 못하는 수준이다.", STARTS) == " "


def test_finished_word_before_the_seam_keeps_the_space_without_evidence() -> None:
    # "정보들이" never occurs elsewhere, but "인터넷의" is a complete word.
    assert seam_glue("시중의 많은 책과 인터넷의", "정보들이 백과사전식", {}) == " "


def test_non_hangul_edges_keep_the_space() -> None:
    assert seam_glue("1914년 11월 13일,", "일기에서 그는", STARTS) == " "
    assert seam_glue("버전 2", "장에서 다룬다", STARTS) == " "
    assert join_at_seam("a long hyphen-", "ated word", STARTS) == "a long hyphenated word"


def test_cross_page_merge_uses_the_book_vocabulary() -> None:
    pages = [PageRecord(page_num=i + 1, sections=[SectionBlock(type="body", text=text)]) for i, text in enumerate(BOOK)]
    pages += [
        PageRecord(page_num=10, sections=[SectionBlock(type="body", text="하지만 위대한 철학자에게도 자기 자신을 다스리는 통제의 길은 결코 처음부터 끝까지 순")]),
        PageRecord(page_num=11, sections=[SectionBlock(type="body", text="탄하지 않았다. 한계를 인정해야 할 때도 있었다.")]),
        PageRecord(page_num=12, sections=[SectionBlock(type="body", text="비트겐슈타인은 자신의 철학적 여정을 통해 진정한 자아와 삶의")]),
        PageRecord(page_num=13, sections=[SectionBlock(type="body", text="의미를 찾아갔다.")]),
    ]
    bodies = [s.text for p in normalize_paragraphs(pages) for s in p.sections if s.type == "body"]
    assert any("끝까지 순탄하지 않았다." in text for text in bodies)
    assert any("자아와 삶의 의미를 찾아갔다." in text for text in bodies)


def test_two_line_heading_is_one_heading() -> None:
    merged = merge_split_headings(
        [
            SectionBlock(type="subtitle", text="나를 잃으면"),
            SectionBlock(type="subtitle", text="전부 잃는다"),
            SectionBlock(type="body", text="본문이다."),
        ]
    )
    assert [(s.type, s.text) for s in merged] == [("subtitle", "나를 잃으면 전부 잃는다"), ("body", "본문이다.")]


def test_separate_headings_stay_separate() -> None:
    numbered = [SectionBlock(type="subtitle", text="1. 첫째"), SectionBlock(type="subtitle", text="2. 둘째")]
    assert merge_split_headings(numbered) == numbered
    finished = [SectionBlock(type="section_title", text="끝난 문장이다."), SectionBlock(type="section_title", text="다음 제목")]
    assert merge_split_headings(finished) == finished
    mixed = [SectionBlock(type="section_title", text="큰 제목"), SectionBlock(type="subtitle", text="작은 제목")]
    assert merge_split_headings(mixed) == mixed


def test_dangling_first_line_joins_the_heading() -> None:
    merged = merge_split_headings(
        [
            SectionBlock(type="body", text="앞 문단이 끝난다."),
            SectionBlock(type="body", text="마흔,"),
            SectionBlock(type="subtitle", text="자기만의 철학이 있어야 할 때"),
            SectionBlock(type="caption", text="삶에서"),
            SectionBlock(type="subtitle", text="균형을 찾는 법"),
        ]
    )
    assert [(s.type, s.text) for s in merged] == [
        ("body", "앞 문단이 끝난다."),
        ("subtitle", "마흔, 자기만의 철학이 있어야 할 때"),
        ("subtitle", "삶에서 균형을 찾는 법"),
    ]


def test_labels_and_sentences_are_not_lead_ins() -> None:
    assert is_lead_in("마흔,")
    assert is_lead_in("삶에서")
    for text in ("고요", "침묵", "◦ 시작하며 ◦", "나는 누구인가?", "비트겐슈타인의 내면", "그래서 나는 걷는다"):
        assert not is_lead_in(text), text


def test_normalize_paragraphs_repairs_headings() -> None:
    page = PageRecord(
        page_num=1,
        sections=[
            SectionBlock(type="body", text="마흔,"),
            SectionBlock(type="subtitle", text="자기만의 철학이 있어야 할 때"),
            SectionBlock(type="body", text="사람들은 흔히 나는 나를 잘 안다고 생각한다."),
        ],
    )
    sections = normalize_paragraphs([page])[0].sections
    assert [(s.type, s.text) for s in sections][0] == ("subtitle", "마흔, 자기만의 철학이 있어야 할 때")
