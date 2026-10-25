# CONTEXT — ebook_capture handoff (다음 세션용)

작성일: 2026-07-25  
상태: **Kindle for PC (`kindle_app`) 캡처 루프 검증 완료.** 동일 파라미터를 다른 프로필에 전파해 둠.  
관련 문서: [USAGE.md](USAGE.md) · [REQUIREMENTS.md](REQUIREMENTS.md) §12 · [reader_profiles.jsonc](reader_profiles.jsonc)

---

## 0. 2026-10-10 추가: `rdp_full` (원격 데스크톱 창 캡처)

대상: mstsc 창("… - Remote Desktop Connection") 안에서 전체 화면으로 띄운 리더. `window_full` + `screen` 백엔드로 client 영역(1438x1761)을 그대로 찍는다. 3페이지 시험 캡처에서 `right`/SendInput으로 한 장씩 넘어감을 확인했다.

이번에 들어간 동작 (코드: `core/pipeline.py`, `core/auto_crop.py`, `core/windows_util.keep_display_awake`):

| 요구 | 구현 | 로그 키 |
|------|------|---------|
| 포커스가 나가도 캡처 유지 | 키 전송 실패 시 재포그라운드 후 재전송 (`page_turn_retries`), 화면이 전과 같으면 재포그라운드 + 키 재전송 + 재촬영 후에야 반복으로 간주 | `TARGET_KEY_RETRY`, `PAGE_TURN_RETRY*` |
| 상하단 바 없는 상태에서 캡처 | 포인터를 창 옆에 세워 두고 되돌리지 않음 (`keep_pointer_outside`); 연속 두 장이 같아질 때까지 재촬영 (`settle_stable_sec`/`settle_max_sec`) | `SETTLE_STABLE`, `SETTLE_TIMEOUT` |
| 화면 보호기 차단 | 캡처 phase 동안 `SetThreadExecutionState(ES_DISPLAY_REQUIRED)` (`prevent_sleep`) | `SLEEP_BLOCK` |
| 책마다 다른 crop | 캡처 완료 후 PNG 전체에서 공통 페이지 윤곽 추출 → PDF crop (`pdf_auto_crop`). crop이 바뀌면 페이지 PDF 재생성 | `PDF_AUTO_CROP` |

320페이지 전체 실행 결과 (`허깅페이스_트랜스포머_하드_트레이닝`): 키 실패·settle 타임아웃 0회, 자동 윤곽은 320장 모두 solid로 좌우 15px(RDP 검은 바)만 crop (`left=right=0.0104`, 상하 0). 책은 318쪽(판권지)에서 끝났고 319쪽에서 재시도 2회가 돌았다.

끝 감지 허용치 (`stop_repeat_tolerance`, 기본 0.3): 320쪽은 판권지에 리더의 오른쪽 화살표 오버레이가 겹쳐 픽셀 해시가 달라졌고, 그래서 "책 끝"이 자동으로 안 걸렸다. 지금은 160x260 회색 썸네일의 평균 차이로 비교한다. 측정값: 오버레이 차이 0.003, 실제 넘김 최소 3.98 (같은 책 318쪽 연속 비교). 재시도 판단도 같은 기준을 쓴다. 0.0이면 예전처럼 완전 일치.

두 번째 책 (`마스터링_트랜스포머`, 505쪽): 213장째부터 원격 리더의 상단 툴바(46px, 픽셀 동일)가 페이지 위에 겹쳐 끝까지 남았다. 내용 위치는 안 밀렸고 빈 위 여백만 덮였다. 이를 위해 `auto_crop`에 크롬 감지 2단계를 넣었다: 윤곽 가로 범위 안에서 상하단 행이 30% 이상 페이지에서 동일하고 그 띠에 비균일 행(아이콘)이 있으면 crop. 결과 top 48px, 첫 책은 0px(회귀 확인). 505장 분석에 약 40초. 480장으로 시작했다가 끝이 아니어서 `test-key --repeat 1`로 한 장 넘긴 뒤 `--pages 640 --resume`으로 이어 붙였고, 끝 감지(허용치 0.3)가 505쪽에서 멈췄다.

