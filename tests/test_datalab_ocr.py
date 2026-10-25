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
    assert dl.equation_text('<math display="block">E = mc^2</math>') == "$$\nE = mc^2\n$$"
    assert dl.equation_text("<p>x^2 + y^2 = z^2</p>") == "$$\nx^2 + y^2 = z^2\n$$"
    # aligned rows each on their own line; fences alone on theirs (Typora needs this)
    assert dl.equation_text(
        '<math display="block">\\begin{aligned} a &= b \\\\ &= c \\end{aligned}</math>'
    ) == "$$\n\\begin{aligned} a &= b \\\\\n&= c \\end{aligned}\n$$"
    # display math embedded in a text block becomes its own paragraph
    text = dl.html_to_text('<p>식은 <math display="block">y = x</math> 이다.</p>')
    assert "\n\n$$\ny = x\n$$\n\n" in text


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
        ("title", "권력의 맛"),
        ("body", "본문 단락."),
        ("body", "where $c$ is light"),
        ("caption", "그림 1"),
        ("footnote", "1 각주"),
        ("table", "<table><tr><td>a</td></tr></table>"),
        ("equation", "$$\nE = mc^2\n$$"),
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
    assert dl.classify_heading("4.3 나이브 베이즈", [92, 0, 400, 80], (769, 1420)) == "section_title"
    assert dl.classify_heading("4.3.3.1 학습 단계", [92, 0, 400, 80], (769, 1420)) == "subtitle"


def test_code_blocks_split_by_page_break_are_joined() -> None:
    from core.ocr_json_loader import PageRecord, SectionBlock
    from core.paragraph_merge import merge_code_blocks

    pages = [
        PageRecord(1, [SectionBlock("body", "코드는 다음과 같습니다."),
                       SectionBlock("code", "```\nimport sys\n```"),
                       SectionBlock("code", "```\nclass A:\n    def f(self):\n```"),
                       SectionBlock("footnote", "1 역주"),
                       SectionBlock("page_number", "12")]),
        PageRecord(2, [SectionBlock("header", "MACHINE LEARNING"),
                       SectionBlock("code", "```\n\n        return 1\n```"),
                       SectionBlock("body", "설명.")]),
        PageRecord(3, [SectionBlock("code", "```\n$ pip install x\n```")]),
    ]
    out = merge_code_blocks(pages)
    assert [s.text for s in out[0].sections if s.type == "code"] == [
        "```\nimport sys\nclass A:\n    def f(self):\n        return 1\n```"
    ]
    assert [s.type for s in out[1].sections] == ["header", "body"]
    # a code block after a body paragraph starts a new listing
    assert out[2].sections[0].text == "```\n$ pip install x\n```"


def test_regular_table_becomes_pipe_table() -> None:
    html = ("<table><tr><th>출력</th><th>분류</th></tr>"
            "<tr><td>계산</td><td>카테고리 <math>c</math>를 출력</td></tr></table>")
    assert dl.table_text(html) == "| 출력 | 분류 |\n| --- | --- |\n| 계산 | 카테고리 $c$를 출력 |"
    # Spans keep HTML (structure is the content), math normalised.
    spanned = "<table><tr><th colspan=\"2\">x</th></tr><tr><td>1</td><td><math>c</math></td></tr></table>"
    out = dl.table_text(spanned)
    assert out.startswith("<table>") and "$c$" in out


def test_chapter_label_with_sup_and_wide_title() -> None:
    # "1장" arrives as 1<sup>장</sup>; the title under it spans the page width.
    chunks = [
        {"block_type": "SectionHeader", "html": "<h1>1<sup>장</sup></h1>", "bbox": [284, 229, 431, 401]},
        {"block_type": "SectionHeader", "html": "<h1>인공지능과 머신 러닝</h1>", "bbox": [270, 456, 705, 685]},
        {"block_type": "Text", "html": "<p>본문 끝에 각주 표식.<sup>3</sup></p>", "bbox": [266, 895, 705, 1067]},
    ]
    assert dl.chunks_to_sections(chunks) == [
        {"type": "title", "text": "1장"},
        {"type": "title", "text": "인공지능과 머신 러닝"},
        {"type": "body", "text": "본문 끝에 각주 표식."},
    ]


