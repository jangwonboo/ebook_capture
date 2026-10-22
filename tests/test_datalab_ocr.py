"""Datalab chunk → section mapping (no API calls). Ported from parallax's
vlmparse tests: every case here was a real mistake once."""

from __future__ import annotations

from core import datalab_ocr as dl
from core.config import CaptureConfig


def test_inline_math_keeps_delimiters() -> None:
    html = "<p>the product <math>\\Delta e \\times \\Delta d</math> is bounded</p>"
    assert dl.html_to_text(html) == "the product $\\Delta e \\times \\Delta d$ is bounded"


def test_inline_math_unescapes_entities() -> None:
    assert dl.html_to_text("<p>if <math>a &lt; b</math> then</p>") == "if $a < b$ then"


def test_equation_block_becomes_display_math() -> None:
    assert dl.equation_text('<math display="block">E = mc^2</math>') == "$$E = mc^2$$"
    assert dl.equation_text("<p>x^2 + y^2 = z^2</p>") == "$$x^2 + y^2 = z^2$$"


def test_lists_and_breaks_become_lines() -> None:
    html = "<ul><li>첫째</li><li>둘째</li></ul>"
    assert dl.html_to_text(html) == "- 첫째\n- 둘째"
    assert dl.html_to_text("<p>한 줄<br>두 줄</p>") == "한 줄\n두 줄"


def test_footnote_marker_is_dropped() -> None:
    assert dl.html_to_text("<p>본문<sup>1</sup> 계속.<sup>2</sup></p>") == "본문 계속."


def test_list_markers_are_not_doubled() -> None:
    html = ("<ul><li>• 처벌</li><li>1. 동기적 결핍</li><li>2) 인지적</li>"
            "<li>3 Weber (1985)</li><li>2021년 보고</li></ul>")
    assert dl.html_to_text(html) == "- 처벌\n1. 동기적 결핍\n2. 인지적\n3. Weber (1985)\n- 2021년 보고"
    notes = ("<ul><li><div><div>8</div><div>Magee &amp; Galinsky (2008)</div></div></li>"
             "<li><div><div>9</div><div>Cislak et al. (2018)</div></div></li></ul>")
    assert dl.html_to_text(notes) == "8. Magee & Galinsky (2008)\n\n9. Cislak et al. (2018)"


def test_chunk_type_mapping() -> None:
    chunks = [
        {"block_type": "PageHeader", "html": "<p>권력중독</p>"},
        {"block_type": "SectionHeader", "html": "<h1>1장</h1>"},
        {"block_type": "SectionHeader", "html": "<h2>권력의 <b>맛</b></h2>"},
        {"block_type": "Text", "html": "<p>본문 단락.</p>"},
        {"block_type": "TextInlineMath", "html": "<p>where <math>c</math> is light</p>"},
        {"block_type": "Picture", "html": "<p>A man standing near a window</p>"},
        {"block_type": "Caption", "html": "<p>그림 1</p>"},
        {"block_type": "Footnote", "html": "<p>1 각주</p>"},
        {"block_type": "Table", "html": "<table><tr><td>a</td></tr></table>"},
        {"block_type": "Equation", "html": "<math>E = mc^2</math>"},
        {"block_type": "PageFooter", "html": "<p>42</p>"},
        {"block_type": "Text", "html": "<p></p>"},
    ]
    sections = dl.chunks_to_sections(chunks)
    assert [(s["type"], s["text"]) for s in sections] == [
        ("header", "권력중독"),
        ("title", "1장"),
        ("section_title", "권력의 맛"),
        ("body", "본문 단락."),
        ("body", "where $c$ is light"),
        ("caption", "그림 1"),
        ("footnote", "1 각주"),
        ("table", "<table><tr><td>a</td></tr></table>"),
        ("equation", "$$E = mc^2$$"),
        ("page_number", "42"),
    ]


def test_heading_classified_by_position_not_tag_level() -> None:
    body = [{"block_type": "Text", "html": "<p>x</p>", "bbox": [60, 300, 1480, 400]}]
    centred = {"block_type": "SectionHeader", "html": "<h1>무엇이 인간을 강하게 만드는가</h1>",
               "bbox": [517, 100, 1022, 160]}
    left = {"block_type": "SectionHeader", "html": "<h2>신체적 능력</h2>", "bbox": [77, 200, 255, 255]}
    wide = {"block_type": "SectionHeader",
            "html": "<h2>3. 정서적 결핍: 그 결과, 우울 증상이 나타나고 의기소침해진다.</h2>",
            "bbox": [92, 500, 1478, 745]}
    digits = {"block_type": "SectionHeader", "html": "<h1>14</h1>", "bbox": [58, 800, 115, 864]}
    ornament = {"block_type": "Text", "html": "<p>•••</p>", "bbox": [743, 900, 796, 936]}
    fig = {"block_type": "Figure", "html": "", "bbox": [300, 950, 1200, 1300]}
    cap = {"block_type": "SectionHeader", "html": "<h1>인간관계의 두 축</h1>", "bbox": [514, 1310, 1025, 1470]}
    label = {"block_type": "SectionHeader", "html": "<h2>PART 1</h2>", "bbox": [346, 20, 539, 90]}
    out = dl.chunks_to_sections(body + [centred, left, wide, digits, ornament, fig, cap, label])
    assert [s["type"] for s in out] == [
        "body", "section_title", "subtitle", "body", "caption", "title"]
    assert out[1]["text"].startswith("무엇이") and out[2]["text"] == "신체적 능력"
    assert out[3]["text"].startswith("3. 정서적") and out[5]["text"] == "PART 1"
    assert dl.classify_heading("Chapter 2. 권력은 어디에서 오는가", [92, 0, 1450, 80], (769, 1420)) == "subtitle"