세 번째 책 (`프렌즈_튀르키예`, 2026-10-22, 823쪽): 이번 원격 세션은 4K 전체 화면(client 3840x2160)이고 리더 창이 왼쪽 1280px만 차지해서 `window_subrect`(CLI `--sub-left 2 --sub-top 81 --sub-width 1277 --sub-height 1975`)를 추가해 리더 페이지 영역만 찍었다. 주의: `inspect`가 DPI 인식 전에 창 좌표를 읽어 4800x2700(1.25배)으로 보고했고 `run`은 물리 3840x2160으로 잡아 첫 27장이 어긋났다. `inspect`도 `run`과 같은 시점에 `ensure_windows_capture_environment()`를 부르도록 고쳤으니 probe 좌표를 그대로 써도 된다. 결과: 키 유실 2회(232, 821쪽) 모두 재시도 1회로 복구 → 실제 포커스 이탈 재시도 경로 검증됨. 리더가 824쪽이라 표시했지만 마지막 두 장(824, 825)은 뒷표지 위에 "마지막 페이지입니다/평점" 대화상자가 뜬 화면이라 `dropped_tail/`로 빼고 823쪽으로 PDF를 다시 만들었다(`--pages 823 --force-phase pdf`). 자동 윤곽: solid 264/823, trim left 0.0376 / right 0.0516 / top 0.0607 / bottom 0.0713 (리더 흰 여백 제거), 크롬 0. 페이지 1163x1714.

네 번째 책 (`권력중독`, 2026-10-22, 243쪽): 리더 카운터는 254쪽이었지만 화면 기준으로는 243장(뒷표지)에서 끝났고, 끝 감지가 244장(평점 대화상자)에서 멈췄다. 244장은 `dropped_tail/`로. 리플로우 본문이 윤곽(표지 박스와 동일) 끝까지 꽉 차서 크롭선이 글자 끝과 1px 겹쳤다 → `--pdf-auto-crop-margin 0.005`로 재생성(CLI 플래그 신설). OCR(`--text`)은 Gemini 402 RESOURCE_EXHAUSTED(선불 크레딧 소진)로 보류. `.env`의 `GOOGLE_API_CA_BUNDLE`이 가리키는 `cato-root.cer`는 Windows 루트 저장소에서 `certutil -store Root <sha1> cato-root.cer`로 내보내면 된다(gitignore).

**2026-10-22 추가: PDF/PNG → Datalab OCR → Markdown 파이프라인.** `D:\projects\parallax`의 vlmparse datalab 백엔드를 `core/datalab_ocr.py`로 옮겼다(429/전송 오류 백오프, 과금 단위 센트, `chunks` 형식, Picture/Figure 설명문 폐기, `<math>`→`$…$`, 표 HTML 보존). 설정은 `ocr_engine`(`google`|`datalab`) · `datalab_mode` · `ocr_workers`(CLI `--ocr-engine --datalab-mode --ocr-workers`). OCR 단계(`pipeline._run_phase_ocr`)는 엔진 공통으로 재작성했다: 건너뛸 쪽을 먼저 거르고, `ocr_workers>1`이면 ThreadPool로 동시 요청, 한 쪽 실패는 `OCR_PAGE_FAIL`로 남기고 계속(Gemini는 전역 실패가 흔해 순차 모드에서 첫 실패에 멈춤), 끝에 `OCR_COST`/`OCR_FAIL n page(s)`. Datalab 블록 유형을 기존 section 타입으로 대응시켰으므로 조립(`assemble_markdown`)은 그대로다. 입력이 `--input-pdf`면 PyPDF2로 한 쪽짜리 PDF를 잘라 그대로 보낸다(렌더 불필요, fitz 의존성 없음).

조립 쪽에서 같이 고친 것 셋. ① 장 감지: Datalab은 장 머리의 작은 "Chapter N" 라벨을 `PageHeader`로 준다 → `promote_chapter_label_header()`가 페이지 첫 header/page_number(또는 title)가 라벨이고 다음이 제목이면 둘 다 title로 올려 기존 `N장` 규칙을 태운다. 라벨 정규식을 `N장|제N장|Chapter N|PART N|N부`(한 줄 전체)로 넓혔고, 선두 제목에 라벨이 2개 이상이면 목차 페이지로 보고 장 시작에서 제외. ② `paragraph_ends()`가 각주 표식(`보았다.^6^`)을 무시하도록 — 전에는 마침표 뒤 `^6^` 때문에 다음 단락과 붙었다. ③ 같은 페이지 안의 body 병합은 앞 블록이 30자 이상일 때만 — 목차 항목처럼 짧은 줄이 한 덩어리로 붙던 것을 막는다.