def test_bare_number_over_title_is_a_chapter_label() -> None:
    # Chapter opener set as "01" above the title (no "장" anywhere); inline
    # emphasis must not inject spaces into the title or the body.
    chunks = [
        {"block_type": "SectionHeader", "html": "<h1>01</h1>", "bbox": [100, 100, 180, 180]},
        {"block_type": "SectionHeader", "html": "<h2>BoW(단어 주머니)에서<br/><u>트랜스포</u>머까지</h2>", "bbox": [100, 200, 700, 300]},
        {"block_type": "Text", "html": "<p>지난 20년간 <b>자연어 처리</b>(natural language processing, <b>NLP</b>) 분야</p>", "bbox": [100, 320, 700, 400]},
    ]
    assert dl.chunks_to_sections(chunks) == [
        {"type": "title", "text": "1장"},
        {"type": "title", "text": "BoW(단어 주머니)에서 트랜스포머까지"},
        {"type": "body", "text": "지난 20년간 자연어 처리(natural language processing, NLP) 분야"},
    ]
    # Right-hand opener: both the number and the title tagged PageHeader, told
    # apart from a page number by their display size.
    right = [
        {"block_type": "PageHeader", "html": "<p>07</p>", "bbox": [1800, 194, 1948, 302]},
        {"block_type": "PageHeader", "html": "텍스트<br/>표현", "bbox": [1750, 407, 1950, 576]},
        {"block_type": "Text", "html": "<p>이전 장들에서는 분류와 생성 문제를 처리했다.</p>", "bbox": [374, 1275, 1952, 2112]},
    ]
    assert dl.chunks_to_sections(right) == [
        {"type": "title", "text": "7장"},
        {"type": "title", "text": "텍스트 표현"},
        {"type": "body", "text": "이전 장들에서는 분류와 생성 문제를 처리했다."},
    ]
    # "CHAPTER" set alone above the number is part of the label, not a heading.
    worded = [
        {"block_type": "SectionHeader", "html": "<h1>CHAPTER</h1>", "bbox": [280, 394, 571, 467]},
        {"block_type": "SectionHeader", "html": "<h1>1</h1>", "bbox": [519, 532, 595, 708]},
        {"block_type": "SectionHeader", "html": "<h2>자연어 처리와<br/>허깅페이스</h2>", "bbox": [703, 926, 1400, 1251]},
    ]
    assert dl.chunks_to_sections(worded) == [
        {"type": "title", "text": "1장"},
        {"type": "title", "text": "자연어 처리와 허깅페이스"},
    ]
    # A small page number followed by a heading at the top of the page is not a label.
    pageno = [
        {"block_type": "PageHeader", "html": "<p>31</p>", "bbox": [1984, 127, 2045, 177]},
        {"block_type": "SectionHeader", "html": "<h2>아나콘다 설치</h2>", "bbox": [374, 300, 900, 360]},
        {"block_type": "Text", "html": "<p>본문.</p>", "bbox": [374, 400, 1952, 600]},
    ]
    assert [s["type"] for s in dl.chunks_to_sections(pageno)] == ["header", "subtitle", "body"]
    # A bare number in the middle of a page, or followed by a numbered section, is not a label.
    mid = [
        {"block_type": "Text", "html": "<p>본문.</p>", "bbox": [100, 100, 700, 150]},
        {"block_type": "SectionHeader", "html": "<h2>3</h2>", "bbox": [100, 200, 180, 240]},
        {"block_type": "SectionHeader", "html": "<h2>2.2 설치</h2>", "bbox": [100, 260, 500, 300]},
    ]
    assert [s["text"] for s in dl.chunks_to_sections(mid)] == ["본문.", "2.2 설치"]


