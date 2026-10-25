"""LLM proofreading: fix validation, application, caching (no API calls)."""

from __future__ import annotations

import json
from pathlib import Path

from core.llm_proofread import (
    PROOF_SUFFIX,
    apply_fixes_to_page,
    page_prompt,
    parse_fixes,
    proofread_pages,
    validate_fix,
)
from core.ocr_json_loader import PageRecord, SectionBlock


def _page(num: int, *texts: str, kind: str = "body") -> PageRecord:
    return PageRecord(page_num=num, sections=[SectionBlock(type=kind, text=t) for t in texts])


def test_parse_fixes_tolerates_prose_around_json() -> None:
    raw = '교정 목록입니다.\n{"fixes":[{"seg":1,"from":"맴리듀스","to":"맵리듀스"}]}\n끝.'
    assert parse_fixes(raw) == [{"seg": 1, "from": "맴리듀스", "to": "맵리듀스"}]
    assert parse_fixes("no json here") == []


def test_validate_fix_rejects_rewrites_and_ambiguity() -> None:
    seg = "자기 회귀는 추가 예측 등 시계열 분석에 사용하며 추가 비용이 든다."
    assert validate_fix("추가 예측", "추가 예측", "주가 예측") == ""
    assert validate_fix(seg, "추가", "주가") == "ambiguous"
    assert validate_fix(seg, "시계열 분석에 사용하며", "시계열 분석에 쓰이며 매우 유용하고") == "length"
    assert validate_fix(seg, "비용이 든다", "무료입니다") == "too-different"
    assert validate_fix(seg, "없는말", "있는말") == "not-found"
    assert validate_fix("x = 1 더하기 2", "1", "2") == "no-hangul"
    assert validate_fix("수식 $a$ 뒤", "$a$", "$b$") == "protected"
    # Short syllable swaps and math carried over unchanged are accepted.
    assert validate_fix("장맛이 뻗 책", "뻗", "밴") == ""
    assert validate_fix("허둠 사이", "허둠", "하둡") == ""
    assert validate_fix("바이러스 $b$를 찾는다", "바이러스 $b$를", "바이어스 $b$를") == ""
    assert validate_fix("바이러스 $b$를 찾는다", "바이러스 $b$를", "바이어스 $c$를") == "protected"
    assert validate_fix("ㄴ 항목", "L", "ㄴ") == "not-found"
    assert validate_fix("L 항목", "L", "ㄴ") == ""


def test_apply_fix_spanning_math() -> None:
    page = _page(8, "바이러스 $b$를 찾습니다.")
    new_page, recs = apply_fixes_to_page(
        page, [0], [{"seg": 1, "from": "바이러스 $b$를", "to": "바이어스 $b$를"}]
    )
    assert new_page.sections[0].text == "바이어스 $b$를 찾습니다."
    assert recs[0].applied


def test_apply_skips_protected_spans_and_code_sections() -> None:
    page = PageRecord(
        page_num=3,
        sections=[
            SectionBlock("body", "맴리듀스를 쓴다. 수식 $\\text{맴리듀스}$ 는 둔다."),
            SectionBlock("code", "맴리듀스"),
        ],
    )
    prompt, idx = page_prompt(page)
    assert idx == [0] and prompt.startswith("[1] 맴리듀스를")
    new_page, recs = apply_fixes_to_page(page, idx, [{"seg": 1, "from": "맴리듀스를", "to": "맵리듀스를"}])
    assert new_page.sections[0].text == "맵리듀스를 쓴다. 수식 $\\text{맴리듀스}$ 는 둔다."
    assert new_page.sections[1].text == "맴리듀스"
    assert [r.applied for r in recs] == [True]


def test_proofread_pages_caches_per_page(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake(prompt: str) -> tuple[str, int, int]:
        calls.append(prompt)
        return '{"fixes":[{"seg":1,"from":"테이터","to":"데이터"}]}', 100, 10

    pages = [_page(1, "테이터를 본다."), _page(2, "그림만", kind="figure")]
    res = proofread_pages(pages, tmp_dir=tmp_path, title="책", request=fake, workers=1)
    assert res.pages[0].sections[0].text == "데이터를 본다."
    assert len(calls) == 1 and res.usage.pages == 1 and res.usage.input_tokens == 100
    cache = tmp_path / f"책_0001{PROOF_SUFFIX}"
    assert json.loads(cache.read_text(encoding="utf-8"))["fixes"][0]["to"] == "데이터"

    res2 = proofread_pages(pages, tmp_dir=tmp_path, title="책", request=fake, workers=1)
    assert len(calls) == 1 and res2.usage.cached == 1
    assert res2.pages[0].sections[0].text == "데이터를 본다."
    assert "p0001  테이터 -> 데이터" in res2.report_text()


def test_cache_survives_spacing_changes(tmp_path: Path) -> None:
    calls: list[str] = []

    def fake(prompt: str) -> tuple[str, int, int]:
        calls.append(prompt)
        return '{"fixes":[{"seg":1,"from":"테이터","to":"데이터"}]}', 10, 1

    proofread_pages([_page(1, "테이터 를 본다.")], tmp_dir=tmp_path, title="책", request=fake, workers=1)
    res = proofread_pages([_page(1, "테이터를 본다.")], tmp_dir=tmp_path, title="책", request=fake, workers=1)
    assert len(calls) == 1 and res.usage.cached == 1
    assert res.pages[0].sections[0].text == "데이터를 본다."


def test_request_errors_keep_page_and_are_reported(tmp_path: Path) -> None:
    def boom(prompt: str) -> tuple[str, int, int]:
        raise RuntimeError("down")

    res = proofread_pages([_page(1, "테이터")], tmp_dir=tmp_path, title="책", request=boom, workers=1)
    assert res.pages[0].sections[0].text == "테이터"
    assert res.usage.failed == 1 and res.errors and "down" in res.errors[0]