`권력중독` 실측: 243쪽 accurate, 6워커, 실패 0, $1.82(쪽당 0.75센트), 벽시계 약 14분(쪽당 9-10초, 요청 동시성으로 나눠짐). 장 구조 13개(Front matter · PART 1 · Chapter 1-6 · PART 2 · Chapter 7-9 · 참고문헌)가 전부 잡혔다. 주의: 조립 코드만 바뀐 뒤 `--text`를 다시 돌리면 planner가 "Nothing to do"로 끝난다(`.md` 존재) — 이번엔 `core.assemble_markdown.assemble_markdown()`을 직접 불러 재조립했다. 재조립 전용 플래그는 아직 없다(TODO 후보). 이번 실행분 `.ocr.json`은 제목의 장식 불릿("• ")이 들어간 채 저장돼 사후 스크립트로 지웠고, 코드에는 `SectionHeader` 선두 불릿 제거가 들어가 있어 다음 책부터는 바로 깨끗하다.

같은 날 후속 — **제목 등급은 글자 크기가 아니라 위치로.** 사용자 지적: 원본(리플로우 리더)이 번호 목록·인용·미주를 본문보다 훨씬 큰 글자로 그려서 글자 크기가 단락 성격과 맞지 않고, Marker는 그 큰 글자를 SectionHeader h1/h2로 붙인다(h1/h2 배정은 실측상 무작위). `datalab_ocr.classify_heading()`이 bbox로 정한다: 장 라벨(`Chapter N`/`PART N`/`N장`)→title, 그림 직후→caption, `1. …` 번호 항목·본문 폭 80% 이상→body, `Chapter N. 제목` 꼴→subtitle, 가운데 정렬(페이지 중심 ±5%)→section_title(###), 그 외(왼쪽 정렬)→subtitle(####), 숫자만·장식 기호(`•••`, `...`)→버림. 페이지 중심·폭은 그 페이지 bbox 전체의 min/max로 추정(Datalab bbox 좌표계는 보낸 이미지보다 약 1.2배 커서 절대값을 쓰면 안 된다). Datalab의 `TableOfContents`는 미주 목록에도 붙어서 body로 접었다. 조립 쪽: 뒷부분 표제어에 `주/미주/감사의 글/옮긴이의 글/찾아보기` 등 추가, PageHeader로 온 뒷부분 표제어를 title로 승격, 같은 표제어가 반복되는 페이지(러닝 헤더)는 새 장을 열지 않음, 장 제목이 본문 첫 ### 로 한 번 더 찍히던 중복 제거, 짧은 줄 두 개(각 30자 미만, 문장 끝 아님)는 페이지 안/경계 어디서든 붙이지 않음(목차 줄이 한 덩어리로 뭉치던 문제). 결과(권력중독): ## 16(Front matter·PART 2·Chapter 9·감사의 글·주·참고문헌 3), ### 25, #### 64 — 원본 대조로 ###=가운데 파란 소제목(••• 장식 뒤), ####=왼쪽 소제목 두 단계와 일치. 남은 오차: 그림 제목이 본문 중간에 큰 글자로 선 경우(74쪽 "비언어적 및 준언어적 신호", 48쪽) 2건은 ###로 남는다. 기존 `.ocr.json`은 `rebuild_page_structure()`로 재OCR 없이 재분류했다.

이어서 사용자 요청 넷을 반영: ① `full` 스타일의 `<!-- pages -->` 주석 기본 꺼짐(`assemble_options._STYLE_DEFAULTS`), ② 각주 참조 `<sup>N</sup>`는 본문에서 제거(전에는 `^N^`로 남겨 문장 끝마다 붙었다), ③ `<li>• 항목`의 이중 글머리 제거, ④ `<li>1. 항목`·`<li>1 항목`은 `-` 없이 번호 목록으로. 미주는 `<li><div><div>8</div><div>Magee (2008)</div></div></li>` 꼴이라 번호 줄과 본문 줄이 갈라지므로 `html_to_text`가 `- 8` 다음 줄을 붙여 `8. Magee (2008)`로 만든다. 결과: 각주 표식 0, 이중 글머리 0, 번호 목록 219, 남은 `- N` 6건(페이지 경계에서 번호와 본문이 갈라진 것).

**2026-10-25 추가: 기술서 검증(수식·그림·표).** `데이터분석을_위한_머신러닝_입문.pdf` 4장(PDF 106-205쪽, `--input-pdf` + Datalab accurate, 100쪽 $0.72, 실패 0)으로 확인했다. 수식은 `Equation` 블록의 `<math display="block">`을 `$$…$$`로, `TextInlineMath` 안의 `<math>`를 `$…$`로 옮기면 스캔본과 1:1로 맞는다(110쪽 유도식 `\begin{aligned}` 3줄, 베르누이 분포 지수까지 확인). 그림은 `chunk["images"]`(base64)를 `harvest_images()`가 `<output_dir>/assets/<sha1>.jpg`로 저장하고 `figure` 섹션 `![그림](assets/…)`로 끼운다 — Picture 블록뿐 아니라 모든 블록을 보며(표지 그림이 SectionHeader에 실려 온 적 있음), 파일명은 내용 해시(Datalab 이름은 페이지 간 충돌), alt는 고정 "그림"(Marker가 넣는 긴 설명문은 페이지 글이 아니다), `blocks_raw`에는 저장 경로를 남겨 `rebuild_page_structure()`가 API 없이 재조립한다. 코드 목록은 `Code` 블록 또는 `<pre>`로 감싼 Text → ` ``` ` 펜스. 표는 병합 셀이 없으면 파이프 표, 있으면 HTML(수식만 `$…$`로). 제목: `SECTION_NUMBER_RE`로 `4.3 …`→section_title(###), `4.3.1 …`→subtitle(####)을 위치 규칙보다 먼저 적용(그림 바로 아래 번호 제목이 caption으로 잡히던 것 방지), 절 번호만 `PageHeader`로 떨어진 쪽(`4.8`/`4.10`)은 다음 SectionHeader에 붙여 `4.8 자기 회귀`로 복원, `C O L U M N` 상자 라벨은 버림, 캡션 앞 장식 글리프(`♥ ▼`) 제거. 장 표시가 전혀 없는 입력은 `book_structure`가 "Front matter" 대신 제목이 title인 단일 장으로 만든다. 결과: ## 1, ### 12(4.1-4.12 전부), #### 96, 그림 29, 파이프 표 9 + HTML 표 1(혼동 행렬, rowspan). 남은 오차: 파이프 표 셀 안의 `|`는 `\|`로 이스케이프하므로 `$P(c\|x)$`처럼 수식 안에도 들어간다(GitHub는 렌더됨, 다른 뷰어는 확인 불가); 거리 공식 소제목(`유클리드 거리` 등)과 코드 파일명(`kmeans.py`)은 원본대로 ####로 남긴다.

후속(같은 날): ① 수식 블록은 Typora 호환을 위해 `$$`를 별도 줄에 두는 형식(`display_math()`), 본문 블록 안의 `<math display="block">`도 독립 단락으로 분리. ② 코드 목록 병합 `paragraph_merge.merge_code_blocks()`: 연속한 code 섹션(같은 쪽 안, 또는 쪽 경계에서 사이에 header/page_number/쪽 하단 footnote만 있는 경우)을 한 펜스로 합친다 — Datalab은 긴 목록을 줄 묶음마다 Code 블록으로 쪼개고(133쪽 11조각) 쪽이 넘어가면 당연히 끊긴다(4장에서 25곳). 4장 결과 코드 블록 118 → 70. 이어붙인 뒤 쪽 들여쓰기는 OCR이 준 대로라 연속 쪽 첫 줄들이 왼쪽으로 붙는 경우가 있다(수정 안 함, 원본 참조 필요). ③ 출력 파일은 LF로만 쓴다(`_atomic_write_text`에 `newline="\n"`): `Path.write_text`가 Windows에서 CRLF를 내보내 `$$` 블록 안 `\\` 행 구분 뒤에 CR이 붙었고, Typora가 그 수식(자카드/다이스 계수의 aligned)을 렌더하지 못했다. 문법상 다른 결함이 없어 CR을 원인으로 본다(추정, Typora 직접 확인은 사용자 측).

**2026-10-25 전체 책 변환(266쪽, $2.00, 실패 0).** 장 감지가 처음엔 2개(Front matter·찾아보기)였다. 원인은 장 머리의 `<h1>1<sup>장</sup></h1>` — `<sup>`를 각주 표식으로 통째로 버려 "1"만 남고 숫자 규칙에 걸려 사라졌다. 고친 것: ① `<sup>`는 내용이 숫자·기호(`3`, `*`, `a`)일 때만 버리고 글자는 살린다(`_sup_replacement`). ② `N장` 라벨 바로 다음 SectionHeader는 폭·위치와 무관하게 title(장 제목이 페이지 폭을 다 써서 body로 떨어지던 것). ③ 라벨 title 뒤에 title이 오지 않으면(활용법 페이지의 스크린샷 라벨 `4장`/`5장`) body로 내린다 — 단 페이지 마지막 블록이면 그대로(부 표지). ④ 목차 줄(`1.1 인공지능이란? 016`, `1장 … ..... 015`)은 끝의 쪽 번호로 알아보고 body. ⑤ 대문자 러닝 헤더(`MACHINE LEARNING FOR DATA ANALYSIS`)는 SectionHeader/Text로 와도 header — 절 번호 `3.3`이 이 러닝 헤더에 붙던 것도 같이 해결. ⑥ `- 1.1 제목` 목록 줄을 `1. 1 제목` 순서 목록으로 오인하던 `LIST_ORDERED_RE`에 `(?!\d)` 추가. ⑦ 목록 항목은 reflow·단락 병합 양쪽에서 줄 경계 고정(`is_list_item`): 장 머리 절 목록이 한 줄로 뭉치거나 다음 단락과 붙던 문제. 결과: ## 12(목차·Front matter·1~5장·찾아보기 외), ### 42(1.1~5.6 전부), #### 253, 그림 124, 수식 블록 134, 코드 171. 권력중독 재조립은 장 구성 동일(## 16/### 25/#### 64), 목록 항목이 단락에 붙지 않게 되어 순서 목록 219 → 244.

**2026-10-25 OCR 오타 보정(`core/ocr_typo_fix.py`).** 사용자 요청 "ocr 오타도 수정하도록 반영". 조립(`assemble_markdown`) 첫 단계에서 한글 어절을 사전으로 고친다: 코드 기본 항목(`BUILTIN_TYPOS`) + 프로젝트 루트 `ocr_typos.txt` + 책 폴더 `ocr_typos.txt`(`틀린표기 -> 맞는표기`, 어절 앞부분 매칭이라 조사 유지, `!단어` 보호). `$…$`/`$$…$$`/백틱/그림·링크 경로는 보호, code/equation/figure 섹션은 건너뜀. 내역은 `{title}_typo_fixes.txt`. 책 안 빈도 추정(드문 어절 앞부분 ↔ 헷갈리는 자모 하나 차이의 잦은 어절, 자모 혼동 집합 ㅂ/ㅁ·ㄷ/ㅌ·ㅇ/ㅎ·된소리·겹받침·ㅐ/ㅔ)도 구현했지만 **기본 꺼짐(`--typo-freq`)**: 실측에서 ML 책은 사전이 잡은 것 외에 전부 오탐(`빅테이블→빅데이블`, `창에서→장에서`, `처리함으로써→처리합으로써`)이었고 권력중독은 17건 모두 오탐(`앉는다→않는다`, `차원을→자원을`, `상대를→상태를`). 한국어는 활용·조사 때문에 멀쩡한 희귀 단어가 잦은 단어와 자모 하나 차이인 경우가 흔해서 책 안 빈도만으로는 판별이 안 된다. 또 Datalab 오타는 책 전체에서 일관되게 틀리는 편(`맴리듀스` 5회 전부)이라 빈도로는 원래 못 잡는다 — 사전이 맞는 도구. 결과: ML 책 `맴리듀스` 5회·`텐드로그램` 2회 교정, 장 구성 변화 없음(## 12), 권력중독 0건. 이어서 사용자가 `.env`에 `ANTHROPIC_API_KEY`를 넣어 **LLM 교정 `core/llm_proofread.py`** 추가(`--proofread`, 기본 꺼짐): 쪽마다 산문 섹션을 `[n] 텍스트`로 보내고 교정 목록 JSON만 받는다(쪽을 다시 쓰게 하지 않음 → 출력 토큰이 적어 싸고, 문장 바꿔치기가 구조적으로 불가). 로컬 검증(`validate_fix`): 세그먼트에 정확히 1회 존재, 길이 차 ≤4, difflib 유사도 ≥0.5, 한글 포함, `$`/백틱 제외, 보호 스팬 안이면 무시. 캐시 `tmp/{title}_NNNN.proof.json`(프롬프트+모델 sha1). SDK는 `anthropic` 2.x(httpx2), 회사 CA는 `google_ocr._ssl_context()`를 `DefaultHttpxClient(verify=…)`로 재사용. 모델 `claude-opus-5-5`, effort medium, 시스템 프롬프트 cache_control, `fallbacks="default"`(400이면 일반 요청으로 전환). 10쪽 시험: 9쪽 $0.04, 제안 1건 `추가 예측→주가 예측`(156쪽, 맞는 교정 — 자기 회귀 설명의 "주가 예측"). 전체 실행: ML 책 247쪽 $1.08, 적용 82건(맬리듀스×20, 퍼센트론→퍼셉트론, 원도→윈도, 바이어→바이어스, 경시하강법→경사하강법, 하지모토→하시모토 등; 표본 대조에서 오교정 0 — `가장 클 카테고리→가장 큰`, `바뀜 드립니다→바꿔`도 맞음). 권력중독 243쪽 $1.56, 적용 32건(쿼팅→퀼팅, 쏠도→쇄도, 엘론→엔론, 키츠볜→키츠뷜, 값아먹는→갉아먹는 등; `브릭클레→블릭클레`는 인명이라 확인 불가). 검증 규칙 조정: 1~2음절 교정은 유사도 조건 면제(`뻗→밴`, `허둠→하둡`), `$…$`가 양쪽에 똑같이 있으면 허용(`바이러스 $b$를→바이어스 $b$를`), 호환 자모(ㄱ-ㅎ)도 한글로 인정(찾아보기 머리글 `L→ㄴ`). 빈도 추정과 달리 LLM 교정은 전수 검토에서 오탐이 없었으므로 기본 흐름은 "사전 + `--proofread`"이고, 빈도(`--typo-freq`)는 쓰지 않는다.

**2026-10-25 소스 우선순위 변경(`job_plan`).** `마스터링_트랜스포머` PDF→MD 요청에서 책 폴더 `tmp/`에 캡처 PNG 505장이 남아 있어 플래너가 `--input-pdf`를 무시하고 원본 PNG(크롭 전)를 OCR하려 했다. 이제 `--input-pdf`/`input_pdf`가 실제 파일을 가리키면 PNG보다 먼저 쓴다. 같이 고친 것: 명시한 PDF인데 `n_pages`가 기본값 1이면 PDF 전체 쪽 수로 올린다(첫 실행이 1쪽만 처리하고 끝났음 — `_clamp_n_pages`는 줄이기만 한다). `--pages`를 주면 그대로.

**2026-10-25 마스터링_트랜스포머 PDF→MD(505쪽, Datalab $3.78 + 교정 $4.90).** 장 머리가 `01`(큰 숫자) + 제목 꼴이라 처음엔 "부"만 잡혔다. 추가 규칙(`_opens_chapter`): 쪽 첫머리의 1~2자리 숫자 블록이 표시 크기(높이 ≥ 쪽 너비의 4.5%; 러닝 헤드 쪽 번호는 약 3%)이고 바로 뒤에 제목 블록(SectionHeader, 또는 역시 표시 크기인 PageHeader — 오른쪽 쪽은 둘 다 PageHeader로 온다)이 오면 `N장` 라벨 title로 만들고 다음 블록을 장 제목으로 삼는다. 함께 고친 것: `html_to_text`가 인라인 태그(`<b>`/`<i>`/`<u>`…)를 공백으로 바꿔 `자연어 처리 (NLP )`가 되던 것을 공백 없이 제거. 교정 캐시 해시는 공백을 뺀 텍스트 기준(구 해시도 인정)이라 공백만 바뀐 재조립은 무료지만, 섹션 분류가 바뀐 쪽은 다시 요청된다(2차 재조립에서 361쪽 $2.13, 3차 11쪽 $0.06 — 분류 규칙을 먼저 안정시킨 뒤 `--proofread`를 켜는 편이 싸다). 결과: ## 23(목차·Front matter·1~4부·1~18장), ### 100, 그림 126, 코드 블록 695. LLM 교정 211건 적용(`허킹 페이스→허깅 페이스`, `토큰나이저→토크나이저`, `옳긴이→옮긴이`가 대부분; 캡처 PNG로 원본 대조해 셋 다 OCR의 일관된 오인임을 확인). 12장 제목 "efficient transformer"는 원서 디자인 그대로 영문(오류 아님). 남은 흠: 차례 쪽의 `03 부`/`04 부`가 ###로 2건 남음.

운영 실수 기록: Git Bash에서 `--base-dir D:\ebook`을 따옴표 없이 넘겨 백슬래시가 사라졌고(`D:ebook` = 드라이브 상대 경로) 출력이 `D:\projects\ebook\…`로 갔다. 그래서 미리 복사해 둔 4장 OCR 결과를 못 보고 100쪽을 다시 보냈다(약 $0.72 낭비). Windows 경로는 항상 따옴표로 감싸거나 슬래시로 쓴다. 결과 폴더는 `D:\ebook\데이터분석을_위한_머신러닝_입문\`로 옮겼다.

미검증: 없음(포커스 이탈 재시도는 세 번째 책에서 실측).

## 1. 한 줄 요약

Kindle 데스크톱 앱에서 “중앙 클릭×2 → settle → 캡처 → right” 루프가 동작한다.  
그 공통 knobs를 `_proven_capture_defaults()`로 묶어 `kindle_cloud` / `aladin_app` / `aladin_web`에도 적용했다.  
**아직 실기 검증이 안 된 것:** Cloud·Aladin 실제 캡처, 각 리더별 `pdf_trim` / `target_window_title`, Aladin의 SendInput 적합성.

---

## 2. 검증된 페이지 루프 (코드가 이미 이렇게 동작)

`core/pipeline.py` `_run_phase_capture`:

1. (첫 페이지만) `CAPTURE_SETTLE` = `delay_sec`
2. `READER_FOCUS` — 본문 비율 좌표에 `reader_focus_clicks`회 클릭 (간격 ≥ `GetDoubleClickTime`)
3. 포인터를 캡처 **옆**으로 대피 → `focus_click_settle_sec` 대기 (오버레이 소멸)
4. 스크린샷 (`hide_cursor_during_capture`)
5. `TARGET_KEY_SENT` — `next_key` (`reader_focus_clicks=0`으로 키만; 클릭은 위에서 끝)
6. `delay_sec` 후 다음 페이지

시작 시: `fit_on_start=false`, `start_focus_clicks=0` (창은 사용자가 미리 left-third 배치).

진단: `--debug-capture` → `DEBUG_KEY_EFFECT meandiff=… (page moved | NO VISIBLE CHANGE)`.

---

## 3. Kindle에서 잡았던 함정 (다시 건드리지 말 것)

자세한 표: **REQUIREMENTS.md §12**.

| ID | 함정 | 코드 위치 |
|----|------|-----------|
| 12.3 | 짧은 연속 클릭 → 더블클릭 줌 | `windows_util._reader_focus_clicks` |
| 12.4 | 합성 **Alt** 탭이 메뉴 모드 토글 → 화살표 무시 | `force_foreground_hwnd` (이미 FG면 no-op; Alt는 최후 수단) |
| 12.5 | 프레임 `SetFocus`가 WinUI `InputSite` 포커스 탈취 | `has_internal_keyboard_focus` / `_send_vk_attached` |
| 12.7 | 포인터를 화면 밖 위로 보내면 상단 바에 클램프 → 툴바 유지 | `_move_pointer_outside_capture_rect` (옆 우선) |
| 12.8 | Kindle 앱 크롬이 client 안 → `pdf_trim.top=0.032` | `kindle_app` 프로필만 |

회귀 테스트: `tests/test_capture_order.py`, `tests/test_windows_key.py` (`test_already_foreground_window_is_not_reactivated`, double-click gap).

---

## 4. 프로필 파라미터 (현재)

공통 (`_proven_capture_defaults` / `reader_profiles.jsonc`):

| 필드 | 값 |
|------|-----|
| `capture_mode` | `screen_left_third` |
| `window_capture_backend` | `screen` |
| `use_window_client_rect` | true |
| `hide_cursor_during_capture` | true |
| `delay_sec` | 2.0 |
| `reader_focus_clicks` | **2** |
| `reader_focus_x_ratio` / `_y` | **0.5 / 0.5** |
| `focus_click_settle_sec` | **1.0** |
| `fit_on_start` | false |
| `start_focus_clicks` | 0 |

리더별만 다른 것:

| 프로필 | `next_key` | `key_delivery` | `target_window_title` | `pdf_trim` | 검증 |
|--------|------------|----------------|----------------------|------------|------|
| `kindle_app` | right | sendinput | `Kindle` | top **0.032** | ✅ |
| `kindle_cloud` | right | **pyautogui** | (GUI에서 탭 제목) | 0 TBD | ❌ 실기 미검증 |
| `aladin_app` | **pagedown** | **sendinput** | (설정 필요) | 0 TBD | ❌ (예전엔 pyautogui로 “확인” 기록만) |
| `aladin_web` | **pagedown** | **pyautogui** | (GUI에서 탭 제목) | 0 TBD | ❌ |

변경 의도:
- Cloud: 예전 `focus_clicks=0`(상단 Aa) → **중앙 클릭×2**로 kindle_app과 동일. 상단만 피하면 됨.
- Aladin 앱: 네이티브이므로 kindle_app처럼 **sendinput**. 안 되면 `pyautogui`로 되돌리기.

---

## 5. 다음 세션 TODO (우선순위)

### 5.1 실기 스모크 (프로필마다)

```powershell
# 창을 화면 왼쪽 1/3에 미리 배치. 툴바/화살표 숨긴 읽기 화면에서 시작.
# 이전 tmp PNG가 있으면 resume이 건너뜀 → 새 title 쓰거나 tmp 삭제 / --force-phase capture

python -m ebook_capture run --config default_config.jsonc --reader kindle_cloud --pdf --pages 4 --debug-capture --title cloud_smoke -y
python -m ebook_capture run --config default_config.jsonc --reader aladin_app  --pdf --pages 4 --debug-capture --title aladin_app_smoke -y
python -m ebook_capture run --config default_config.jsonc --reader aladin_web  --pdf --pages 4 --debug-capture --title aladin_web_smoke -y
```

성공 기준:
- 로그 매 키: `DEBUG_KEY_EFFECT … (page moved)`
- 연속 PNG meandiff ≫ 0 (같은 화면 반복 아님)
- 이미지에 툴바/페이지 화살표 없음

실패 시 분기:
- `NO VISIBLE CHANGE` → `key_delivery` 바꾸기 (`sendinput`↔`pyautogui`), Alt/포커스 재발인지 §12.4·12.5 확인
- 줌/Aa → 클릭이 상단·가장자리인지 확인; 필요 시 clicks=1 또는 0
- 오버레이 잔류 → `focus_click_settle_sec` ↑ 또는 포인터 대피 위치

### 5.2 리더별 튜닝 후 프로필에 반영

- [ ] `aladin_app` `target_window_title` 확정 (창 제목 부분 일치)
- [ ] `kindle_cloud` / `aladin_web` — 브라우저 탭 제목 예시를 USAGE에 한 줄 추가
- [ ] 각 리더 첫 클린 PNG로 `pdf_trim` 비율 측정 → `reader_profiles.jsonc` + built-in
- [ ] Aladin SendInput 실패 시 `aladin_app.key_delivery`를 `pyautogui`로 되돌리고 note 갱신

### 5.3 (선택) 코드/문서

- [ ] GUI Reader 콤보가 새 필드(`focus_click_settle_sec`, focus ratios)를 프로필 적용 시 반영하는지 확인
- [ ] 검증용 폴더 정리: `E:\ebook\kindle_verify_*` (이전 세션 스모크)
- [x] 책 config에서 리더 knobs 제거 (`default_config.jsonc` / `.json` = 책만)

---

## 6. 주요 파일 맵

| 경로 | 역할 |
|------|------|
| `core/pipeline.py` | 캡처 루프 순서, `READER_FOCUS`, settle, `DEBUG_KEY_EFFECT` |
| `core/windows_util.py` | Alt 가드, InputSite 포커스 유지, 클릭 간격, key delivery |
| `core/reader_profiles.py` | `_proven_capture_defaults`, built-in 프로필 |
| `reader_profiles.jsonc` | 런타임 오버레이 (built-in을 덮어씀) |
| `core/config.py` | `CaptureConfig` / `PdfTrim` |
| `REQUIREMENTS.md` §12 | 문제·해결책 카탈로그 |
| `tests/test_capture_order.py` | focus→capture→key 순서 |
| `tests/test_reader_profiles.py` | 전 프로필 공통 루프 knobs |

우선순위: **CLI 플래그 > `reader_profiles.jsonc` > built-in > CaptureConfig 기본값**.

---

## 7. 빠른 재현 (Kindle 앱, 이미 통과한 명령)

```powershell
python -m ebook_capture run --config default_config.jsonc --reader kindle_app --pdf --pages 4 --debug-capture --title kindle_verify_final -y
```

기대 로그 조각: `READER_FOCUS clicks=2 @(…,…) ratio=(0.50,0.50) settle=1.0s` 후  
`DEBUG_KEY_EFFECT meandiff=… (page moved)` 반복, `PDF_TRIM … top: 0.032`.

테스트: `pytest` → 현재 86+ passed 수준 (스킵 제외).

---

## 8. 하지 말 것

- `force_foreground_hwnd`에 Alt를 “항상” 넣는 쪽으로 되돌리기
- focus click 간격을 더블클릭 시간 이하로 줄이기
- 캡처 **후**에 focus click 넣는 순서로 되돌리기
- Kindle `pdf_trim.top`을 이유 없이 0으로 리셋
- resume이 켜진 채로 깨진 PNG가 있는 `tmp`에서 “안 넘어간다”고 단정 (먼저 PNG 삭제 / `--force-phase capture`)