def test_front_matter_headings_are_not_chapters() -> None:
    # TOC lines end with a page number; a "N장" label without a title after it
    # is a picture label; an all-caps running head tagged as heading is a header.
    chunks = [
        {"block_type": "SectionHeader", "html": "<h2>1장 인공지능과 머신 러닝 ..... 015</h2>", "bbox": [100, 100, 700, 130]},
        {"block_type": "SectionHeader", "html": "<h2>1.1 인공지능이란? 016</h2>", "bbox": [100, 140, 700, 170]},
        {"block_type": "SectionHeader", "html": "<h1>4장</h1>", "bbox": [100, 200, 200, 260]},
        {"block_type": "Picture", "html": "", "bbox": [100, 270, 700, 600]},
        {"block_type": "SectionHeader", "html": "<h2>3.3</h2>", "bbox": [211, 992, 309, 1058]},
        {"block_type": "SectionHeader", "html": "<h2>MACHINE LEARNING FOR DATA ANALYSIS</h2>", "bbox": [673, 986, 1137, 1008]},
    ]
    secs = dl.chunks_to_sections(chunks)
    assert secs == [
        {"type": "body", "text": "1장 인공지능과 머신 러닝 ..... 015"},
        {"type": "body", "text": "1.1 인공지능이란? 016"},
        {"type": "body", "text": "4장"},
        {"type": "header", "text": "MACHINE LEARNING FOR DATA ANALYSIS"},
    ]


def test_bare_section_number_is_glued_to_next_heading() -> None:
    chunks = [
        {"block_type": "PageHeader", "html": "<p>4.8</p>", "bbox": [166, 112, 266, 182]},
        {"block_type": "PageHeader", "html": "<p>MACHINE LEARNING</p>", "bbox": [631, 105, 1085, 130]},
        {"block_type": "SectionHeader", "html": "<h2>자기 회귀</h2>", "bbox": [310, 147, 508, 208]},
        {"block_type": "SectionHeader", "html": "<h2>C O L U M N</h2>", "bbox": [959, 1220, 1137, 1251]},
        {"block_type": "Caption", "html": "<p>♥ 그림 4-12 분류 방식</p>", "bbox": [100, 300, 500, 320]},
        {"block_type": "Picture", "html": "", "bbox": [100, 330, 900, 700]},
        {"block_type": "SectionHeader", "html": "<h2>4.2.2.1 지도 학습</h2>", "bbox": [100, 720, 400, 760]},
    ]
    secs = [s for s in dl.chunks_to_sections(chunks) if s["type"] != "header"]
    assert secs == [
        {"type": "section_title", "text": "4.8 자기 회귀"},
        {"type": "caption", "text": "그림 4-12 분류 방식"},
        {"type": "subtitle", "text": "4.2.2.1 지도 학습"},
    ]


def test_images_are_harvested_as_figures(tmp_path) -> None:
    import base64
    import io
    from PIL import Image

    def png(w, h):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), "white").save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    chunks = [
        {"block_type": "Picture", "html": "<p>A plot of y = x</p>",
         "images": {"_page_0_Picture_1.png": png(200, 120), "tiny.png": png(10, 10)}},
        {"block_type": "Caption", "html": "<p>그림 4-1 산점도</p>"},
    ]
    assets = tmp_path / "assets"
    page = dl.chunks_to_page_structure(chunks, 5, assets)
    figs = [s for s in page["sections"] if s["type"] == "figure"]
    assert len(figs) == 1 and figs[0]["text"].startswith("![그림](assets/")
    assert len(list(assets.glob("*.png"))) == 1
    assert page["sections"][1] == {"type": "caption", "text": "그림 4-1 산점도"}
    # blocks_raw keeps the saved paths, so a rebuild needs no API call.
    assert page["blocks_raw"][0]["images"] == [figs[0]["text"].split("](")[1][:-1]]
    rebuilt = dl.rebuild_page_structure(page)
    assert rebuilt["sections"] == page["sections"]


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


def test_pre_text_block_becomes_fenced_code() -> None:
    nl = chr(10)
    html = "<pre>import math" + nl + nl + "class A(object):" + nl + "    pass</pre>"
    out = dl.chunks_to_sections([{"block_type": "Text", "html": html}])
    assert out[0]["type"] == "code"
    assert out[0]["text"] == "```" + nl + "import math" + nl + nl + "class A(object):" + nl + "    pass" + nl + "```"
