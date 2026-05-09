# ebook_capture

화면의 고정 영역을 연속 캡처해 PNG를 모으고, Google Gemini OCR 텍스트/좌표를 추출한 뒤 검색 가능한 PDF와 선택적 Google Cloud TTS 오디오를 만드는 도구입니다.

## 프로젝트 구성

```
__main__.py                    # python -m ebook_capture 진입점(상위 폴더 실행용)
ebook_capture.py               # python -m ebook_capture 진입점(프로젝트 루트 실행용)
cli.py                         # argparse: gui | capture
assets/
  capture.ui                   # Qt Designer UI (실행 시에는 ui_capture.py 코드 경로 사용)
  default_config.json          # GUI 기본 옵션(CaptureConfig 스키마); 수정 시 재실행에 반영
  ocr_lang.csv                 # Google OCR 언어 힌트 목록
  voice_lang.csv               # Google TTS 음성 목록
core/
  config.py                    # CaptureConfig(JSON 직렬화)
  google_ocr.py                # Google Gemini API 기반 OCR
  pipeline.py                  # 캡처·OCR·검색 PDF·음성 (Qt 없음 → CLI 전용 적합)
  searchable_pdf.py            # 이미지 배경 + OCR text layer PDF 생성
  tts.py                       # 음성 합성·MP3 병합 (선택 의존성)
gui/
  app.py                       # 메인 다이얼로그; 작업 시 CLI 서브프로세스 실행
  theme.py                     # qt-material (Material Design 스타일)
  ui_capture.py                # capture.ui에서 생성된 위젯 코드
  snipping.py                  # 영역 선택(SnippingWidget)

legacy/                        # 이전 실험·중복 스크립트·미사용 QSS/CSS 등 (참고용)
```

### 설계 요약

| 레이어 | 역할 |
|--------|------|
| **core** | `pyautogui`/Win32 캡처, Pillow/PyPDF2/reportlab/Google Gemini OCR 처리. GUI 없이 동작. |
| **cli** | `capture`: 플래그 또는 `--config` JSON으로 `run_capture()` 실행. `gui`: PyQt 창 실행. |
| **gui** | 옵션을 모아 임시 JSON을 쓰고 `python -m ebook_capture capture --config <파일>`을 **서브프로세스**로 실행합니다. 캡처 로직은 CLI와 동일한 코드 경로를 사용합니다. |

## 설치

```bash
cd /path/to/ebook_capture
pip install -e .
# 음성 출력까지 쓰려면:
pip install -e ".[voice]"
```

Python **3.10+** 권장.

## 사용법

### GUI

```bash
python -m ebook_capture gui
# 또는 (editable 설치 후)
ebook-capture gui
```

1. **Folder**: 출력 상위 폴더(절대 경로, 예: `D:/books`).
2. **Title**, **Pages**: 책 제목과 페이지 수. Title을 비우면 `unknown`을 사용합니다.
3. **Target → Region**: 데스크톱에서 캡처할 직사각형 선택.
4. **Next** 콤보: 페이지 넘김에 쓸 키(`pyautogui.press` 이름과 동일한 계열).
5. **Output**: `Images only`, `PDF (image)`, `Text (OCR)`, `PDF (searchable)`, `Audio (TTS from OCR)` 중 선택. 기본은 image PDF입니다.
6. **Start**: 위 설정으로 임시 JSON을 만들고 CLI 프로세스를 띄웁니다. 로그는 창 하단 텍스트에 표시됩니다.

**Browse / Save Options / Load Options** 버튼으로 출력 폴더 선택·설정 JSON 저장·불러오기가 가능합니다.

GUI는 **`qt-material`** 로 Material Design 계열 다크 테마(`dark_blue`)를 적용합니다. 패키지가 없으면 Fusion 스타일로 동작합니다.

