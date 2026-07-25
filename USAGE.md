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
```

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

공통 기본값 (`kindle_app`에서 검증 후 전 프로필에 공유):

| 항목 | 기본 | 설명 |
|------|------|------|
| `fit_on_start` | 끔 | 시작 시 창 resize 안 함 (미리 배치) |
| `start_focus_clicks` | 0 | 시작 시 포커스 클릭 없음 |
| `reader_focus_clicks` | 2 | 캡처 **직전** 본문 클릭 |
| `reader_focus_x_ratio` / `_y_ratio` | 0.5 / 0.5 | 클릭 위치 (본문 중앙) |
| `focus_click_settle_sec` | 1.0 | 클릭 후 오버레이 사라질 대기 |
| `pdf_trim` | 0 (`kindle_app`만 top=0.032) | PDF 여백 crop (캡처 크기 **비율**) |

페이지 한 장의 처리 순서는 다음과 같습니다.

1. 본문 중앙을 `reader_focus_clicks`회 클릭 (리더 포커스 확보)
2. 포인터를 캡처 영역 밖으로 빼고 `focus_click_settle_sec` 대기 — 페이지 화살표·툴바가 사라짐
3. 이미지 캡처
4. `next_key` 전송 후 `delay_sec` 대기

클릭은 같은 지점을 연속으로 누르므로 시스템 더블클릭 시간(`GetDoubleClickTime`)보다 길게
벌려 보냅니다. 그래서 `reader_focus_clicks: 2`도 더블클릭(= Kindle 이미지 줌)이 되지 않습니다.
클릭 위치는 중앙이 안전합니다. 상단은 툴바, 좌우 가장자리는 페이지 이동 영역입니다.

`kindle_app`만 예외로 `pdf_trim.top = 0.032`입니다. Kindle 앱은 자기 상단 바(뒤로·설정·창
버튼, 약 48px)를 client 영역 안에 그리기 때문에 캡처에 항상 들어옵니다. 창 높이를 크게
바꿨다면 이 비율도 다시 맞추세요. 다른 리더의 `pdf_trim`은 첫 클린 캡처 후 측정해 넣으세요.

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
| `--ocr-lang` | 예: `kor`, `eng` |
| `--ocr-prompt` / `--ocr-prompt-file` | Gemini 프롬프트 |
| `--resume` / `--no-resume` | 완료 페이지 건너뛰기 |
| `--force-phase capture\|ocr\|pdf\|all` | 해당 단계 강제 재실행 |

전체 목록: `python -m ebook_capture run --help`

---

## 6. 설정 파일

번들 기본: `default_config.jsonc` (없으면 `default_config.json`).

자주 쓰는 필드:

| 필드 | 설명 |
|------|------|
| `output_mode` | `images` \| `pdf` \| `text` |
| `reader_profile` | 예: `kindle_app` |
| `title`, `base_dir`, `n_pages`, `start_page` | 책·경로 |
| `capture_mode`, `target_window_title` | 캡처 대상 |
| `next_key`, `key_delivery`, `delay_sec` | 페이지 넘김 |
| `fit_on_start`, `start_focus_clicks` | 시작 맞춤·포커스 |
| `pdf_trim` | `{ "left", "right", "top", "bottom" }` 비율 |
| `resume`, `force_phase` | 재개 / 강제 |
| `ocr_lang`, `assemble_style` | text 모드 |

CLI 플래그가 JSON 값을 덮어씁니다.

PDF 여백 예 (폭 1000px, `left: 0.02` → 20px 잘림):

```json
"pdf_trim": { "left": 0.02, "right": 0.02, "top": 0.03, "bottom": 0.03 }
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

추가 CA: `GOOGLE_API_CA_BUNDLE=회사루트.cer`

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