def test_rebuild_page_structure_from_blocks_raw() -> None:
    page = {"page": 3, "sections": [], "text": "", "engine": "datalab",
            "blocks_raw": [{"block_type": "Text", "html": "<p>다시</p>", "bbox": [0, 0, 10, 10]}]}
    out = dl.rebuild_page_structure(page)
    assert out["sections"] == [{"type": "body", "text": "다시"}]
    assert out["text"] == "다시"


def test_page_structure_matches_ocr_json_contract() -> None:
    chunks = [
        {"block_type": "Text", "html": "<p>hello</p>", "bbox": [0, 0, 1, 1],
         "images": {"x.jpg": "AAAA"}},
    ]
    page = dl.chunks_to_page_structure(chunks, 7)
    assert page["page"] == 7
    assert page["sections"] == [{"type": "body", "text": "hello"}]
    assert page["text"] == "hello"
    assert page["engine"] == "datalab"
    assert "images" not in page["blocks_raw"][0]


def test_spend_counts_cents_not_dollars() -> None:
    spend = dl.Spend()
    spend.record({"total_cost": 1, "cost_breakdown": {"final_cost_cents": 1.0}})
    spend.record({"total_cost": 2})
    assert spend.pages == 2
    assert abs(spend.usd - 0.03) < 1e-9


def test_find_key_ignores_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(dl, "_load_env_file", lambda: None)
    monkeypatch.setenv("DATALAB_API_KEY", dl.PLACEHOLDER)
    assert dl.find_key(dl.PLACEHOLDER) is None
    assert dl.find_key("real-key") == "real-key"


def test_config_ocr_engine_fields() -> None:
    cfg = CaptureConfig.from_mapping(
        {"ocr_engine": "DataLab", "datalab_mode": "balanced", "ocr_workers": 6}
    )
    assert cfg.ocr_engine == "datalab"
    assert cfg.datalab_mode == "balanced"
    assert cfg.ocr_workers == 6
    cfg.ocr_engine = "tesseract"
    try:
        cfg.validate()
    except ValueError as exc:
        assert "ocr_engine" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
    cfg.ocr_engine = "google"
    cfg.ocr_workers = 0
    try:
        cfg.validate()
    except ValueError as exc:
        assert "ocr_workers" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_cli_parses_engine_flags() -> None:
    from cli import _build_parser

    args = _build_parser().parse_args(
        ["run", "--title", "B", "--base-dir", "E:/x", "--text",
         "--ocr-engine", "datalab", "--datalab-mode", "fast", "--ocr-workers", "4"]
    )
    assert args.ocr_engine == "datalab"
    assert args.datalab_mode == "fast"
    assert args.ocr_workers == 4


def test_paragraph_ends_ignores_footnote_marker() -> None:
    from core.paragraph_merge import paragraph_ends

    assert paragraph_ends("잠재력이라고 보았다.^6^")
    assert paragraph_ends("보았다.^12^ ^13^")
    assert not paragraph_ends("처벌에 기반한 권력")


def test_short_toc_lines_are_not_merged_within_page() -> None:
    from core.ocr_json_loader import PageRecord, SectionBlock
    from core.paragraph_merge import merge_within_page_paragraphs

    page = PageRecord(
        page_num=10,
        sections=[
            SectionBlock(type="body", text="처벌에 기반한 권력"),
            SectionBlock(type="body", text="보상에 기반한 권력"),
            SectionBlock(type="body", text="제안 2: 권력자를 제대로 선별하라"),
            SectionBlock(type="body", text="제안 3: 조직에서 임파워먼트 중심의 리더십을 실천하라"),
            SectionBlock(type="subtitle", text="소제목"),
            SectionBlock(type="body", text="권력이라는 개념은 문화마다 상이하게 인식된다고 할 수 있는데 이는 독일 특유의"),
            SectionBlock(type="body", text="역사적 배경과 관련이 있다."),
        ],
    )
    out = merge_within_page_paragraphs(page)
    texts = [s.text for s in out.sections]
    assert texts[:4] == ["처벌에 기반한 권력", "보상에 기반한 권력",
                         "제안 2: 권력자를 제대로 선별하라", "제안 3: 조직에서 임파워먼트 중심의 리더십을 실천하라"]
    assert len(texts) == 6 and texts[5].endswith("관련이 있다.")


def test_short_toc_lines_are_not_merged_across_pages() -> None:
    from core.ocr_json_loader import PageRecord, SectionBlock
    from core.paragraph_merge import merge_cross_page_paragraphs

    pages = [
        PageRecord(11, [SectionBlock("body", "위계의 장점")]),
        PageRecord(12, [SectionBlock("body", "위계의 단점")]),
        PageRecord(13, [SectionBlock("body", "그는 그것을")]),
        PageRecord(14, [SectionBlock("body", "받아들였고 그 뒤로 오랫동안 권력이라는 말을 입에 올리지 않았다.")]),
    ]
    out = merge_cross_page_paragraphs(pages)
    texts = [s.text for p in out for s in p.sections]
    assert texts[0] == "위계의 장점" and texts[1] == "위계의 단점"
    assert texts[2].startswith("그는 그것을") and texts[2].endswith("않았다.")
