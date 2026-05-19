"""Command-line interface for the capture pipeline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import (
    CAPTURE_MANUAL,
    CaptureConfig,
    DEFAULT_BOOK_TITLE,
    OUTPUT_MODES,
    OUTPUT_AUDIO,
    OUTPUT_IMAGES,
    OUTPUT_PDF_IMAGE,
    OUTPUT_PDF_SEARCHABLE,
    OUTPUT_TEXT,
    PHASE_ALL,
    PHASE_CAPTURE,
    PHASE_OCR,
    PHASE_PDF,
    Rect,
    WINDOW_CAPTURE_PRINTWINDOW,
    bundled_default_config_path,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ebook-capture",
        description="Capture on-screen regions and build PDF / OCR / optional TTS audio.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    gui = sub.add_parser("gui", help="Open the PyQt5 control panel (calls capture via CLI subprocess).")
    gui.set_defaults(_handler=_cmd_gui)

    cap = sub.add_parser(
        "capture",
        help="Run one capture job (use --config from the GUI or pass flags below).",
    )
    cap.set_defaults(_handler=_cmd_capture)
    cap.add_argument(
        "--config",
        type=Path,
        help="JSON base settings; any other flags you pass still override the file.",
    )
    cap.add_argument(
        "--title",
        default=None,
        help=(
            "Book title (creates <base-dir>/<title>/ with tmp/ below it; "
            f"default: {DEFAULT_BOOK_TITLE})"
        ),
    )
    cap.add_argument(
        "--pages",
        type=int,
        metavar="N",
        default=None,
        help="Number of pages to capture",
    )
    cap.add_argument(
        "--start-page",
        type=int,
        dest="start_page",
        default=None,
        help="First page number in filenames (default 1 when not using --config)",
    )
    cap.add_argument(
        "--capture-mode",
        choices=[
            CAPTURE_MANUAL,
            "window_full",
            "window_left_third",
            "window_right_third",
        ],
        default=argparse.SUPPRESS,
        help="manual = fixed rect; window_* = live window region on Windows",
    )
    cap.add_argument(
        "--window-title",
        dest="window_title",
        default=argparse.SUPPRESS,
        help="Substring match for window_* modes (as in GUI list)",
    )
    cap.add_argument(
        "--active-window",
        action="store_true",
        default=False,
        help=(
            "Foreground window only (Windows): print ACTIVE_WIN frame/client coords, "
            "then set target to that title and capture. Use with window_* modes; "
            "overrides --window-title. With no --config and no --pages/--base-dir, "
            "loads bundled default_config.json."
        ),
    )
    cap.add_argument(
        "--window-frame",
        action="store_true",
        default=False,
        help="Include title bar and borders (outer window rect; default is client area only).",
    )
    cap.add_argument(
        "--window-match-first",
        action="store_true",
        default=False,
        help="If several windows match the title substring, pick first list match (not foreground).",
    )
    cap.add_argument(
        "--window-capture-backend",
        choices=["printwindow", "screen"],
        default=argparse.SUPPRESS,
        dest="window_capture_backend",
        help="Windows window_*: printwindow=HWND capture (default); screen=mss/region.",
    )
    cap.add_argument(
        "--hide-cursor-during-capture",
        action="store_true",
        default=False,
        help="Move the mouse outside the capture rectangle during each screen capture, then restore it.",
    )
    cap.add_argument(
        "--debug-capture",
        action="store_true",
        default=False,
        help="Print DEBUG_RECT lines (window + crop); limit pages to --debug-max-pages (default 5).",
    )
    cap.add_argument(
        "--debug-max-pages",
        type=int,
        default=argparse.SUPPRESS,
        metavar="N",
        help="With --debug-capture, max pages for all phases (default 5).",
    )
    cap.add_argument(
        "--phase",
        choices=[PHASE_CAPTURE, PHASE_OCR, PHASE_PDF, PHASE_ALL],
        default=argparse.SUPPRESS,
        help="Run only one phase, or all phases: capture, ocr, pdf, all.",
    )
    mode = cap.add_mutually_exclusive_group()
    mode.add_argument(
        "--output-mode",
        choices=sorted(OUTPUT_MODES),
        default=None,
        help=(
            "High-level job output: images, text, pdf_image, pdf_searchable, audio "
            f"(default: {OUTPUT_PDF_IMAGE})."
        ),
    )
    mode.add_argument(
        "--images",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_IMAGES,
        help="Capture PNG files only.",
    )
    mode.add_argument(
        "--pdf-image",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_PDF_IMAGE,
        help="Capture PNG files and build a normal image PDF (default).",
    )
    mode.add_argument(
        "--text",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_TEXT,
        help="Capture PNG files and run OCR text output only.",
    )
    mode.add_argument(
        "--pdf-searchable",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_PDF_SEARCHABLE,
        help="Capture PNG files, run OCR, and build a searchable PDF.",
    )
    mode.add_argument(
        "--audio",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_AUDIO,
        help="Capture PNG files, run OCR, and build voice MP3 output.",
    )
    cap.add_argument(
        "--resume",
        dest="resume",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Resume from completed per-page outputs (default).",
    )
    cap.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Ignore resume state and process requested phases again.",
    )
    cap.add_argument(
        "--force-phase",
        choices=[PHASE_CAPTURE, PHASE_OCR, PHASE_PDF, "voice", PHASE_ALL],
        default=argparse.SUPPRESS,
        help="Regenerate one phase even when resume outputs exist.",
    )
    cap.add_argument(
        "--base-dir",
        type=Path,
        dest="base_dir",
        default=None,
        help="Parent output folder (absolute path recommended)",
    )
    cap.add_argument("--left", type=int, default=None, help="Capture rectangle left (screen px)")
    cap.add_argument("--top", type=int, default=None, help="Capture rectangle top (screen px)")
    cap.add_argument("--width", type=int, default=None, help="Capture rectangle width")
    cap.add_argument("--height", type=int, default=None, help="Capture rectangle height")
    cap.add_argument(
        "--delay",
        type=float,
        dest="delay_sec",
        default=None,
        help="Seconds to wait after each page-turn key",
    )
    cap.add_argument(
        "--next-key",
        dest="next_key",
        default=None,
        help="Key name for pyautogui.press (e.g. pagedown, right, space, enter)",
    )
    cap.add_argument(
        "--no-images",
        dest="capture_images",
        action="store_false",
        default=True,
        help="Skip PNG capture (use existing files in tmp/)",
    )
    cap.add_argument(
        "--no-pdf",
        dest="build_pdf",
        action="store_false",
        default=True,
        help="Skip Phase III PDF generation.",
    )
    cap.add_argument(
        "--ocr",
        action="store_true",
        default=False,
        help="Run Phase II Google Gemini OCR + per-page .txt/.ocr.json.",
    )
    cap.add_argument(
        "--no-ocr",
        action="store_true",
        default=False,
        help="Skip OCR even if enabled in --config.",
    )
    cap.add_argument(
        "--ocr-lang",
        dest="ocr_lang",
        default="eng",
        help="OCR language hint (e.g. kor, eng).",
    )
    cap.add_argument(
        "--voice",
        action="store_true",
        default=False,
        help="Synthesize MP3 per page (Google Cloud TTS; needs credentials)",
    )
    cap.add_argument("--voice-lang", dest="voice_lang_code", default="en-US")
    cap.add_argument("--voice-model", dest="voice_model", default="en-US-Wavenet-A")
    cap.add_argument("--voice-gender", dest="voice_gender", default="FEMALE")

    return p


def _cmd_gui(_: argparse.Namespace) -> int:
    from gui.app import run_gui

    run_gui()
    return 0


def _apply_phase_selection(cfg: CaptureConfig, phase: str) -> None:
    cfg.run_capture_phase = phase in {PHASE_CAPTURE, PHASE_ALL}
    cfg.run_ocr_phase = phase in {PHASE_OCR, PHASE_ALL}
    cfg.run_pdf_phase = phase in {PHASE_PDF, PHASE_ALL}
    cfg.capture_images = cfg.run_capture_phase
    cfg.ocr = cfg.run_ocr_phase
    cfg.build_pdf = cfg.run_pdf_phase


def _apply_output_mode_selection(cfg: CaptureConfig, output_mode: str) -> None:
    cfg.output_mode = output_mode
    cfg.apply_output_mode()


def _sync_legacy_phase_flags(cfg: CaptureConfig) -> None:
    cfg.run_capture_phase = bool(cfg.capture_images)
    cfg.run_ocr_phase = bool(cfg.ocr)
    cfg.run_pdf_phase = bool(cfg.build_pdf)
    if cfg.run_pdf_phase and cfg.run_ocr_phase:
        cfg.output_mode = OUTPUT_PDF_SEARCHABLE
    elif cfg.run_pdf_phase:
        cfg.output_mode = OUTPUT_PDF_IMAGE
    elif cfg.run_ocr_phase:
        cfg.output_mode = OUTPUT_AUDIO if cfg.voice else OUTPUT_TEXT
    else:
        cfg.output_mode = OUTPUT_IMAGES


def _apply_cli_overrides_to_config(cfg: CaptureConfig, args: argparse.Namespace) -> None:
    """When using --config, CLI flags override only if provided."""
    if hasattr(args, "phase"):
        _apply_phase_selection(cfg, str(args.phase))
    if getattr(args, "output_mode", None):
        _apply_output_mode_selection(cfg, str(args.output_mode))
        if hasattr(args, "phase"):
            _apply_phase_selection(cfg, str(args.phase))
    if args.title is not None:
        cfg.title = str(args.title).strip() or DEFAULT_BOOK_TITLE
    if args.pages is not None:
        cfg.n_pages = int(args.pages)
    if args.start_page is not None:
        cfg.start_page = int(args.start_page)
    if args.base_dir is not None:
        cfg.base_dir = str(args.base_dir)
    if hasattr(args, "capture_mode"):
        cfg.capture_mode = str(args.capture_mode)
    if hasattr(args, "window_title"):
        cfg.target_window_title = str(args.window_title or "").strip()
    if getattr(args, "delay_sec", None) is not None:
        cfg.delay_sec = float(args.delay_sec)
    if getattr(args, "next_key", None) is not None:
        cfg.next_key = str(args.next_key)
    if (
        getattr(args, "left", None) is not None
        and getattr(args, "top", None) is not None
        and getattr(args, "width", None) is not None
        and getattr(args, "height", None) is not None
    ):
        cfg.rect = Rect(
            left=int(args.left),
            top=int(args.top),
            width=int(args.width),
            height=int(args.height),
        )
    if getattr(args, "ocr", False):
        cfg.ocr = True
        cfg.run_ocr_phase = True
    if getattr(args, "voice", False):
        cfg.voice = True
    if getattr(args, "window_frame", False):
        cfg.use_window_client_rect = False
    if getattr(args, "window_match_first", False):
        cfg.prefer_foreground_window_match = False
    if getattr(args, "debug_capture", False):
        cfg.debug_capture = True
    if getattr(args, "debug_max_pages", None) is not None:
        cfg.debug_capture_max_pages = max(1, int(args.debug_max_pages))
    if hasattr(args, "window_capture_backend"):
        cfg.window_capture_backend = str(args.window_capture_backend)
    if getattr(args, "hide_cursor_during_capture", False):
        cfg.hide_cursor_during_capture = True
    if hasattr(args, "resume"):
        cfg.resume = bool(args.resume)
    if hasattr(args, "force_phase"):
        cfg.force_phase = str(args.force_phase)
    if "--no-images" in sys.argv:
        cfg.capture_images = False
        cfg.run_capture_phase = False
    if "--no-pdf" in sys.argv:
        cfg.build_pdf = False
        cfg.run_pdf_phase = False
    if getattr(args, "no_ocr", False):
        cfg.ocr = False
        cfg.run_ocr_phase = False
    if not hasattr(args, "phase") and not getattr(args, "output_mode", None):
        _sync_legacy_phase_flags(cfg)


def _cmd_capture(args: argparse.Namespace) -> int:
    from core.pipeline import run_capture

    use_active = getattr(args, "active_window", False)
    if use_active and sys.platform != "win32":
        print("Error: --active-window is only supported on Windows.", file=sys.stderr)
        return 2

    if args.config:
        cfg = CaptureConfig.from_json_file(args.config)
        _apply_cli_overrides_to_config(cfg, args)
    elif use_active and not all(x is not None for x in (args.pages, args.base_dir)):
        path = bundled_default_config_path()
        if not path.is_file():
            print(
                "Error: use --config FILE.json, or pass --pages --base-dir, "
                f"or ship {path.name} in repo root.",
                file=sys.stderr,
            )
            return 2
        cfg = CaptureConfig.from_json_file(path)
        _apply_cli_overrides_to_config(cfg, args)
    else:
        mode = getattr(args, "capture_mode", CAPTURE_MANUAL)
        requested_phase = str(getattr(args, "phase", PHASE_ALL))
        wants_capture = requested_phase in {PHASE_CAPTURE, PHASE_ALL}
        base_required = (args.pages, args.base_dir)
        if not all(x is not None for x in base_required):
            print(
                "Error: without --config pass --pages --base-dir "
                "(or use --active-window alone to load bundled default_config.json).",
                file=sys.stderr,
            )
            return 2
        if mode == CAPTURE_MANUAL:
            rect_required = (
                args.left,
                args.top,
                args.width,
                args.height,
            )
            if wants_capture and not all(x is not None for x in rect_required):
                print(
                    "Error: manual mode requires --left --top --width --height",
                    file=sys.stderr,
                )
                return 2
            rect = Rect(
                left=int(args.left or 0),
                top=int(args.top or 0),
                width=int(args.width or 0),
                height=int(args.height or 0),
            )
            window_title = ""
        else:
            wt = str(getattr(args, "window_title", "") or "").strip()
            if wants_capture and not wt and not use_active:
                print(
                    "Error: window capture modes require --window-title or --active-window",
                    file=sys.stderr,
                )
                return 2
            rect = Rect(0, 0, 0, 0)
            window_title = wt

        cfg = CaptureConfig(
            title=(str(args.title).strip() if args.title is not None else DEFAULT_BOOK_TITLE)
            or DEFAULT_BOOK_TITLE,
            n_pages=args.pages,
            start_page=int(args.start_page if args.start_page is not None else 1),
            base_dir=str(args.base_dir),
            rect=rect,
            capture_mode=str(mode),
            target_window_title=window_title,
            use_window_client_rect=not getattr(args, "window_frame", False),
            prefer_foreground_window_match=not getattr(
                args, "window_match_first", False
            ),
            hide_cursor_during_capture=bool(
                getattr(args, "hide_cursor_during_capture", False)
            ),
            delay_sec=float(args.delay_sec if args.delay_sec is not None else 1.0),
            next_key=str(args.next_key if args.next_key is not None else "pagedown"),
            capture_images=args.capture_images,
            build_pdf=args.build_pdf,
            ocr=bool(args.ocr) and not getattr(args, "no_ocr", False),
            run_capture_phase=bool(args.capture_images),
            run_ocr_phase=bool(args.ocr) and not getattr(args, "no_ocr", False),
            run_pdf_phase=bool(args.build_pdf),
            resume=bool(getattr(args, "resume", True)),
            force_phase=str(getattr(args, "force_phase", "")),
            ocr_lang=args.ocr_lang,
            voice=bool(args.voice),
            voice_lang_code=args.voice_lang_code,
            voice_model=args.voice_model,
            voice_gender=args.voice_gender,
            debug_capture=getattr(args, "debug_capture", False),
            debug_capture_max_pages=(
                max(1, int(getattr(args, "debug_max_pages")))
                if hasattr(args, "debug_max_pages")
                else 5
            ),
            window_capture_backend=getattr(
                args, "window_capture_backend", WINDOW_CAPTURE_PRINTWINDOW
            ),
        )
        if getattr(args, "output_mode", None):
            _apply_output_mode_selection(cfg, str(args.output_mode))
        if hasattr(args, "phase"):
            _apply_phase_selection(cfg, str(args.phase))
        if "--no-images" in sys.argv:
            cfg.capture_images = False
            cfg.run_capture_phase = False
        if "--no-pdf" in sys.argv:
            cfg.build_pdf = False
            cfg.run_pdf_phase = False
        if getattr(args, "no_ocr", False):
            cfg.ocr = False
            cfg.run_ocr_phase = False
        if not hasattr(args, "phase") and not getattr(args, "output_mode", None):
            _sync_legacy_phase_flags(cfg)

    if use_active:
        from core import windows_util as wu

        if cfg.capture_mode == CAPTURE_MANUAL:
            print(
                "Error: --active-window needs capture_mode window_full or "
                "window_left_third / window_right_third (not manual).",
                file=sys.stderr,
            )
            return 2
        try:
            t = wu.print_active_window_rects()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        cfg.target_window_title = t
        cfg.prefer_foreground_window_match = True

    return run_capture(cfg)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
