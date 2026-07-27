# CONTEXT — ebook_capture handoff (다음 세션용)

작성일: 2026-07-25  
상태: **Kindle for PC (`kindle_app`) 캡처 루프 검증 완료.** 동일 파라미터를 다른 프로필에 전파해 둠.  
관련 문서: [USAGE.md](USAGE.md) · [REQUIREMENTS.md](REQUIREMENTS.md) §12 · [reader_profiles.jsonc](reader_profiles.jsonc)

---

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
