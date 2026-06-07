"""Screen capture and post-processing (no Qt — safe for CLI subprocess)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import pyautogui
from PIL import Image

from core.screen_capture import (
    ensure_windows_capture_environment,
    screenshot_region,
)
from core.config import (
    CAPTURE_MANUAL,
    CaptureConfig,
    PHASE_CAPTURE,
    PHASE_OCR,
    PHASE_PDF,
    WINDOW_CAPTURE_PRINTWINDOW,
)

ProgressFn = Callable[[str], None]


def _emit(progress: ProgressFn | None, msg: str) -> None:
    if progress:
        progress(msg)
    print(msg, flush=True)


def _screen_region(cfg: CaptureConfig) -> tuple[int, int, int, int]:
    """Return left, top, width, height for one screenshot."""
    if cfg.capture_mode == CAPTURE_MANUAL:
        return cfg.rect.as_tuple()
    from core import windows_util as wu

    return wu.resolve_screen_rect(
        cfg.target_window_title,
        cfg.capture_mode,
        use_client_rect=cfg.use_window_client_rect,
        prefer_foreground=cfg.prefer_foreground_window_match,
        pinned_hwnd=cfg.pinned_target_hwnd,
    )


def _activate_target(cfg: CaptureConfig) -> None:
    if cfg.capture_mode == CAPTURE_MANUAL:
        return
    from core import windows_util as wu

    if cfg.pinned_target_hwnd > 0:
        wu.focus_window_for_keyboard(cfg.pinned_target_hwnd)
        return
    wu.activate_window_title(
        cfg.target_window_title,
        prefer_foreground=cfg.prefer_foreground_window_match,
        pinned_hwnd=0,
    )


def _send_page_turn_key(cfg: CaptureConfig, progress: ProgressFn | None) -> None:
    """Activate target window, focus clicks, then send next_key."""
    if cfg.capture_mode == CAPTURE_MANUAL:
        pyautogui.press(cfg.next_key)
        return
    from core import windows_util as wu

    left, top, w, h = _screen_region(cfg)
    ok, detail = wu.send_page_turn_key(
        cfg.next_key,
        pinned_hwnd=cfg.pinned_target_hwnd,
        title=cfg.target_window_title,
        prefer_foreground=cfg.prefer_foreground_window_match,
        capture_rect=(left, top, w, h),
        reader_focus_clicks=cfg.reader_focus_clicks,
    )
    _emit(progress, f"TARGET_KEY_SENT key={cfg.next_key!r} ok={ok} {detail}")


def _debug_rect_lines(cfg: CaptureConfig) -> list[str]:
    if cfg.capture_mode == CAPTURE_MANUAL:
        l, t, w, h = cfg.rect.as_tuple()
        return [
            "DEBUG_RECT mode=manual",
            f"DEBUG_RECT crop_screen left={l} top={t} width={w} height={h} "
            f"(right={l + w} bottom={t + h})",
        ]
    from core import windows_util as wu

    return wu.debug_rect_lines_window_capture(
        cfg.target_window_title,
        cfg.capture_mode,
        use_client_rect=cfg.use_window_client_rect,
        prefer_foreground=cfg.prefer_foreground_window_match,
    )


def _ensure_pointer_in_capture_rect(
    left: int,
    top: int,
    width: int,
    height: int,
    progress: ProgressFn | None,
) -> None:
    """If the cursor is outside the capture rectangle, move it inside (center) before screenshot."""
    if width < 1 or height < 1:
        return
    x, y = pyautogui.position()
    inside = left <= x < left + width and top <= y < top + height
    if inside:
        return
    cx = left + width // 2
    cy = top + height // 2
    pyautogui.moveTo(cx, cy, duration=0.1)
    _emit(
        progress,
        f"POINTER_MOVE outside capture area; moved to center ({cx}, {cy})",
    )
    time.sleep(0.05)


def _move_pointer_outside_capture_rect(
    left: int,
    top: int,
    width: int,
    height: int,
    progress: ProgressFn | None,
) -> tuple[int, int] | None:
    """Move cursor outside the screenshot rect temporarily; return original position."""
    if width < 1 or height < 1:
        return None
    original = pyautogui.position()
    ox, oy = int(original[0]), int(original[1])

    mid_x = left + max(1, width // 2)
    mid_y = top + max(1, height // 2)
    candidates = [
        (mid_x, top - 24),
        (left - 24, mid_y),
        (left + width + 24, mid_y),
        (mid_x, top + height + 24),
    ]
    target_x = target_y = 0
    for target_x, target_y in candidates:
        try:
            pyautogui.moveTo(target_x, target_y, duration=0)
            break
        except Exception:
            continue
    else:
        _emit(progress, "POINTER_HIDE skipped; could not move cursor outside capture area")
        return None
    _emit(
        progress,
        f"POINTER_HIDE moved outside capture area to ({target_x}, {target_y})",
    )
    time.sleep(0.03)
    return ox, oy


def _restore_pointer(
    original: tuple[int, int] | None,
    progress: ProgressFn | None,
) -> None:
    if original is None:
        return
    try:
        pyautogui.moveTo(original[0], original[1], duration=0)
        _emit(progress, f"POINTER_RESTORE ({original[0]}, {original[1]})")
    except Exception as ex:
        _emit(progress, f"POINTER_RESTORE_FAIL {ex!r}")


def _part_path(path: Path) -> Path:
    return path.with_name(path.name + ".part")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = _part_path(path)
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _valid_png(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        return False


def _valid_text(path: Path) -> bool:
    return path.is_file() and path.stat().st_size >= 0


def _valid_ocr_json(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    sections = data.get("sections")
    return isinstance(sections, list)


def _valid_pdf(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _load_state(cfg: CaptureConfig) -> dict[str, Any]:
    path = cfg.state_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "title": cfg.title,
        "start_page": cfg.start_page,
        "n_pages": cfg.n_pages,
        "phases": {
            PHASE_CAPTURE: {},
            PHASE_OCR: {},
            PHASE_PDF: {},
        },
        "errors": [],
        "outputs": {},
    }


def _save_state(cfg: CaptureConfig, state: dict[str, Any]) -> None:
    state["title"] = cfg.title
    state["start_page"] = cfg.start_page
    state["n_pages"] = cfg.n_pages
    state["outputs"] = {
        "final_pdf": str(cfg.final_pdf_path()),
        "combined_txt": str(cfg.final_ocr_text_path()),
    }
    _atomic_write_json(cfg.state_path(), state)


def _mark_page(
    cfg: CaptureConfig,
    state: dict[str, Any],
    phase: str,
    page_num: int,
    status: str,
    path: Path | None = None,
    error: str | None = None,
) -> None:
    phases = state.setdefault("phases", {})
    phase_state = phases.setdefault(phase, {})
    record: dict[str, Any] = {"status": status}
    if path is not None:
        record["path"] = str(path)
    if error:
        record["error"] = error
        state.setdefault("errors", []).append(
            {"phase": phase, "page": page_num, "error": error}
        )
    phase_state[str(page_num)] = record
    _save_state(cfg, state)


def _state_done(state: dict[str, Any], phase: str, page_num: int) -> bool:
    try:
        return state["phases"][phase][str(page_num)]["status"] == "done"
    except (KeyError, TypeError):
        return False


def _can_skip_page(
    cfg: CaptureConfig,
    state: dict[str, Any],
    phase: str,
    page_num: int,
    validator: Callable[[], bool],
) -> bool:
    if not cfg.resume or cfg.should_force(phase):
        return False
    if _state_done(state, phase, page_num) and validator():
        return True
    if validator():
        _mark_page(cfg, state, phase, page_num, "done")
        return True
    return False


def _save_image_atomic(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = _part_path(path)
    image.save(part, format="PNG")
    os.replace(part, path)


def _capture_one_page(
    cfg: CaptureConfig,
    page_num: int,
    page_index: int,
    n_run: int,
    progress: ProgressFn | None,
) -> Image.Image:
    _activate_target(cfg)
    left, top, w, h = _screen_region(cfg)
    if cfg.debug_capture:
        _emit(
            progress,
            f"--- DEBUG_RECT page {page_index + 1}/{n_run} file_page#{page_num} ---",
        )
        for line in _debug_rect_lines(cfg):
            _emit(progress, line)
        _emit(
            progress,
            f"DEBUG_RECT crop_screen_pointer_region left={left} top={top} "
            f"width={w} height={h} (right={left + w} bottom={top + h})",
        )

    shot: Image.Image | None = None
    if (
        cfg.capture_mode != CAPTURE_MANUAL
        and cfg.window_capture_backend == WINDOW_CAPTURE_PRINTWINDOW
    ):
        import sys

        if sys.platform == "win32":
            from core import windows_util as wu
            from core import win32_bitmap_capture as wbc

            try:
                hwnd = (
                    cfg.pinned_target_hwnd
                    if cfg.pinned_target_hwnd > 0
                    else wu.resolve_target_hwnd(
                        cfg.target_window_title,
                        prefer_foreground=cfg.prefer_foreground_window_match,
                    )
                )
                raw = wbc.capture_client_printwindow(hwnd)
                if raw is not None:
                    raw_mostly_black = wbc.is_mostly_black(raw)
                    shot = wbc.apply_window_preset_crop(raw, cfg.capture_mode)
                    if cfg.debug_capture:
                        _emit(
                            progress,
                            f"DEBUG_RECT capture_backend=printwindow hwnd=0x{hwnd:x} "
                            f"raw_px={raw.width}x{raw.height} "
                            f"raw_mostly_black={raw_mostly_black} "
                            f"out_px={shot.width}x{shot.height}",
                        )
            except Exception as ex:
                if cfg.debug_capture:
                    _emit(progress, f"DEBUG_RECT printwindow_failed {ex!r}")

    if shot is None:
        _ensure_pointer_in_capture_rect(left, top, w, h, progress)
        if cfg.debug_capture:
            cx, cy = pyautogui.position()
            _emit(progress, f"DEBUG_RECT cursor_after_pointer_adjust x={cx} y={cy}")
    restore_pointer = None
    if shot is None:
        if cfg.debug_capture:
            _emit(progress, "DEBUG_RECT capture_backend=screen_region (mss / pyautogui)")
        try:
            if cfg.hide_cursor_during_capture:
                restore_pointer = _move_pointer_outside_capture_rect(
                    left, top, w, h, progress
                )
            shot = screenshot_region(left, top, w, h)
        finally:
            _restore_pointer(restore_pointer, progress)
    return shot


def _pin_capture_target(cfg: CaptureConfig, progress: ProgressFn | None) -> None:
    """Lock one HWND for the whole capture phase (avoids foreground drift to another match)."""
    if cfg.capture_mode == CAPTURE_MANUAL:
        return
    from core import windows_util as wu

    hwnd, title = wu.pin_target_window(
        cfg.target_window_title,
        prefer_foreground=cfg.prefer_foreground_window_match,
    )
    cfg.pinned_target_hwnd = hwnd
    _emit(
        progress,
        f"TARGET_WINDOW pinned title={title!r} hwnd=0x{hwnd:x} "
        f"(query={cfg.target_window_title!r})",
    )


def _run_phase_capture(
    cfg: CaptureConfig,
    state: dict[str, Any],
    n_run: int,
    progress: ProgressFn | None,
) -> None:
    _emit(progress, "Phase I: capture PNG")
    _pin_capture_target(cfg, progress)
    skipped_any = False
    for i, page_num in enumerate(cfg.page_numbers(n_run)):
        img_path = cfg.page_png_path(page_num)
        if _can_skip_page(
            cfg,
            state,
            PHASE_CAPTURE,
            page_num,
            lambda path=img_path: _valid_png(path),
        ):
            skipped_any = True
            _emit(progress, f"IMAGE_SKIP page#{page_num} {img_path}")
            continue
        if skipped_any:
            _emit(
                progress,
                "CAPTURE_RESUME_WARN skipped earlier pages; ensure the viewer is "
                f"currently positioned at page#{page_num}.",
            )
        try:
            shot = _capture_one_page(cfg, page_num, i, n_run, progress)
            _save_image_atomic(shot, img_path)
            if cfg.debug_capture:
                _emit(
                    progress,
                    f"DEBUG_RECT image_saved size_px={shot.width}x{shot.height} path={img_path}",
                )
            _mark_page(cfg, state, PHASE_CAPTURE, page_num, "done", img_path)
            _emit(progress, f"IMAGE_OK {i + 1}/{n_run} page#{page_num} {img_path}")
        except Exception as ex:
            _mark_page(cfg, state, PHASE_CAPTURE, page_num, "failed", img_path, repr(ex))
            raise
        if i < n_run - 1:
            _send_page_turn_key(cfg, progress)
            time.sleep(cfg.delay_sec)


def _collect_combined_ocr_parts(cfg: CaptureConfig) -> list[str]:
    """Build combined OCR text from all page .txt files already in tmp/."""
    import re

    parts: list[tuple[int, str]] = []
    pattern = re.compile(rf"^{re.escape(cfg.title)}_(\d+)\.txt$")
    tmp = cfg.tmp_dir()
    if not tmp.is_dir():
        return []
    for path in tmp.glob(f"{cfg.title}_*.txt"):
        match = pattern.match(path.name)
        if not match:
            continue
        page_num = int(match.group(1))
        text = path.read_text(encoding="utf-8")
        parts.append((page_num, f"=== page {page_num} ===\n{text}"))
    parts.sort(key=lambda item: item[0])
    return [block for _, block in parts]


def _run_phase_ocr(
    cfg: CaptureConfig,
    state: dict[str, Any],
    n_run: int,
    progress: ProgressFn | None,
) -> int:
    from core.google_ocr import (
        extract_page_structure_from_image,
        extract_page_structure_from_pdf_page,
        page_structure_to_text,
    )

    pdf_path = cfg.resolved_input_pdf()
    if pdf_path is not None and pdf_path.is_file():
        _emit(progress, "Phase II: PDF -> structured OCR JSON + TXT (Google Gemini)")
    else:
        _emit(progress, "Phase II: PNG -> structured OCR JSON + TXT (Google Gemini)")
    try:
        for page_num in cfg.page_numbers(n_run):
            txt_path = cfg.page_txt_path(page_num)
            json_path = cfg.page_ocr_json_path(page_num)
            if pdf_path is not None and pdf_path.is_file():
                pdf_index = cfg.pdf_page_index(page_num)
                if _can_skip_page(
                    cfg,
                    state,
                    PHASE_OCR,
                    page_num,
                    lambda t=txt_path, j=json_path: _valid_text(t) and _valid_ocr_json(j),
                ):
                    _emit(progress, f"OCR_SKIP page#{page_num} {txt_path}")
                    continue
                try:
                    _emit(
                        progress,
                        f"OCR_PDF_PAGE pdf_page={page_num} pdf_index={pdf_index}",
                    )
                    structure = extract_page_structure_from_pdf_page(
                        pdf_path,
                        pdf_index,
                        page_num=page_num,
                        lang_hint=cfg.ocr_lang,
                        prompt=cfg.ocr_text_prompt,
                        prompt_file=cfg.resolved_ocr_prompt_file(),
                    )
                except ValueError as exc:
                    _mark_page(cfg, state, PHASE_OCR, page_num, "failed", json_path, str(exc))
                    raise RuntimeError(str(exc)) from exc
            else:
                png = cfg.page_png_path(page_num)
                if not _valid_png(png):
                    _emit(progress, f"OCR_MISSING_IMAGE page#{page_num} {png}")
                    return 3
                if _can_skip_page(
                    cfg,
                    state,
                    PHASE_OCR,
                    page_num,
                    lambda t=txt_path, j=json_path: _valid_text(t) and _valid_ocr_json(j),
                ):
                    _emit(progress, f"OCR_SKIP page#{page_num} {txt_path}")
                    continue
                structure = extract_page_structure_from_image(
                    png,
                    page_num=page_num,
                    lang_hint=cfg.ocr_lang,
                    prompt=cfg.ocr_text_prompt,
                    prompt_file=cfg.resolved_ocr_prompt_file(),
                )
            try:
                text = page_structure_to_text(structure)
                _atomic_write_text(txt_path, text)
                _atomic_write_json(json_path, structure)
                _mark_page(cfg, state, PHASE_OCR, page_num, "done", json_path)
                if text:
                    _emit(progress, f"OCR_TEXT_OK page#{page_num} {txt_path}")
                    _emit(progress, f"OCR_JSON_OK page#{page_num} {json_path}")
                else:
                    _emit(progress, f"OCR_EMPTY page#{page_num} (no visible text) {json_path}")
            except RuntimeError as exc:
                _mark_page(cfg, state, PHASE_OCR, page_num, "failed", json_path, str(exc))
                raise
        _atomic_write_text(
            cfg.final_ocr_text_path(),
            "\n\n".join(_collect_combined_ocr_parts(cfg)),
        )
        _emit(progress, f"OCR_OK {cfg.final_ocr_text_path()}")
        return 0
    except RuntimeError as exc:
        _emit(progress, f"OCR_FAIL {exc}")
        return 3


def _run_phase_pdf(
    cfg: CaptureConfig,
    state: dict[str, Any],
    n_run: int,
    progress: ProgressFn | None,
) -> int:
    from core.image_pdf import build_page_image_pdf, merge_pdfs

    _emit(progress, "Phase III: image PDF")
    page_pdfs: list[Path] = []
    try:
        for page_num in cfg.page_numbers(n_run):
            png = cfg.page_png_path(page_num)
            page_pdf = cfg.page_image_pdf_path(page_num)
            if not _valid_png(png):
                _emit(progress, f"PDF_MISSING_IMAGE page#{page_num} {png}")
                return 3
            if _can_skip_page(
                cfg,
                state,
                PHASE_PDF,
                page_num,
                lambda path=page_pdf: _valid_pdf(path),
            ):
                page_pdfs.append(page_pdf)
                _emit(progress, f"PDF_PAGE_SKIP page#{page_num} {page_pdf}")
                continue
            try:
                part = _part_path(page_pdf)
                build_page_image_pdf(png, part)
                os.replace(part, page_pdf)
                if not _valid_pdf(page_pdf):
                    raise RuntimeError(f"Generated invalid PDF page: {page_pdf}")
                page_pdfs.append(page_pdf)
                _mark_page(cfg, state, PHASE_PDF, page_num, "done", page_pdf)
                _emit(progress, f"PDF_PAGE_OK page#{page_num} {page_pdf}")
            except Exception as exc:
                _mark_page(cfg, state, PHASE_PDF, page_num, "failed", page_pdf, str(exc))
                raise
        final_part = _part_path(cfg.final_pdf_path())
        merge_pdfs(page_pdfs, final_part)
        os.replace(final_part, cfg.final_pdf_path())
        _emit(progress, f"PDF_OK {cfg.final_pdf_path()}")
        return 0
    except Exception as exc:
        _emit(progress, f"PDF_FAIL {exc}")
        return 3


def run_capture(
    cfg: CaptureConfig,
    progress: ProgressFn | None = None,
) -> int:
    # Screen-region capture needs physical monitor coordinates. PrintWindow captures
    # the HWND client coordinate space directly; forcing per-monitor DPI awareness
    # can inflate MSTSC client sizes (e.g. 2560x1440 -> 3200x1800 at 125%).
    if cfg.capture_mode == CAPTURE_MANUAL or (
        cfg.window_capture_backend != WINDOW_CAPTURE_PRINTWINDOW
    ):
        ensure_windows_capture_environment()
    cfg.validate()
    maxp = max(1, int(cfg.debug_capture_max_pages))
    n_run = min(maxp, cfg.n_pages) if cfg.debug_capture else cfg.n_pages
    if cfg.debug_capture:
        _emit(
            progress,
            f"DEBUG_CAPTURE enabled: running {n_run} page(s) "
            f"(configured n_pages={cfg.n_pages}, max={maxp})",
        )
    cfg.output_dir().mkdir(parents=True, exist_ok=True)
    cfg.tmp_dir().mkdir(parents=True, exist_ok=True)
    state = _load_state(cfg)

    if cfg.run_capture_phase:
        _run_phase_capture(cfg, state, n_run, progress)
    if cfg.run_ocr_phase:
        rc = _run_phase_ocr(cfg, state, n_run, progress)
        if rc:
            return rc
    if cfg.run_pdf_phase:
        rc = _run_phase_pdf(cfg, state, n_run, progress)
        if rc:
            return rc
    _emit(progress, "DONE")
    return 0