**기본 설정 파일**: `assets/default_config.json` 은 `CaptureConfig` 와 동일한 JSON 스키마입니다. GUI는 시작 시 이 파일을 읽어 위젯에 반영합니다. `base_dir` 가 비어 있으면 `~/Documents/ebook_capture_out` 으로 채웁니다. CLI 에서 직접 쓰려면 `base_dir` 에 절대 경로를 넣은 뒤 `python -m ebook_capture capture --config my.json` 으로 실행하면 됩니다. 코드에서 경로는 `core.config.bundled_default_config_path()` 로 얻을 수 있습니다.

### 창 기준 캡처 (Windows)

- **대상 앱**: 상단 그룹 «Target window & capture area» 에서 **Refresh windows** 로 상단 창 목록을 채운 뒤, Chrome·리디북스·알라딘·원격데스크톱 등 **제목이 보이는 항목**을 선택합니다.
- **영역**: 같은 그룹의 콤보에서 **전체 창**, **좌 1/3**, **우 1/3**(세로는 창 높이 전체)을 고릅니다. **Manual** 은 기존처럼 화면에서 직접 드래그합니다.
- **페이지**: **Start page #** 은 저장 파일명에 쓰일 첫 페이지 번호, **Page count** 는 연속 캡처할 장 수입니다 (예: 101부터 10장 → Start `101`, Count `10`).
- **다음 페이지**: 각 장의 스크린샷 직후·다음 키 입력 직전에 선택한 창을 앞으로 가져온 뒤 `Next`/`next_key` 를 보냅니다 (해당 창이 활성일 때 페이지가 넘어가도록).

CLI 예: `--capture-mode window_right_third --window-title "리디북스"` (제목은 목록과 동일해야 함). 창 모드는 **Windows + pygetwindow** 가 필요합니다.

### CLI (직접 실행)

JSON 설정 파일(GUI와 동일 형식):

```bash
python -m ebook_capture capture --config job.json
```

플래그만 사용(캡처 phase는 영역 필수):

```bash
python -m ebook_capture capture ^
  --title "MyBook" --pages 10 --base-dir D:/books ^
  --left 100 --top 100 --width 1200 --height 1600 ^
  --delay 0.4 --next-key pagedown ^
  --pdf-image --ocr-lang eng
```

단계별 재실행:

```bash
python -m ebook_capture capture --config job.json --phase ocr
python -m ebook_capture capture --config job.json --phase pdf
python -m ebook_capture capture --config job.json --force-phase ocr
```

주요 옵션:

| 옵션 | 설명 |
|------|------|
| `--config` | JSON을 먼저 읽고, **같은 명령에 준** `--title`, `--pages`, `--start-page`, `--base-dir` 등이 있으면 그 값으로 **덮어씀**. |
| `--title` | 책 제목. 생략하거나 빈 값이면 `unknown` 사용. |
| `--base-dir` | 임시 파일은 `<base-dir>/<title>/tmp/`, 최종 파일은 `<base-dir>/<title>/` 아래에 생성. |
| `--images` | PNG 캡처만 수행. |
| `--pdf-image` | PNG 캡처 후 일반 이미지 PDF 생성. 기본값. |
| `--text` | PNG 캡처 후 OCR 텍스트(`.txt`, `_ocr.txt`)만 생성. |
| `--pdf-searchable` | PNG 캡처 후 OCR JSON과 검색 가능한 PDF 생성. |
| `--audio` | PNG 캡처 후 OCR 텍스트 기반 MP3 생성. |
| `--output-mode` | 위 모드를 값으로 직접 지정: `images`, `text`, `pdf_image`, `pdf_searchable`, `audio`. |
| `--phase` | `capture`, `ocr`, `pdf`, `all` 중 실행할 단계 선택. |
| `--resume` / `--no-resume` | `capture_state.json`과 기존 산출물 기준으로 완료된 페이지를 건너뛰거나 재처리. |
| `--force-phase` | `capture`, `ocr`, `pdf`, `voice`, `all` 중 지정 phase를 강제 재생성. |
| `--next-key` | `pyautogui.press()`에 넘기는 키 이름(예: `pagedown`, `space`, `enter`). |
| `--no-images` | 이미 캡처된 PNG만으로 이후 단계만 실행. |
| `--no-pdf` | 레거시 옵션: Phase III PDF 생략. 새 작업에는 `--images` 또는 `--text` 권장. |
| `--ocr` | 레거시 옵션: Google Gemini OCR로 페이지별 `.txt`, `.ocr.json` 및 통합 `*_ocr.txt` 생성. 새 작업에는 `--text` 또는 `--pdf-searchable` 권장. |
| `--voice` | 페이지 텍스트를 MP3로 합성 후 `_voice.mp3`로 병합(`pip install .[voice]` 및 GCP 자격 필요). |

