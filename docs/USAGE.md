# ebook_capture 사용법

화면(또는 지정 창)을 연속 캡처해 **PNG**, **이미지 PDF**, 또는 **OCR Markdown**을 만듭니다.  
설치·개요: [README.md](../README.md) · 동작 규칙·문제 해결 카탈로그: [ARCHITECTURE.md](ARCHITECTURE.md) · 지금 상태: [CONTEXT.md](CONTEXT.md)

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
| **text** | `*.ocr.json` + `{title}.md` | OCR → Markdown (Gemini / Claude Vision / Datalab) |

`--text`는 OCR과 Markdown 조립까지 한 번에 합니다.  
소스 우선순위: `--input-pdf`(명시) → 이미 있는 PNG → 책 폴더의 PDF → (없으면) 화면 캡처.  
만든 Markdown은 웹 리더로 읽습니다: [reader/README.md](../reader/README.md).

---

## 2. 명령

| 명령 | 용도 |
|------|------|
| `gui` | 그래픽 인터페이스 |
| `run` | 캡처 / PDF / OCR 실행 |
| `monitors` | 모니터 번호·해상도 (`--capture-monitor`용) |
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

### OCR 엔진 고르기

| `--ocr-engine` | 특징 | 키 |
| --- | --- | --- |
| `google` (기본) | Gemini. 프롬프트·`--ocr-lang` 사용 | `GOOGLE_API_KEY` |
| `anthropic` | Claude Vision (기본 `claude-haiku-4-5-20251001`, `--anthropic-ocr-model`로 변경) | `ANTHROPIC_API_KEY` |
| `datalab` | [Datalab](https://www.datalab.to)(호스팅 Marker). 유형이 붙은 레이아웃 블록을 받아 수식·그림·표·코드를 살림. 프롬프트·`--ocr-lang`은 무시 | `DATALAB_API_KEY` |

어느 엔진이든 결과는 같은 `tmp/*.ocr.json` 형식이고, 그 뒤 조립은 같습니다. 수식·그림·표·제목이 Markdown에서 어떻게 되는지는 [ARCHITECTURE §8](ARCHITECTURE.md#8-markdown-조립-규칙).

Datalab 메모:

- 입력은 `tmp/*.png`(캡처 결과) 또는 `--input-pdf`(한 쪽씩 잘라 PDF 그대로 전송). 둘 다 쪽당 1건 요청이며 실측 accurate 모드 약 1센트/쪽, 쪽당 10초 안팎.
- `--ocr-workers N`(1-16): 동시 요청 수. Datalab은 요청마다 큐에 서므로 4-8이면 벽시계 시간이 그만큼 줄고 비용은 같습니다. 429/연결 끊김은 Retry-After로 물러나 재시도합니다.
- 실패한 쪽은 `OCR_PAGE_FAIL`로 남기고 나머지를 계속합니다. 끝에 `OCR_FAIL n page(s)`가 찍히면 같은 명령을 다시 실행하면 빠진 쪽만 채웁니다(완료된 쪽은 `OCR_SKIP`).
- `OCR_COST datalab pages=N usd=X`: 응답의 `cost_breakdown.final_cost_cents` 합계(단위 센트 → 달러).
- `--datalab-mode fast|balanced|accurate`(기본 accurate). `fast`는 PDF 텍스트 레이어를 긁어 인라인 수식을 놓칩니다.

### 오타 교정

- 조립할 때 사전(`ocr_typos.txt`, 프로젝트 루트와 책 폴더)으로 한글 어절을 고칩니다. 내역은 `{title}_typo_fixes.txt`, 끄려면 `--no-typo-fix`
- `--proofread`를 주면 Claude가 쪽마다 OCR 오인을 찾아 고칩니다(유료, 266쪽 약 $1). 고친 것과 거부한 것 모두 같은 내역 파일에 남고, `tmp/*.proof.json`에 캐시되어 재조립은 무료입니다
- `--typo-freq`(책 안 빈도 추정)는 오탐이 많아 권하지 않습니다

필요한 중간 파일이 없으면 **실행할 단계 목록**을 보여 주고 `Proceed? [Y/n]`으로 묻습니다.  
스크립트·GUI는 `-y` / `--yes`로 건너뜁니다.

---

## 4. 리더 프로필

리더마다 페이지 넘김·포커스 클릭이 다릅니다. 프로필로 한 번에 맞춥니다.

| 프로필 | 대상 | 넘김 키 / 전달 | 포커스 클릭 | PDF 자르기 |
|--------|------|----------------|-------------|------------|
| `kindle_app` | Kindle 데스크톱 (**검증 기준선**) | right / sendinput | 0 (API 포그라운드만. 클릭은 본문 링크를 눌러 점프를 일으킴) | top 0.035 |
| `kindle_cloud` | Kindle Cloud Reader (브라우저) | right / pyautogui | 2 @ 중앙 | 없음 (미측정) |
| `aladin_app` | 알라딘 ebook 앱 | pagedown / sendinput | 2 @ 중앙 | top 0.010, fill_top 0.026, bottom 0.045 |
| `aladin_web` | 알라딘 웹 뷰어 (Chrome) | **wheeldown** (휠 1칸) / pyautogui | 0 (본문 클릭은 메뉴 토글) | top 0.058, bottom 0.040 |
| `rdp_full` | 원격 데스크톱(mstsc) 창 안의 리더 | right / sendinput | 0 (API 포그라운드) | 자동 윤곽 + fill_left 0.01, fill_bottom 0.05 |

프로필별 실기 검증 여부는 [CONTEXT §2](CONTEXT.md).

`rdp_full`은 다른 프로필과 루프가 다릅니다. 원격 리더는 세션 안에서 전체 화면으로 띄우고,
로컬에서는 mstsc 창을 모니터 높이에 맞춰 둡니다 (2026-10-10 검증: client 1438x1761).

| 항목 | 값 | 이유 |
|------|----|------|
| `keep_pointer_outside` | true | 포인터가 원격 리더 위를 지나면 hover 툴바가 뜸. 창 옆에 세워 두고 되돌리지 않음 |
| `settle_stable_sec` / `settle_max_sec` | 0.4 / 4.0 | 키 입력 후 페이지 넘김 바가 사라질 때까지 연속 두 장이 같아질 때까지 재촬영 |
| `page_turn_retries` | 2 | 화면이 안 바뀌면(포커스 이탈로 키 유실) 재포그라운드 + 키 재전송 후 재촬영 |
| `pdf_auto_crop` | true | 고정 `pdf_trim` 대신 캡처 완료 후 페이지 공통 윤곽을 뽑아 crop. 끝까지 남은 리더 툴바도 걸러냄(동작은 [ARCHITECTURE §7](ARCHITECTURE.md#pdf-자르기)). 로그 `PDF_AUTO_CROP`, 끄려면 `--no-pdf-auto-crop` |
| `prevent_sleep` | true (config 기본) | 캡처 중 화면 보호기·디스플레이 끄기 차단 (`SetThreadExecutionState`) |
| `--sub-left/--sub-top/--sub-width/--sub-height` (`window_subrect`) | 책마다 | 창 client 영역 중 리더 페이지 부분만 캡처. 원격 세션이 전체 화면(3840x2160)이고 리더가 일부만 차지할 때 사용. 좌표는 `inspect --screenshot`의 probe 기준(물리 픽셀, run과 동일 DPI 모드). width/height 0 = 끝까지. 2026-10-22 검증: 4K 세션 리더 `--sub-left 2 --sub-top 81 --sub-width 1277 --sub-height 1975` |
| `--pdf-auto-crop-margin` (`pdf_auto_crop_margin`) | 0.0 | 감지한 윤곽을 사방으로 이 비율만큼 넓힘. 본문이 윤곽 끝까지 꽉 차는 리플로우 책(권력중독: 글자 끝 = 크롭선)은 0.005 정도를 주면 안티앨리어싱이 안 잘림 |
| `stop_repeat_tolerance` | 0.3 (config 기본) | 회색 썸네일 평균 차이가 이 값 이하면 같은 페이지로 봄. 리더 오버레이(화살표 등)는 ~0.003, 실제 넘김은 4 이상. 책 끝 감지와 키 재전송 판단에 공통 사용. 0.0 = 완전 일치 |

프로필이 따로 정하지 않으면 쓰는 공통값(`_proven_capture_defaults`):

| 항목 | 기본 | 설명 |
|------|------|------|
| `fit_on_start` | 끔 | 시작 시 창 resize 안 함 (미리 배치) |
| `start_focus_clicks` | 0 | 시작 시 포커스 클릭 없음 |
| `reader_focus_clicks` | 2 | 캡처 **직전** 본문 클릭 (`kindle_app`·`aladin_web`·`rdp_full`은 0) |
| `reader_focus_x_ratio` / `_y_ratio` | 0.5 / 0.5 | 클릭 위치 (본문 중앙) |
| `focus_click_settle_sec` | 1.0 | 클릭 후 오버레이 사라질 대기 |
| `pdf_trim` | 프로필마다 (`reader_profiles.jsonc`) | crop + optional white-fill |

페이지마다 "본문 클릭 → 포인터 대피·대기 → 캡처 → 넘김 키"를 반복합니다(세부는 [ARCHITECTURE §5.3](ARCHITECTURE.md#53-페이지-루프-pipeline_run_phase_capture)). 클릭 위치는 중앙이 안전합니다. 상단은 툴바, 좌우 가장자리는 페이지 이동 영역입니다. 클릭 간격은 더블클릭 시간보다 길게 벌려 보내므로 `reader_focus_clicks: 2`도 줌이 되지 않습니다.

`pdf_trim`의 `left/right/top/bottom`은 잘라내고, `fill_*`는 잘라내지 않고 그 띠만 흰색으로 덮어 여백을 유지합니다. 값은 캡처 크기에 대한 비율이라, 창 높이를 크게 바꿨다면 다시 측정하세요. 책 config의 `pdf_trim`은 프로필 값에 덮이므로 측정값은 프로필에 넣습니다.

```powershell
ebook-capture run --config default_config.jsonc --reader kindle_app -y
ebook-capture test-key --config default_config.jsonc --reader aladin_app
```

- GUI **Reader** 콤보 = 동일 동작
- 정의 파일: `reader_profiles.jsonc` (직접 수정·추가 가능)
- 개별 옵션(`--next-key` 등)이 프로필보다 **우선**

### 문제 해결

자주 겪는 경우만 적습니다. 원인과 코드 쪽 해결은 [ARCHITECTURE §12](ARCHITECTURE.md#12-발견한-문제--해결책).

#### 줌·메뉴가 뜨거나 엉뚱한 쪽으로 점프할 때

포커스 클릭이 원인입니다. Cloud Reader는 상단을 클릭하면 Aa/줌 툴바가, Kindle 앱은 이미지를 두 번 누르면 줌이, 본문 링크를 누르면 점프가 일어납니다. `reader_focus_clicks`를 0으로 두고(키만 보냄) 시작 전에 본문을 한 번 직접 클릭해 두세요.

#### 페이지가 안 넘어갈 때

`--debug-capture`를 붙이면 키를 보낸 뒤 화면이 실제로 바뀌었는지 로그로 알려줍니다.

```powershell
python -m ebook_capture run --config default_config.jsonc --reader kindle_app --pages 4 --debug-capture -y
```

`DEBUG_KEY_EFFECT meandiff=... (page moved)`면 정상, `NO VISIBLE CHANGE`면 키가 리더에
전달되지 않았거나 리더가 무시한 것입니다. 후자라면 `key_delivery`를 `pyautogui`로 바꿔
보세요. 웹 뷰어가 키를 아예 무시하면 `--next-key wheeldown`(캡처 영역 중앙에서 휠 1칸)을 쓰세요. 캡처 중에는 다른 창을 클릭하지 마세요. 리더가 포그라운드에서 벗어나면 다시
활성화하는 과정에서 페이지 넘김이 한 번 빠질 수 있습니다.

#### 첫 페이지가 로딩 화면으로 찍힐 때

첫 캡처 전에 `delay_sec`만큼 기다립니다(로그 `CAPTURE_SETTLE`). 리더가 느리면 `delay_sec`를
올리세요.

---

## 5. run 옵션 요약

### 출력

| 옵션 | 의미 |
|------|------|
| `--images` / `--pdf` / `--text` | 출력 타입 (하나만) |
| `--next-key` | 넘김 키. `pagedown`·`right` 등 키 이름 또는 `wheeldown`/`wheelup` (캡처 영역 중앙에서 휠 1칸, 키 입력을 무시하는 웹 뷰어용) |
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
| `--window-title` | 창 제목 부분 일치 (`--window-match-first`: 여럿이면 첫 창) |
| `--window-capture-backend` | `printwindow` \| `screen` |
| `--sub-left/--sub-top/--sub-width/--sub-height` | 창 client 안 부분 영역만 캡처 (`rdp_full` 참고) |
| `--capture-scale F` / `--capture-monitor N` | 캡처 전 리더 창을 F배로 키움(비율 유지) / 그 모니터에 배치 (`monitors`로 번호 확인) |
| `--debug-capture` / `--debug-max-pages N` | 키 효과 로그(`DEBUG_KEY_EFFECT`) / N쪽까지만 |
| `--active-window` | 현재 활성 창 사용 |
| `--delay` | 페이지 넘긴 뒤 대기(초) |
| `--next-key` | `pagedown` \| `right` \| … |
| `--key-delivery` | `auto` \| `sendinput` \| `pyautogui` \| … |

### OCR · 재개

| 옵션 | 설명 |
|------|------|
| `--ocr-engine google\|anthropic\|datalab` | OCR 백엔드 (기본 google = Gemini) |
| `--anthropic-ocr-model` | Claude Vision 모델 (기본 `claude-haiku-4-5-20251001`) |
| `--datalab-mode fast\|balanced\|accurate` | Datalab 정확도 (기본 accurate) |
| `--ocr-workers N` | OCR 동시 요청 수 (1-16, 기본 1) |
| `--no-typo-fix` | 조립 시 OCR 오타 사전 보정 끄기. 기본은 켜짐, 내역은 `{title}_typo_fixes.txt` |
| `--typo-freq` | 책 안 빈도로 오타 추정까지 적용(오탐 많음, 내역 검토 필수) |
| `--proofread` | Claude로 쪽마다 OCR 오인 교정(유료, `ANTHROPIC_API_KEY`). 모델은 교정 목록만 돌려주고 로컬에서 검증 후 적용. `tmp/*.proof.json`에 캐시되어 재조립은 무료 |
| `--proofread-model` | `--proofread` 모델 (기본 `claude-opus-5-5`) |
| `--ocr-lang` | 예: `kor`, `eng` (Gemini만) |
| `--ocr-prompt` / `--ocr-prompt-file` | Gemini 프롬프트 |
| `--resume` / `--no-resume` | 완료 페이지 건너뛰기 |
| `--force-phase capture\|ocr\|pdf\|all` | 해당 단계 강제 재실행 |

### PDF

| 옵션 | 설명 |
|------|------|
| `--pdf-auto-crop` / `--no-pdf-auto-crop` | 공통 윤곽 자동 crop 켜기/끄기 (프로필 값보다 우선) |
| `--pdf-auto-crop-margin R` | 감지한 윤곽을 사방으로 R(0–0.2)만큼 넓힘 |
| `--pdf-page-margin R` | PDF 쪽 사방에 흰 여백 R(0–0.2) 추가 |

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
  {title}_typo_fixes.txt        # 오타 교정 내역 (text)
  assets/<sha1>.jpg|png         # 그림 (Datalab)
  {title}.notes.json            # 웹 리더의 주석 (리더가 씀)
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

추가 CA: `GOOGLE_API_CA_BUNDLE=회사루트.cer` (Claude·Datalab 호출도 같은 CA 설정을 씁니다). Windows 루트 저장소에서 `certutil -store Root <sha1> 회사루트.cer`로 내보낼 수 있습니다.

Claude(`--ocr-engine anthropic`, `--proofread`): `ANTHROPIC_API_KEY=...`

Datalab(`--ocr-engine datalab`): `DATALAB_API_KEY=...` (https://www.datalab.to 발급, 선불 크레딧). 환경변수 → `.env` 순으로 찾고 자리표시자 `your-datalab-api-key-here`는 없는 것으로 봅니다.

OCR(`--text`)을 쓸 때만 필요합니다. `--images` / `--pdf`만이면 API 키 없이 동작합니다.

---

## 9. 진단

```powershell
# 모니터 번호
python -m ebook_capture monitors

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
