# ebook_capture 사용법

화면(또는 지정 창)을 연속 캡처해 **PNG**, **이미지 PDF**, 또는 **OCR Markdown**을 만듭니다.  
설치·개요: [README.md](README.md) · 개발자 문서: [REQUIREMENTS.md](REQUIREMENTS.md)

```powershell
python -m ebook_capture run [options]
# 또는 editable 설치 후
ebook-capture run [options]
```

---

## 1. 출력 선택

| 출력 | 결과 파일 | 설명 |
|------|-----------|------|
| **images** | `tmp/{title}_NNNN.png` | 캡처만 |
| **pdf** | PNG + `{title}.pdf` | 이미지 PDF (**기본**) |
| **text** | `*.ocr.json` + `{title}.md` | Gemini OCR → Markdown |

`--text`는 OCR과 Markdown 조립까지 한 번에 합니다.  
소스 우선순위: 이미 있는 PNG → 책 PDF/`--input-pdf` → (없으면) 화면 캡처.

---

## 2. 명령

| 명령 | 용도 |
|------|------|
| `gui` | 그래픽 인터페이스 |
| `run` | 캡처 / PDF / OCR 실행 |
| `test-key` | 페이지 넘김 키만 테스트 |
| `inspect` | 창 위치·캡처 영역 확인 |

---

## 3. 빠른 시작

### GUI

```powershell
python -m ebook_capture gui
```

1. **Reader** — Kindle / Aladin 등 프로필 선택 (키·포커스·시작 맞춤 자동 적용)
2. **Folder / Title / Page count** — 출력 위치와 분량
3. **Refresh windows** — 리더 창 선택 (웹 리더는 탭 제목이 바뀔 수 있음)
4. **Output** — Images / PDF / Text
5. **Start** — 실행 (확인 생략 `-y`)

**Assemble MD**: OCR JSON만 있을 때 Markdown만 다시 만듭니다.

### CLI

```powershell
# PDF (기본)
python -m ebook_capture run --config default_config.jsonc --pdf -y

# Kindle 앱 프로필로 캡처
python -m ebook_capture run --config default_config.jsonc --reader kindle_app -y

# 이미 PNG가 있으면 OCR + MD만
python -m ebook_capture run --title "My Book" --base-dir E:\ebook --text -y

# 부분 OCR만 있어도 범위 전체가 될 때까지 resume (PNG 전부 또는 책 PDF 사용)
python -m ebook_capture run --config default_config.jsonc --text --style full -y

# 외부 PDF → text
python -m ebook_capture run --title Book --base-dir E:\ebook --text --input-pdf E:\in\book.pdf -y

# PDF → Datalab OCR → Markdown (Gemini 대신 Datalab, 6페이지 동시 요청)
python -m ebook_capture run --title Book --base-dir E:\ebook --text --input-pdf E:\in\book.pdf --ocr-engine datalab --ocr-workers 6 -y
```

### PDF → OCR → Markdown (Datalab)

