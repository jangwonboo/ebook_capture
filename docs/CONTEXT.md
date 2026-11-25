# CONTEXT — 지금 상태와 할 일 (다음 세션용)

기준일: 2026-11-25  
이 파일은 "지금 무엇이 되고, 무엇이 안 되었고, 다음에 무엇을 할지"만 담는다. 동작 규칙과 함정은 [ARCHITECTURE.md](ARCHITECTURE.md), 날짜별 실행 기록은 [HISTORY.md](HISTORY.md), 사용법은 [USAGE.md](USAGE.md).

---

## 1. 한눈에

| 영역 | 상태 |
| --- | --- |
| 캡처 → PDF | Kindle 앱, 알라딘 웹(Chrome), 원격 데스크톱 리더에서 실제 책 전권 캡처 완료 |
| OCR → Markdown | Datalab(4권), Claude Vision(1권) 실사용. 장 구조·수식·그림·표·코드 조립 검증 |
| 오타 교정 | 사전 + LLM 교정(`--proofread`) 실사용, 표본 대조에서 오교정 0 |
| 쪽 경계·두 줄 제목 복원 | 파이프라인(`seam_repair`)과 리더 양쪽에 구현. 실제 책 재조립으로는 미검증 (§5-2) |
| 웹 리더 | 목차·본문·검색·주석·주석 파일·AI 문답 구현. 실제 API 키와 실제 폴더 저장은 미검증 (§5-1) |
| 테스트 | `pytest` 191 통과, 6 건너뜀(실제 책 OCR이 있어야 도는 회귀 테스트) |

---

## 2. 리더 프로필 검증 현황