저장 경로:

- 페이지 PNG/TXT/OCR JSON: `<base-dir>/<title>/tmp/<title>_0001.*`
- 페이지 searchable PDF 조각: `<base-dir>/<title>/tmp/<title>_0001.searchable.pdf`
- 페이지 일반 PDF 조각(일반 PDF 모드): `<base-dir>/<title>/tmp/<title>_0001.page.pdf`
- 최종 PDF/TXT/MP3: `<base-dir>/<title>/<title>.pdf`, `<title>_ocr.txt`, `<title>_voice.mp3`
- resume 상태: `<base-dir>/<title>/capture_state.json`

PDF 변환 메모:

- 일반 PDF/검색 PDF 모두 PNG의 DPI 메타데이터를 읽어 PDF 페이지 크기를 계산합니다.
- 그래서 capture -> pdf 변환 시 이미지가 72 DPI 기준으로 강제 축척되는 문제를 줄이고, 원본 DPI 기반 물리 배율을 유지합니다.

전체 도움말: `python -m ebook_capture capture --help`

## 외부 도구·환경 변수

- **Google OCR** (`--ocr`): `.env` 또는 환경 변수에 `GOOGLE_API_KEY` 지정. `doc_metadata` 프로젝트와 동일하게 `python-dotenv` + `google.genai.Client(api_key=...)` 경로를 사용합니다.
  - 사내망: 기본 `GOOGLE_API_TRUST_MODE=auto` 가 Windows 인증서 저장소를 우선 사용합니다. 필요 시 `GOOGLE_API_CA_BUNDLE=<사내 CA .cer/.pem>` 추가.
  - open망: `GOOGLE_API_TRUST_MODE=certifi` 로 두면 공개 CA bundle만 사용합니다.
- **Google Cloud TTS** (`--voice`): 서비스 계정 JSON 경로를 `GOOGLE_APPLICATION_CREDENTIALS`에 지정. 레포에 하드코딩된 경로는 제거되었습니다.
- **개발 시 모듈 경로**: `pip install -e .` 없이 실행하면 `PYTHONPATH`에 저장소 루트를 추가해야 할 수 있습니다. GUI는 서브프로세스에 저장소 루트를 `PYTHONPATH`로 넣어 개발 편의를 둡니다.

## 특이사항

- 이전 코드베이스는 `main.py` / `run.py` / `utils.py` 등에 **전역 상태·중복 옵션 처리·하드코딩된 자격 증명**이 섞여 있었습니다. 현재 파이프라인은 `core/pipeline.py` 한 경로로 통합했습니다.
- **Kindle 전용 `pywinauto` 캡처**(`legacy/main_win.py` 등)는 레거시로 옮겼습니다. 현재 기본 흐름은 **화면 좌표 스크린샷**입니다.
- `legacy/qss`, `legacy/css`의 스타일시트는 Python 코드에서 로드되지 않았던 모음입니다.
- Windows 외 OS에서는 경로·키 입력 동작을 반드시 확인하세요.

## 라이선스

개별 파일에 다른 라이선스가 붙어 있을 수 있습니다(예: `legacy/qss/license`, 제3자 QSS). 새 패키지 코드는 프로젝트 정책에 맞게 정리하세요.
