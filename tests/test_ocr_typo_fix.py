"""OCR typo correction: dictionary, in-book frequency, protected spans."""

from __future__ import annotations

from collections import Counter

from core.ocr_json_loader import PageRecord, SectionBlock
from core.ocr_typo_fix import (
    TypoDictionary,
    compose,
    confusable_syllables,
    decompose,
    fix_ocr_typos,
    infer_frequency_fixes,
    load_typo_dictionary,
)


def _page(num: int, *texts: str, kind: str = "body") -> PageRecord:
    return PageRecord(page_num=num, sections=[SectionBlock(type=kind, text=t) for t in texts])


def test_jamo_roundtrip_and_confusion() -> None:
    assert decompose("맵") == ("ㅁ", "ㅐ", "ㅂ")
    assert compose("ㅁ", "ㅐ", "ㅂ") == "맵"
    assert "맵" in confusable_syllables("맴")       # ㅁ/ㅂ final
    assert "덴" in confusable_syllables("텐")       # ㄷ/ㅌ initial
    assert "옮" in confusable_syllables("올")       # ㄹ → ㄻ final
    assert "주" not in confusable_syllables("수")   # ㅅ/ㅈ deliberately not confusable


def test_frequency_fix_rare_variant_of_frequent_word() -> None:
    runs = Counter({"맵리듀스": 10, "맵리듀스를": 5, "맴리듀스": 2, "맴리듀스를": 1})
    prefixes: Counter[str] = Counter()
    for run, n in runs.items():
        for length in range(2, len(run) + 1):
            prefixes[run[:length]] += n
    fixes = infer_frequency_fixes(runs, prefixes)
    assert fixes["맴리듀스"].right == "맵리듀스"
    assert fixes["맴리듀스를"].right == "맵리듀스를"
    assert "맵리듀스" not in fixes


def test_frequency_fix_needs_margin() -> None:
    # 7 vs 3: the "rare" form is too common relative to the candidate → leave both.
    runs = Counter({"수행한다": 7, "주행한다": 3, "배치를": 7, "매치를": 3})
    prefixes: Counter[str] = Counter()
    for run, n in runs.items():
        for length in range(2, len(run) + 1):
            prefixes[run[:length]] += n
    assert infer_frequency_fixes(runs, prefixes) == {}


def test_dictionary_prefix_match_keeps_particle_and_skips_math_code() -> None:
    pages = [
        _page(1, "2장에서 소개한 맴리듀스를 활용한다. $\\mathrm{맴리듀스}$ 는 수식이다. `맴리듀스` 코드."),
        _page(2, "맴리듀스", kind="code"),
    ]
    result = fix_ocr_typos(pages, dictionary=load_typo_dictionary(), use_frequency=False)
    assert result.pages[0].sections[0].text == (
        "2장에서 소개한 맵리듀스를 활용한다. $\\mathrm{맴리듀스}$ 는 수식이다. `맴리듀스` 코드."
    )
    assert result.pages[1].sections[0].text == "맴리듀스"
    assert result.total == 1
    assert "맴리듀스 -> 맵리듀스  x1  (사전)" in result.report_text()


def test_custom_dictionary_and_protect() -> None:
    d = TypoDictionary()
    d.update_from_text("# comment\n학슴 -> 학습\n!학슴한다\n")
    assert d.fixes == {"학슴": "학습"}
    assert d.protected == {"학슴한다"}
    runs = Counter({"학습한다": 20, "학슴한다": 1})
    prefixes: Counter[str] = Counter()
    for run, n in runs.items():
        for length in range(2, len(run) + 1):
            prefixes[run[:length]] += n
    assert infer_frequency_fixes(runs, prefixes, protected=d.protected) == {}
    assert infer_frequency_fixes(runs, prefixes)["학슴한다"].right == "학습한다"


def test_frequency_pass_runs_after_dictionary_on_whole_book() -> None:
    body = " ".join(["데이터를 분석한다."] * 6) + " 테이터를 분석한다. 데이더를 분석한다."
    result = fix_ocr_typos([_page(1, body)], dictionary=TypoDictionary(), use_frequency=True)
    text = result.pages[0].sections[0].text
    assert "테이터" not in text and "데이더" not in text
    assert text.count("데이터를") == 8
    assert {r.wrong for r in result.records} == {"테이터를", "데이더를"}