`--ocr-engine datalab`은 [Datalab](https://www.datalab.to)(호스팅 Marker)에 페이지를 보내 **유형이 붙은 레이아웃 블록**(SectionHeader / Text / Caption / Footnote / Table / Equation / PageHeader …)을 받고, 그것을 `tmp/*.ocr.json`의 section 타입(`title` / `section_title` / `body` / `caption` / `footnote` / `table` / `equation` / `header` / `page_number`)으로 바로 대응시킵니다. 프롬프트가 없으므로 `--ocr-prompt*`와 `--ocr-lang`은 무시됩니다. 그 뒤의 장·단락 조립(`{title}.md`)은 Gemini 경로와 같습니다.

- 입력은 `tmp/*.png`(캡처 결과) 또는 `--input-pdf`(한 쪽씩 잘라 PDF 그대로 전송). 둘 다 쪽당 1건 요청이며 실측 accurate 모드 약 1센트/쪽, 쪽당 10초 안팎.
- `--ocr-workers N`(1-16): 동시 요청 수. Datalab은 요청마다 큐에 서므로 4-8이면 벽시계 시간이 그만큼 줄고 비용은 같습니다. 429/연결 끊김은 Retry-After로 물러나 재시도합니다.
- 실패한 쪽은 `OCR_PAGE_FAIL`로 남기고 나머지를 계속합니다. 끝에 `OCR_FAIL n page(s)`가 찍히면 같은 명령을 다시 실행하면 빠진 쪽만 채웁니다(완료된 쪽은 `OCR_SKIP`).
- `OCR_COST datalab pages=N usd=X`: 응답의 `cost_breakdown.final_cost_cents` 합계(단위 센트 → 달러).
- `--datalab-mode fast|balanced|accurate`(기본 accurate). `fast`는 PDF 텍스트 레이어를 긁어 인라인 수식을 놓칩니다.

수식·그림·표·코드는 다음처럼 남습니다(기술서 한 장, 100쪽 실측: 수식 92건 표시·187건 인라인, 그림 29장, 표 10개, 코드 118블록).

| 원본 | Markdown |
| --- | --- |
| 수식(별행) | `$$`를 앞뒤 별도 줄에 둔 블록(Typora는 한 줄짜리 `$$…$$`를 렌더하지 않음). `\begin{aligned}`의 `\\` 행 구분마다 줄바꿈 |
| 수식(본문 속) | `$ … $`. Typora는 기본값이 꺼져 있으니 환경설정 > Markdown > "인라인 수식"을 켜야 함 |
| 그림 | `<output_dir>/assets/<sha1 16자리>.jpg\|png`에 저장하고 `![그림](assets/…)`로 참조. 64px 미만 장식 이미지는 버림. 캡션(`그림 4-12 …`)은 그림 앞 이탤릭 줄, 앞의 장식 기호(`♥ ▼`)는 제거 |
| 표 | 행·열이 고른 표는 파이프 표(`\| … \|`), 병합 셀(rowspan/colspan)이 있으면 HTML `<table>` 유지(셀 안 `<math>`는 `$…$`) |
| 코드 | ` ``` ` 펜스. Datalab이 `<pre>`로 감싼 Text 블록도 코드로 봄. 쪽 경계나 줄 묶음 단위로 쪼개진 코드 블록은 사이에 러닝 헤더·쪽 번호·쪽 하단 각주만 있으면 하나로 이어 붙임(들여쓰기는 OCR 결과 그대로) |
| 절 번호 제목 | `4.3 제목` → `###`, `4.3.1 …`(그 이하) → `####`. 번호만 러닝 헤더로 떨어진 경우(`4.8` + 다음 제목) 붙여서 복원 |
| `C O L U M N` 상자 라벨 | 버림(상자 제목만 `####`) |
| 장 머리 | `N장` 라벨(위첨자 `<sup>장</sup>` 포함) + 다음 제목 → `## N장 제목`. 라벨만 있고 제목이 안 따르면(스크린샷 라벨) 본문 |
| 목차 줄 | 끝에 쪽 번호가 붙은 제목(`1.1 인공지능이란? 016`)은 제목이 아니라 본문 |
| 러닝 헤더 | 대문자 영문 러닝 헤더(`MACHINE LEARNING FOR …`)는 어떤 블록으로 오든 버림 |

장 표시(`N장`/`Chapter N`)가 한 번도 없는 입력(책에서 한 장만 잘라 변환)은 "Front matter"가 아니라 제목이 `title`인 단일 장으로 조립됩니다.
- Picture/Figure 블록의 글(모델이 지어낸 그림 설명)은 버립니다. 표는 HTML 그대로 `table` 섹션, 수식은 `$…$` / `$$…$$`로 남습니다. `blocks_raw`(유형+HTML+bbox)가 각 `.ocr.json`에 같이 저장됩니다.
- 제목 등급은 Marker의 h1/h2가 아니라 **블록 위치**로 정합니다(리플로우 리더는 번호 목록·인용·미주를 큰 글자로 그려서 글자 크기가 단락 성격과 맞지 않습니다). 가운데 정렬 → `section_title`(###), 왼쪽 정렬 → `subtitle`(####), 본문 폭 전체(80% 이상)나 `1. …` 번호 항목 → `body`, 그림 바로 아래 → `caption`, 장 라벨(`Chapter N`, `PART N`, `N장`) → `title`, 숫자만/장식 기호만 → 버림. 장 머리의 작은 "Chapter N" 라벨은 PageHeader로 오는데 조립 단계가 이를 장 시작으로 씁니다.
- 본문 정리: 각주 참조 번호(`<sup>`)는 버리고, `<li>` 안에 반복된 글머리(`• 항목`)는 하나만 남기며, `1. 항목`/`1 항목` 꼴 항목은 번호 목록으로 냅니다(미주처럼 번호와 글이 다른 `<div>`로 갈라진 항목도 붙임). `full` 스타일은 이제 `<!-- pages: a-b -->` 주석을 넣지 않습니다(`AssembleOptions(page_comments=True)`로 켤 수 있음).
- 분류 규칙만 바뀌었을 때는 재OCR 없이 `core.datalab_ocr.rebuild_page_structure()`로 기존 `.ocr.json`의 `blocks_raw`에서 섹션을 다시 만들 수 있습니다(과금 0).

필요한 중간 파일이 없으면 **실행할 단계 목록**을 보여 주고 `Proceed? [Y/n]`으로 묻습니다.  
스크립트·GUI는 `-y` / `--yes`로 건너뜁니다.

---

## 4. 리더 프로필

리더마다 페이지 넘김·포커스 클릭이 다릅니다. 프로필로 한 번에 맞춥니다.

| 프로필 | 대상 | 넘김 키 / 전달 / 포커스 클릭 |
|--------|------|-------------------------------|
| `kindle_app` | Kindle 데스크톱 (**검증 기준선**) | right / sendinput / 2@중앙 |
| `kindle_cloud` | Kindle Cloud Reader (브라우저) | right / pyautogui / 2@중앙 |
| `aladin_app` | 알라딘 ebook 앱 | pagedown / sendinput / 2@중앙 |
| `aladin_web` | 알라딘 웹 뷰어 | pagedown / pyautogui / 2@중앙 |
| `rdp_full` | 원격 데스크톱(mstsc) 창 안의 리더 (client 영역 전체) | right / sendinput / 0 (API 포그라운드) |

`rdp_full`은 다른 프로필과 루프가 다릅니다. 원격 리더는 세션 안에서 전체 화면으로 띄우고,
로컬에서는 mstsc 창을 모니터 높이에 맞춰 둡니다 (2026-10-10 검증: client 1438x1761).

| 항목 | 값 | 이유 |
|------|----|------|
| `keep_pointer_outside` | true | 포인터가 원격 리더 위를 지나면 hover 툴바가 뜸. 창 옆에 세워 두고 되돌리지 않음 |
| `settle_stable_sec` / `settle_max_sec` | 0.4 / 4.0 | 키 입력 후 페이지 넘김 바가 사라질 때까지 연속 두 장이 같아질 때까지 재촬영 |
| `page_turn_retries` | 2 | 화면이 안 바뀌면(포커스 이탈로 키 유실) 재포그라운드 + 키 재전송 후 재촬영 |
| `pdf_auto_crop` | true | 고정 `pdf_trim` 대신 캡처 완료 후 페이지 공통 윤곽을 뽑아 crop (아래 참고) |
| `prevent_sleep` | true (config 기본) | 캡처 중 화면 보호기·디스플레이 끄기 차단 (`SetThreadExecutionState`) |
| `--sub-left/--sub-top/--sub-width/--sub-height` (`window_subrect`) | 책마다 | 창 client 영역 중 리더 페이지 부분만 캡처. 원격 세션이 전체 화면(3840x2160)이고 리더가 일부만 차지할 때 사용. 좌표는 `inspect --screenshot`의 probe 기준(물리 픽셀, run과 동일 DPI 모드). width/height 0 = 끝까지. 2026-10-22 검증: 4K 세션 리더 `--sub-left 2 --sub-top 81 --sub-width 1277 --sub-height 1975` |
| `--pdf-auto-crop-margin` (`pdf_auto_crop_margin`) | 0.0 | 감지한 윤곽을 사방으로 이 비율만큼 넓힘. 본문이 윤곽 끝까지 꽉 차는 리플로우 책(권력중독: 글자 끝 = 크롭선)은 0.005 정도를 주면 안티앨리어싱이 안 잘림 |
| `stop_repeat_tolerance` | 0.3 (config 기본) | 회색 썸네일 평균 차이가 이 값 이하면 같은 페이지로 봄. 리더 오버레이(화살표 등)는 ~0.003, 실제 넘김은 4 이상. 책 끝 감지와 키 재전송 판단에 공통 사용. 0.0 = 완전 일치 |

`pdf_auto_crop`은 각 PNG의 바깥 테두리를 단계적으로 벗겨 가며 "채워진 상자"(검은 RDP 바에 대비되는 흰 페이지,
페이지 안의 표지 그림)를 찾고, 페이지마다 가장 바깥의 채워진 상자를 모아 중앙값을 공통 윤곽으로 씁니다.
배경 있는 페이지(표지, 장 표제지)가 윤곽을 결정하고, 글만 있는 페이지는 윤곽에 영향을 주지 않습니다.
채워진 상자가 하나도 없으면 전 페이지 내용 상자의 합집합으로 대체합니다. 로그의 `PDF_AUTO_CROP source=…`로
어느 쪽이 쓰였는지 확인할 수 있고, `--no-pdf-auto-crop`으로 끌 수 있습니다.

두 번째 단계로 리더 크롬을 찾습니다. 상하단 가장자리에서 윤곽의 가로 범위 안 픽셀이 전체 페이지의 30% 이상에서
똑같이 반복되는 행을 위에서부터 이어 세고, 그 띠에 아이콘이나 글자처럼 균일하지 않은 행이 하나라도 있으면 툴바로
보고 잘라냅니다 (`chrome=(top …, bottom …)` 로그). 캡처 도중에 떠서 끝까지 남은 툴바도 이 방식으로 걸러집니다.
균일한 색 행만 쌓인 띠는 표지나 장 표제지 디자인으로 보고 건드리지 않습니다.

공통 기본값 (`kindle_app`에서 검증 후 전 프로필에 공유):

| 항목 | 기본 | 설명 |
|------|------|------|
| `fit_on_start` | 끔 | 시작 시 창 resize 안 함 (미리 배치) |
| `start_focus_clicks` | 0 | 시작 시 포커스 클릭 없음 |
| `reader_focus_clicks` | 2 | 캡처 **직전** 본문 클릭 |
| `reader_focus_x_ratio` / `_y_ratio` | 0.5 / 0.5 | 클릭 위치 (본문 중앙) |
| `focus_click_settle_sec` | 1.0 | 클릭 후 오버레이 사라질 대기 |
| `pdf_trim` | Kindle top=0.032 / Aladin top=0.010·fill_top=0.026·bottom=0.045 | crop + optional white-fill |

페이지 한 장의 처리 순서는 다음과 같습니다.

1. 본문 중앙을 `reader_focus_clicks`회 클릭 (리더 포커스 확보)
2. 포인터를 캡처 영역 밖으로 빼고 `focus_click_settle_sec` 대기 — 페이지 화살표·툴바가 사라짐
3. 이미지 캡처
4. `next_key` 전송 후 `delay_sec` 대기

클릭은 같은 지점을 연속으로 누르므로 시스템 더블클릭 시간(`GetDoubleClickTime`)보다 길게
벌려 보냅니다. 그래서 `reader_focus_clicks: 2`도 더블클릭(= Kindle 이미지 줌)이 되지 않습니다.
클릭 위치는 중앙이 안전합니다. 상단은 툴바, 좌우 가장자리는 페이지 이동 영역입니다.

`kindle_app`은 `pdf_trim.top = 0.032`(앱 상단 바 crop). `aladin_app`은
`top = 0.010`(얇은 title strip crop) + `fill_top = 0.026`(툴바 **white fill**) +
`bottom = 0.045`(하단 nav crop). `fill_*`는 잘라내지 않고 해당 띠만 흰색으로
덮어 상단 여백을 유지합니다. 창 높이를 크게 바꿨다면 비율을 다시 맞추세요.

```powershell
ebook-capture run --config default_config.jsonc --reader kindle_app -y
ebook-capture test-key --config default_config.jsonc --reader aladin_app
```

- GUI **Reader** 콤보 = 동일 동작
- 정의 파일: `reader_profiles.jsonc` (직접 수정·추가 가능)
- 개별 옵션(`--next-key` 등)이 프로필보다 **우선**

### Kindle에서 줌만 될 때

Cloud Reader는 **상단을 클릭하면 Aa/줌 툴바**가 열립니다. 프로필은 이미 **본문 중앙**
클릭을 쓰므로 보통 괜찮습니다. 그래도 툴바가 뜨면 `reader_focus_clicks`를 1 또는 0으로
낮추고, 본문을 한 번 수동 클릭한 뒤 Start 하세요.

표지처럼 이미지 페이지에서 줌이 걸리면 클릭이 더블클릭으로 들어간 경우입니다. 지금은 클릭
간격이 더블클릭 시간보다 길게 조정되어 있으니, 그래도 줌이 되면 `reader_focus_clicks`를 1 또는
0으로 낮추세요.

### 페이지가 안 넘어갈 때

`--debug-capture`를 붙이면 키를 보낸 뒤 화면이 실제로 바뀌었는지 로그로 알려줍니다.

```powershell
python -m ebook_capture run --config default_config.jsonc --reader kindle_app --debug-capture -y
```

`DEBUG_KEY_EFFECT meandiff=... (page moved)`면 정상, `NO VISIBLE CHANGE`면 키가 리더에
전달되지 않았거나 리더가 무시한 것입니다. 후자라면 `key_delivery`를 `pyautogui`로 바꿔
보세요. 캡처 중에는 다른 창을 클릭하지 마세요. 리더가 포그라운드에서 벗어나면 다시
활성화하는 과정에서 페이지 넘김이 한 번 빠질 수 있습니다.

### 첫 페이지가 로딩 화면으로 찍힐 때

첫 캡처 전에 `delay_sec`만큼 기다립니다(로그 `CAPTURE_SETTLE`). 리더가 느리면 `delay_sec`를
올리세요.

---

## 5. run 옵션 요약

### 출력

| 옵션 | 의미 |
|------|------|
| `--images` / `--pdf` / `--text` | 출력 타입 (하나만) |
| `--output images\|pdf\|text` | 위와 동일 |
| `--style full\|prose\|raw` | Markdown 스타일 (`--text`) |
| `-y`, `--yes` | 확인 생략 |

### 책 · 설정

| 옵션 | 설명 |
|------|------|
| `--config` | JSON/JSONC 설정 |
| `--reader` | 리더 프로필 이름 |
| `--title` | 책 폴더명 |
| `--base-dir` | 출력 상위 (**절대 경로**) |
| `--pages` / `--start-page` | 페이지 수 / 시작 번호 |
| `--input-pdf` | `--text`용 PDF 소스 |

### 캡처

| 옵션 | 설명 |
|------|------|
| `--capture-mode` | `manual` \| `window_*` \| `screen_left_third` |
| `--window-title` | 창 제목 부분 일치 |
| `--active-window` | 현재 활성 창 사용 |
| `--delay` | 페이지 넘긴 뒤 대기(초) |
| `--next-key` | `pagedown` \| `right` \| … |
| `--key-delivery` | `auto` \| `sendinput` \| `pyautogui` \| … |

### OCR · 재개

| 옵션 | 설명 |
|------|------|
| `--ocr-engine google\|datalab` | OCR 백엔드 (기본 google = Gemini) |
| `--datalab-mode fast\|balanced\|accurate` | Datalab 정확도 (기본 accurate) |
| `--ocr-workers N` | OCR 동시 요청 수 (1-16, 기본 1) |
| `--ocr-lang` | 예: `kor`, `eng` (Gemini만) |
| `--ocr-prompt` / `--ocr-prompt-file` | Gemini 프롬프트 |
| `--resume` / `--no-resume` | 완료 페이지 건너뛰기 |
| `--force-phase capture\|ocr\|pdf\|all` | 해당 단계 강제 재실행 |

전체 목록: `python -m ebook_capture run --help`

---

## 6. 설정 파일

설정을 둘로 나눕니다.

| 파일 | 역할 |
|------|------|
| `default_config.jsonc` (책) | 제목·쪽수·출력·resume 등 **이번 잡** |
| `reader_profiles.jsonc` (리더) | 클릭·키·delay·`pdf_trim` 등 **리더 동작** |

번들 책 기본: `default_config.jsonc` (없으면 `default_config.json`).  
리더 동작은 `reader_profile` 이름 또는 CLI `--reader`로 고릅니다.

### 책 config에 두는 필드

| 필드 | 설명 |
|------|------|
| `title`, `base_dir`, `n_pages`, `start_page` | 책·경로 |
| `output_mode` | `images` \| `pdf` \| `text` |
| `reader_profile` | 예: `kindle_app` / `aladin_app` (이름만) |
| `target_window_title` | (선택) Aladin처럼 **창 제목이 책 이름**일 때 책 config에 둠 |
| `resume`, `force_phase` | 재개 / 강제 |
| `ocr_lang`, `assemble_style` | text 모드 |

### 리더 config에 두는 필드 (`reader_profiles.jsonc`)

`capture_mode`, `target_window_title`, `next_key`, `key_delivery`, `delay_sec`,  
`reader_focus_*`, `fit_on_start`, `pdf_trim`, `window_capture_backend` 등.

우선순위: **개별 CLI 플래그 > `--reader` / `reader_profile` > 책 config**.

PDF 여백(`pdf_trim`)은 리더 프로필에 둡니다. crop + 선택적 white-fill:

```json
"pdf_trim": {
  "left": 0.0, "right": 0.0,
  "top": 0.01, "bottom": 0.045,
  "fill_top": 0.026, "fill_bottom": 0.0
}
```

---

## 7. 출력 경로

```text
{base_dir}/{title}/
  tmp/{title}_0001.png
  tmp/{title}_0001.ocr.json
  {title}.pdf
  {title}.md
  {title}_structure.json
  capture_state.json
```

중단 후 **같은** `--start-page` / `--pages`(보통 1부터 전체 권수)로 다시 실행하면,
이미 있는 PNG는 건너뛰고 빈 페이지만 이어서 캡처한 뒤 PDF를 만듭니다 (`resume`).  
`--start-page`를 이어갈 번호로 바꾸지 마세요 — 파일 번호 범위가 잘려 PDF에 앞 페이지가 빠지거나,
뒤 페이지만 대상으로 잡힙니다.

```powershell
# 예: 1–146까지 있고 전체 292쪽을 이어서 끝내려면
python -m ebook_capture run --config default_config.jsonc --reader kindle_app --pdf --start-page 1 --pages 292 -y
```

캡처를 이어갈 때는 **리더가 다음에 찍을 페이지**(예: 147)에 맞춰 두세요.

---

## 8. OCR용 환경 변수

`.env.example`을 `.env`로 복사한 뒤:

```env
GOOGLE_API_KEY=...
GOOGLE_OCR_MODEL=gemini-2.5-flash
GOOGLE_API_TRUST_MODE=auto
```

| `GOOGLE_API_TRUST_MODE` | 언제 |
|-------------------------|------|
| `auto` | 기본 |
| `system` | 사내망 / Windows 인증서 |
| `certifi` | 일반 인터넷 |

추가 CA: `GOOGLE_API_CA_BUNDLE=회사루트.cer` (Datalab 호출도 같은 CA 설정을 씁니다)

Datalab(`--ocr-engine datalab`): `DATALAB_API_KEY=...` (https://www.datalab.to 발급, 선불 크레딧). 환경변수 → `.env` 순으로 찾고 자리표시자 `your-datalab-api-key-here`는 없는 것으로 봅니다.

OCR(`--text`)을 쓸 때만 필요합니다. `--images` / `--pdf`만이면 API 키 없이 동작합니다.

---

## 9. 진단

```powershell
# 창이 left-third에 맞는지, 캡처 rect 확인
python -m ebook_capture inspect --config default_config.jsonc

# 키 한 번(또는 여러 번)만 보내기
python -m ebook_capture test-key --config default_config.jsonc --reader kindle_app --repeat 3
```

---

## 10. 예시 모음

```powershell
# 기본 PDF
python -m ebook_capture run --config default_config.jsonc --pdf -y

# Aladin 프로필
python -m ebook_capture run --config default_config.jsonc --reader aladin_app --pdf -y

# OCR만 다시 (기존 PNG 유지)
python -m ebook_capture run --config default_config.jsonc --text --force-phase ocr -y

# 처음부터 다시 캡처
python -m ebook_capture run --config default_config.jsonc --pdf --no-resume -y
```
