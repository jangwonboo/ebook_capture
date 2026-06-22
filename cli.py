"""CLI — single ``run`` command with output: images | pdf | text."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import (
    CAPTURE_MANUAL,
    CAPTURE_SCREEN_LEFT_THIRD,
    CaptureConfig,
    DEFAULT_BOOK_TITLE,
    OUTPUT_IMAGES,
    OUTPUT_MODES,
    OUTPUT_PDF,
    OUTPUT_TEXT,
    PHASE_ALL,
    PHASE_CAPTURE,
    PHASE_OCR,
    PHASE_PDF,
    Rect,
    WINDOW_CAPTURE_PRINTWINDOW,
    bundled_default_config_path,
    is_fixed_screen_capture_mode,
    normalize_output_mode,
)


def _add_book_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="JSON settings (CLI overrides).")
    parser.add_argument("--title", default=None, help="Book folder under --base-dir.")
    parser.add_argument(
        "--base-dir",
        type=Path,
        dest="base_dir",
        default=None,
        help="Parent output folder (absolute path).",
    )


def _add_output_args(parser: argparse.ArgumentParser, *, default: str = OUTPUT_PDF) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--output",
        dest="output_mode",
        choices=sorted(OUTPUT_MODES),
        default=None,
        help=f"Output type (default from config or {default}).",
    )
    group.add_argument(
        "--images",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_IMAGES,
        help="PNG pages only.",
    )
    group.add_argument(
        "--pdf",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_PDF,
        help="PNG + merged image PDF.",
    )
    group.add_argument(
        "--text",
        dest="output_mode",
        action="store_const",
        const=OUTPUT_TEXT,
        help="OCR JSON + Markdown (uses PNG or PDF source, then assemble).",
    )


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt for planned steps.",
    )
    parser.add_argument(
        "--input-pdf",
        type=Path,
        default=None,
        help="PDF source for --text when tmp/*.png is absent.",
    )
    parser.add_argument(
        "--style",
        choices=["full", "prose", "raw"],
        default=None,
        help="Markdown style for --text (default: assemble_style in config).",
    )
    parser.add_argument("--ocr-lang", dest="ocr_lang", default=argparse.SUPPRESS)
    parser.add_argument("--ocr-prompt", dest="ocr_text_prompt", default=argparse.SUPPRESS)
    parser.add_argument(
        "--ocr-prompt-file",
        dest="ocr_prompt_file",
        type=Path,
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--resume", dest="resume", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument(
        "--force-phase",
        choices=[PHASE_CAPTURE, PHASE_OCR, PHASE_PDF, PHASE_ALL],
        default=argparse.SUPPRESS,
    )


def _add_capture_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pages", type=int, metavar="N", default=None)
    parser.add_argument("--start-page", type=int, dest="start_page", default=None)
    parser.add_argument(
        "--capture-mode",
        choices=[
            CAPTURE_MANUAL,
            "window_full",
            "window_left_third",
            "window_right_third",
            CAPTURE_SCREEN_LEFT_THIRD,
        ],
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--window-title", dest="window_title", default=argparse.SUPPRESS)
    parser.add_argument("--active-window", action="store_true", default=False)
    parser.add_argument("--window-frame", action="store_true", default=False)
    parser.add_argument("--window-match-first", action="store_true", default=False)
    parser.add_argument(
        "--window-capture-backend",
        choices=["printwindow", "screen"],
        default=argparse.SUPPRESS,
        dest="window_capture_backend",
    )
    parser.add_argument("--hide-cursor-during-capture", action="store_true", default=False)
    parser.add_argument("--debug-capture", action="store_true", default=False)
    parser.add_argument("--debug-max-pages", type=int, default=argparse.SUPPRESS, metavar="N")
    parser.add_argument("--left", type=int, default=None)
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--delay", type=float, dest="delay_sec", default=None)
    parser.add_argument("--next-key", dest="next_key", default=None)
    parser.add_argument(
        "--key-delivery",
        dest="key_delivery",
        choices=[
            "auto",
            "sendinput",
            "postmessage",
            "postmessage_top",
            "pyautogui",
        ],
        default=None,
        help="How to send next_key to the reader window (default from config).",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ebook-capture",
        description=(
            "Ebook capture: choose one output — --images, --pdf, or --text. "
            "Missing steps are detected and confirmed before running."
        ),
    )
    sub = p.add_subparsers(dest="command", required=True)

    gui = sub.add_parser("gui", help="PyQt5 GUI.")
    gui.set_defaults(_handler=_cmd_gui)

    run = sub.add_parser(
        "run",
        help="Run job: --images | --pdf | --text (default pdf).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ebook-capture run --config default_config.json --pdf\n"
            "  ebook-capture run --title Book --base-dir E:/ebook --text -y\n"
            "  ebook-capture run --config cfg.json --text --input-pdf book.pdf\n"
        ),
    )
    run.set_defaults(_handler=_cmd_run)
    _add_book_args(run)
    _add_capture_args(run)
    _add_output_args(run)
    _add_run_options(run)

    test_key = sub.add_parser(
        "test-key",
        help="Test page-turn key: pin window/rect, send next_key once (Aladin etc.).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ebook-capture test-key --config default_config.json\n"
            "  ebook-capture test-key --config default_config.json --repeat 3\n"
            "  ebook-capture test-key --config default_config.json --screenshot\n"
        ),
    )
    test_key.set_defaults(_handler=_cmd_test_key)
    _add_book_args(test_key)
    _add_capture_args(test_key)
    test_key.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Send next_key N times (default 1).",
    )
    test_key.add_argument(
        "--screenshot",
        action="store_true",
        help="Save before/after PNG of the capture rect under tmp/.",
    )

    inspect = sub.add_parser(
        "inspect",
        help="Check reader window position and capture rect (no capture).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ebook-capture inspect --config default_config.jsonc\n"
            "  ebook-capture inspect --config default_config.jsonc --screenshot\n"
            "  ebook-capture inspect --config default_config.jsonc --no-fit\n"
        ),
    )
    inspect.set_defaults(_handler=_cmd_inspect)
    _add_book_args(inspect)
    _add_capture_args(inspect)
    inspect.add_argument(
        "--no-fit",
        action="store_true",
        help="Do not move/resize window; only report current rects.",
    )
    inspect.add_argument(
        "--screenshot",
        action="store_true",
        help="Save one probe PNG of the capture rect under tmp/inspect_probe.png.",
    )

    return p


def _apply_args(cfg: CaptureConfig, args: argparse.Namespace) -> CaptureConfig:
    if getattr(args, "output_mode", None):
        cfg.output_mode = normalize_output_mode(str(args.output_mode))
    if getattr(args, "style", None):
        cfg.assemble_style = str(args.style)
    if getattr(args, "input_pdf", None):
        cfg.input_pdf = str(Path(args.input_pdf).expanduser())
    if getattr(args, "title", None) is not None:
        cfg.title = str(args.title).strip() or DEFAULT_BOOK_TITLE
    if getattr(args, "base_dir", None) is not None:
        cfg.base_dir = str(Path(args.base_dir).expanduser())
    if getattr(args, "pages", None) is not None:
        cfg.n_pages = int(args.pages)
    if getattr(args, "start_page", None) is not None:
        cfg.start_page = int(args.start_page)
    if hasattr(args, "capture_mode"):
        cfg.capture_mode = str(args.capture_mode)
    if hasattr(args, "window_title"):
        cfg.target_window_title = str(args.window_title or "").strip()
    if getattr(args, "delay_sec", None) is not None:
        cfg.delay_sec = float(args.delay_sec)
    if getattr(args, "next_key", None) is not None:
        cfg.next_key = str(args.next_key)
    if getattr(args, "key_delivery", None) is not None:
        cfg.key_delivery = str(args.key_delivery)
    if all(getattr(args, k, None) is not None for k in ("left", "top", "width", "height")):
        cfg.rect = Rect(int(args.left), int(args.top), int(args.width), int(args.height))
    if hasattr(args, "ocr_lang"):
        cfg.ocr_lang = str(args.ocr_lang)
    if hasattr(args, "ocr_text_prompt"):
        cfg.ocr_text_prompt = str(args.ocr_text_prompt or "")
    if hasattr(args, "ocr_prompt_file"):
        cfg.ocr_prompt_file = str(args.ocr_prompt_file or "")
    if hasattr(args, "resume"):
        cfg.resume = bool(args.resume)
    if hasattr(args, "force_phase"):
        cfg.force_phase = str(args.force_phase)
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

    return cfg.normalize()


def _resolve_config(args: argparse.Namespace) -> CaptureConfig | int:
    use_active = getattr(args, "active_window", False)

    if args.config:
        cfg = CaptureConfig.from_json_file(args.config)
        return _apply_args(cfg, args)

    if use_active:
        path = bundled_default_config_path()
        if not path.is_file():
            print(f"Error: missing {path.name}", file=sys.stderr)
            return 2
        cfg = CaptureConfig.from_json_file(path)
        return _apply_args(cfg, args)

    if getattr(args, "input_pdf", None):
        if not args.title and not args.config:
            src = Path(args.input_pdf).expanduser()
            cfg = CaptureConfig(
                title=src.stem,
                base_dir=str(src.parent),
                output_mode=OUTPUT_TEXT,
            )
            return _apply_args(cfg, args)
        if args.title and args.base_dir:
            cfg = CaptureConfig(
                title=str(args.title).strip(),
                base_dir=str(Path(args.base_dir).expanduser()),
                output_mode=OUTPUT_TEXT,
            )
            return _apply_args(cfg, args)

    if args.title and args.base_dir:
        cfg = CaptureConfig(
            title=str(args.title).strip() or DEFAULT_BOOK_TITLE,
            base_dir=str(Path(args.base_dir).expanduser()),
        )
        return _apply_args(cfg, args)

    print("Error: pass --config or --title with --base-dir.", file=sys.stderr)
    return 2


def _apply_active_window_title(cfg: CaptureConfig) -> str | None:
    from core import windows_util as wu

    if cfg.capture_mode == CAPTURE_MANUAL:
        return "--active-window needs window_* or screen_* capture mode."
    try:
        cfg.target_window_title = wu.print_active_window_rects()
    except RuntimeError as exc:
        return str(exc)
    cfg.prefer_foreground_window_match = True
    return None


def _cmd_gui(_: argparse.Namespace) -> int:
    from gui.app import run_gui

    run_gui()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from core.job_runner import run_output_job

    if getattr(args, "active_window", False) and sys.platform != "win32":
        print("Error: --active-window is Windows only.", file=sys.stderr)
        return 2

    result = _resolve_config(args)
    if isinstance(result, int):
        return result
    cfg = result

    if getattr(args, "active_window", False):
        from core import windows_util as wu

        if cfg.capture_mode == CAPTURE_MANUAL:
            print("Error: --active-window needs window_* capture mode.", file=sys.stderr)
            return 2
        try:
            cfg.target_window_title = wu.print_active_window_rects()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        cfg.prefer_foreground_window_match = True

    return run_output_job(cfg, assume_yes=bool(getattr(args, "yes", False)))


def _cmd_test_key(args: argparse.Namespace) -> int:
    import time

    from core.pipeline import (
        _debug_rect_lines,
        _pin_capture_target,
        _screen_region,
        _send_page_turn_key,
    )
    from core.screen_capture import screenshot_region

    if getattr(args, "active_window", False) and sys.platform != "win32":
        print("Error: --active-window is Windows only.", file=sys.stderr)
        return 2

    result = _resolve_config(args)
    if isinstance(result, int):
        return result
    cfg = result

    if getattr(args, "active_window", False):
        from core import windows_util as wu

        if cfg.capture_mode == CAPTURE_MANUAL:
            print("Error: --active-window needs window_* or screen_* capture mode.", file=sys.stderr)
            return 2
        try:
            cfg.target_window_title = wu.print_active_window_rects()
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        cfg.prefer_foreground_window_match = True

    try:
        cfg.validate()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    repeat = max(1, int(getattr(args, "repeat", 1) or 1))
    print(f"TEST_KEY config={getattr(args, 'config', '(cli args)')}")
    print(f"TEST_KEY next_key={cfg.next_key!r} focus_clicks={cfg.reader_focus_clicks}")
    print(f"TEST_KEY key_delivery={cfg.key_delivery!r}")
    try:
        _pin_capture_target(cfg, print)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Hint: open the Aladin reader, click it to focus, then retry. "
            "Or use --active-window with the reader in front.",
            file=sys.stderr,
        )
        return 2
    for line in _debug_rect_lines(cfg):
        print(line)

    left, top, w, h = _screen_region(cfg)
    before_path = None
    if getattr(args, "screenshot", False):
        cfg.tmp_dir().mkdir(parents=True, exist_ok=True)
        before_path = cfg.tmp_dir() / "test_key_before.png"
        screenshot_region(left, top, w, h).save(before_path)
        print(f"TEST_KEY screenshot_before {before_path} size={w}x{h}")

    for i in range(repeat):
        print(f"TEST_KEY send {i + 1}/{repeat}")
        _send_page_turn_key(cfg, print)
        if i + 1 < repeat:
            time.sleep(cfg.delay_sec)

    if getattr(args, "screenshot", False):
        time.sleep(cfg.delay_sec)
        after_path = cfg.tmp_dir() / "test_key_after.png"
        screenshot_region(left, top, w, h).save(after_path)
        print(f"TEST_KEY screenshot_after {after_path}")
        if before_path is not None:
            print("TEST_KEY compare the two PNGs to confirm the page changed.")

    print("TEST_KEY done")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    from core.pipeline import _debug_rect_lines
    from core.screen_capture import screenshot_region

    if getattr(args, "active_window", False) and sys.platform != "win32":
        print("Error: --active-window is Windows only.", file=sys.stderr)
        return 2

    result = _resolve_config(args)
    if isinstance(result, int):
        return result
    cfg = result

    if getattr(args, "active_window", False):
        err = _apply_active_window_title(cfg)
        if err:
            print(f"Error: {err}", file=sys.stderr)
            return 2

    try:
        cfg.validate()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    from core import windows_util as wu

    try:
        hwnd, title = wu.pin_target_window(
            cfg.target_window_title,
            prefer_foreground=cfg.prefer_foreground_window_match,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Hint: open the reader, click it to focus, then retry inspect.",
            file=sys.stderr,
        )
        return 2

    cfg.pinned_target_hwnd = hwnd
    layout_ok = True
    print(f"INSPECT target title={title!r} hwnd=0x{hwnd:x}")
    print(f"INSPECT capture_mode={cfg.capture_mode!r}")

    if is_fixed_screen_capture_mode(cfg.capture_mode):
        print("INSPECT --- before fit ---")
        ok_before, before_lines = wu.describe_window_screen_left_third_fit(hwnd)
        for line in before_lines:
            print(line.replace("DEBUG_RECT", "INSPECT", 1))
        if not getattr(args, "no_fit", False):
            target = wu.screen_left_third_rect()
            wu.fit_window_to_screen_left_third(hwnd)
            print(
                "INSPECT fit applied "
                f"target_frame left={target[0]} top={target[1]} "
                f"width={target[2]} height={target[3]}"
            )
            print("INSPECT --- after fit ---")
            layout_ok, after_lines = wu.describe_window_screen_left_third_fit(hwnd)
            for line in after_lines:
                print(line.replace("DEBUG_RECT", "INSPECT", 1))
        else:
            layout_ok = ok_before
        capture = wu.capture_rect_screen_left_third(
            hwnd,
            use_client_rect=cfg.use_window_client_rect,
        )
    else:
        for line in _debug_rect_lines(cfg):
            print(line.replace("DEBUG_RECT", "INSPECT", 1))
        capture = wu.resolve_screen_rect(
            cfg.target_window_title,
            cfg.capture_mode,
            use_client_rect=cfg.use_window_client_rect,
            prefer_foreground=cfg.prefer_foreground_window_match,
            pinned_hwnd=hwnd,
        )
        layout_ok = True

    left, top, width, height = capture
    cfg.pinned_capture_rect = capture
    print(
        "INSPECT capture_rect "
        f"left={left} top={top} width={width} height={height} "
        f"(right={left + width} bottom={top + height})"
    )

    if getattr(args, "screenshot", False):
        cfg.tmp_dir().mkdir(parents=True, exist_ok=True)
        probe = cfg.tmp_dir() / "inspect_probe.png"
        screenshot_region(left, top, width, height).save(probe)
        print(f"INSPECT screenshot {probe} size={width}x{height}")

    if layout_ok:
        print("INSPECT_OK reader layout matches target")
        return 0
    print("INSPECT_FAIL reader layout does not match target", file=sys.stderr)
    return 1


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
