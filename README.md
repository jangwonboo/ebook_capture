# ebook_capture

전자책 리더 화면을 연속 캡처해 **PNG**, **이미지 PDF**, **OCR Markdown**을 만들고, 만든 Markdown을 웹 리더 **Markdown Reader**로 읽는 도구입니다. 캡처는 CLI와 PyQt5 GUI, 리더는 설치 없는 브라우저 앱입니다.

## 문서

| 문서 | 읽을 사람 | 내용 |
| --- | --- | --- |
| [docs/USAGE.md](docs/USAGE.md) | 사용자 | 명령, 옵션, 리더 프로필, 설정, 출력 경로, 환경 변수, 문제 해결 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 개발자 | 요구사항, 구조, 단계별 규칙(Markdown 조립 포함), 발견한 문제·해결책 |
| [docs/CONTEXT.md](docs/CONTEXT.md) | 다음 세션 | 지금 상태, 검증 현황, 할 일 |
| [docs/HISTORY.md](docs/HISTORY.md) | 기록 | 날짜별 실행 기록 |
| [reader/README.md](reader/README.md) | 리더 사용자 | 웹 리더 사용법 |
| [reader/SPEC.md](reader/SPEC.md) | 리더 개발자 | 웹 리더 기획·스펙·결정 사항·남은 일 |

## 빠른 시작

```bash
pip install -e ".[dev]"      # 또는 uv
```

Python 3.10 이상, Windows 대상입니다. 저장소 루트가 곧 패키지라 저장소의 상위 폴더에서 실행합니다.

```powershell
python -m ebook_capture gui                                                   # GUI
python -m ebook_capture run --config default_config.jsonc --reader kindle_app --pdf -y
python -m ebook_capture run --title "My Book" --base-dir D:/ebook --text --ocr-engine datalab -y
```

| 출력 | 결과 |
| --- | --- |
| `--images` | `tmp/{title}_NNNN.png` |
| `--pdf` (기본) | PNG + `{title}.pdf` |
| `--text` | `*.ocr.json` + `{title}.md` |

웹 리더: `reader/index.html`을 Chrome에서 열고 "폴더 열기"로 책 폴더를 고릅니다.

OCR에는 `.env`에 키가 필요합니다(`.env.example` 참고): Gemini `GOOGLE_API_KEY`, Claude `ANTHROPIC_API_KEY`, Datalab `DATALAB_API_KEY`. 리더의 AI 문답 키는 리더 설정에서 따로 넣습니다.

## 폴더 구성

```text
__init__.py, __main__.py       패키지 진입점 (python -m ebook_capture)
ebook_capture.py, cli.py       설치형 진입점, 명령 (gui | monitors | run | test-key | inspect)
core/                          캡처 · OCR · PDF · Markdown 조립 (Qt 없음)
gui/                           PyQt5 옵션 화면 → run -y 서브프로세스
assets/                        OCR 프롬프트, 언어 CSV, Qt UI
tests/                         pytest (fixtures/에 샘플 OCR JSON)

default_config.json(c)         책 설정 (title, pages, output, reader_profile 이름)
reader_profiles.jsonc          전자책 뷰어별 동작 (키, 클릭, delay, pdf_trim)
ocr_typos.txt                  OCR 오타 사전 (공통)
.env.example                   API 키 예시

reader/                        웹 리더 Markdown Reader (index.html, app.js, notes.js, styles.css, 문서)
docs/                          USAGE · ARCHITECTURE · CONTEXT · HISTORY

pyproject.toml, uv.lock, requirements.txt
activate.cmd, run_tests.cmd    Windows: venv 활성화, 테스트 실행
```

코드와 기본 설정 파일은 패키지 구조와 `--config default_config.jsonc` 같은 사용법이 루트 위치를 전제하므로 루트에 둡니다.

## 라이선스

개별 파일에 다른 라이선스가 붙어 있을 수 있습니다. 새 패키지 코드는 프로젝트 정책에 맞게 정리하세요.
