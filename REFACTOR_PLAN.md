# Refactor — output 기준 구조

**상태:** 완료  
**사용자 매뉴얼:** [`USAGE.md`](USAGE.md)

---

## 출력 3종

| output | 생성물 | CLI |
|--------|--------|-----|
| **images** | `tmp/*.png` | `run --images` |
| **pdf** | `tmp/*.png` + `{title}.pdf` | `run --pdf` |
| **text** | `*.ocr.json` + `{title}.md` | `run --text` |

`text` = OCR → JSON → Markdown assemble. 소스: PNG → PDF → 화면 캡처.

---

## 핵심 모듈

```
cli.py                    # gui | run
core/job_plan.py          # 산출물 분석, Proceed? 확인
core/job_runner.py        # plan → pipeline / assemble
core/pipeline.py          # capture · OCR · PDF
core/image_pdf.py         # PNG → 이미지 PDF
core/assemble_*.py        # OCR JSON → Markdown
default_config.json       # output_mode: pdf
```

---

## 선택적 후속

| 항목 | 설명 |
|------|------|
| GUI resume 토글 | CLI `--no-resume`과 동기화 |
| `pipeline.py` mock 테스트 | resume / force-phase |
| Windows CI | Win32 캡처 integration |