값은 [USAGE §4](USAGE.md#4-리더-프로필).

| 프로필 | 실기 검증 | 근거 |
| --- | --- | --- |
| `kindle_app` | ✅ | 2026-07-25 루프 확정. 이후 포커스 클릭을 0으로(본문 링크 점프 방지) |
| `rdp_full` | ✅ | 2026-10 네 권(320·505·823·243쪽). 포커스 이탈 재시도, 부분 영역, 자동 윤곽 실측 |
| `aladin_web` | ✅ | 2026-11-24 비트겐슈타인 233쪽 전권. 휠 넘김 |
| `aladin_app` | ❌ | 2026-11-17 재캡처 시도에서 첫 장 뒤 넘김 실패(HISTORY). SendInput 적합성 미확인 |
| `kindle_cloud` | ❌ | 실기 미검증, `pdf_trim` 미측정 |

---

## 3. 웹 리더 현황

상세 스펙과 결정 사항은 [reader/SPEC.md](../reader/SPEC.md).

- 구현: 목차 트리, 장 단위 본문, 검색, 위치 저장, 글꼴·크기·테마, 폴더 열기(이미지 링크), 하이라이트·메모·태그·필터, `<책>.notes.json` 저장, Markdown/JSON 내보내기, AI 문답(근거 연결, 채택)
- 결정(2026-11-25): 서버 없음, 브라우저가 Anthropic API 직접 호출(키는 설정에서 입력), 기본 모델 Claude Sonnet 5.5, AI에 넘기는 범위는 "이 장", 주석 파일은 책 폴더, OCR 교정은 파이프라인에서
- 검증: 헤드리스 Chrome에서 실제 입력으로 전 기능 확인. AI는 실제 SDK로 요청을 보내고 응답만 가짜로 돌려줌. 실제 API는 가짜 키로 401까지

---

## 4. 저장소·작업 환경

- 저장소: `https://github.com/jangwonboo/ebook_capture`. 메인 checkout `D:\projects\ebook_capture`(`main`), 이 작업은 worktree `D:\orca\ebook_capture\visual_ebook`(`visual_ebook` 브랜치)
- 저장소 루트가 곧 Python 패키지다. `D:\projects`에서 `python -m ebook_capture …`로 실행한다. venv는 uv로 만들고 pip는 없다
- **메인 checkout에 커밋 안 된 변경이 있다**(2026-11-25 확인): `CONTEXT.md`, `core/datalab_ocr.py`, `core/section_normalize.py`. 이 브랜치에서 `CONTEXT.md`를 `docs/`로 옮겼으므로, 그쪽을 커밋하고 합칠 때 `CONTEXT.md` 내용은 손으로 옮겨 적어야 한다
- Git Bash에서 Windows 경로는 따옴표로 감싸거나 슬래시로 쓴다(`D:\ebook` → `D:ebook` 사고 기록 있음)

---

## 5. 할 일 (우선순위 순)

### 바로

1. **리더 AI 문답을 실제 키로 확인**: 설정에 키를 넣고 한 번 질문한다. 근거 버튼이 맞는 문단으로 가는지, 같은 장에서 이어 물을 때 캐시 읽기 토큰이 찍히는지 본다. Chrome에서 "폴더 열기"로 연 책이 `<책>.notes.json`을 실제로 쓰는지도 확인
2. **쪽 경계 복원을 실제 OCR로 확인**: `D:\ebook\비트겐슈타인`에는 `.md`와 PDF만 있고 `tmp/*.ocr.json`이 없다. OCR JSON이 남은 다른 책으로 재조립해 `seam_repair`가 붙이고 띄운 곳을 대조하거나, 이 책을 다시 OCR한다
3. **재조립 전용 플래그**: 조립 규칙만 바뀌었을 때 `--text`는 "Nothing to do"로 끝난다. 지금은 `assemble_markdown()`을 직접 부른다

### 다음

4. **LLM 교정을 문단 병합 뒤로**: 쪽 단위라 쪽 경계에 걸친 오탈자("‘어" + "평게" → "어떻게")를 못 잡는다
5. **`aladin_app`, `kindle_cloud` 실기 스모크**

   ```powershell
   python -m ebook_capture run --config default_config.jsonc --reader aladin_app   --pdf --pages 4 --debug-capture --title aladin_app_smoke -y
   python -m ebook_capture run --config default_config.jsonc --reader kindle_cloud --pdf --pages 4 --debug-capture --title cloud_smoke -y
   ```

   성공 기준: 매 키 `DEBUG_KEY_EFFECT … (page moved)`, 이미지에 툴바·화살표 없음. 실패하면 ARCHITECTURE §12.12 진단 절차. 통과하면 `pdf_trim`을 측정해 프로필에 넣고, `aladin_app` `target_window_title`을 확정
6. **리더 4단계**: 복습 보기, 장을 다 읽었을 때 칠한 문장으로 질문 만들기, 주석 패널 너비 조절 (SPEC §10)

### 보류·선택

7. 알라딘 웹 뷰어가 주입 키를 무시하는 원인(물리 키보드는 됨). 휠로 우회 중이라 급하지 않음
8. 남은 조립 흠: 그림 제목이 본문 중간에 큰 글자로 선 경우 `###`로 남음(권력중독 2건), 차례 쪽 `03 부`/`04 부`가 `###`(마스터링 트랜스포머), 파이프 표 셀의 `\|` 이스케이프가 수식 안에도 들어감
9. GUI: Reader 콤보가 새 필드(`focus_click_settle_sec`, focus ratio, settle 계열)를 반영하는지, resume 토글
10. `pipeline.py` mock 테스트, Windows CI
11. 예전 스모크 폴더 정리: `E:\ebook\kindle_verify_*`

---

## 6. 다음 세션 시작할 때

- 먼저 `git status`와 `git log --oneline -5`로 이 브랜치와 `main`의 차이를 본다
- 캡처를 다시 돌리기 전에 `tmp`에 이전 PNG가 있는지 본다(resume이 건너뛴다). 새로 찍으려면 `--force-phase capture` 또는 `--no-resume`
- 문서를 고칠 때는 ARCHITECTURE §11의 "한 내용은 한 곳에만" 규칙을 따른다. 실행 결과는 HISTORY에 추가하고, 여기에는 상태와 할 일만 갱신한다
