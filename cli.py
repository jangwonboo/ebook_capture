"""CLI — single ``run`` command with output: images | pdf | text."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import (
    CAPTURE_MANUAL,
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

    # Deprecated aliases → run
    for name, default_out in (
        ("capture", OUTPUT_PDF),
        ("ocr", OUTPUT_TEXT),
        ("ocr-pdf", OUTPUT_TEXT),
        ("assemble", OUTPUT_TEXT),
        ("assemble-md", OUTPUT_TEXT),
    ):
        alias = sub.add_parser(name, help=f"Deprecated: use run --{default_out.replace('images','images')}.")
        alias.set_defaults(_handler=_cmd_run, _deprecated=name)
        _add_book_args(alias)
        if name in {"capture", "ocr", "ocr-pdf"}:
            _add_capture_args(alias)
        _add_output_args(alias, default=default_out)
        _add_run_options(alias)
        if name == "ocr":
            alias.add_argument("source", nargs="?", type=Path, default=None)
        if name == "ocr-pdf":
            alias.add_argument("pdf", type=Path)
        if name in {"assemble", "assemble-md"}:
            alias.add_argument("--output-md", type=Path, default=None)
            alias.add_argument("--structure-json", type=Path, default=None)
            alias.add_argument(
                "--page-comments",
                dest="page_comments",
                action="store_const",
                const=True,
                default=None,
            )
            alias.add_argument(
                "--no-page-comments",
                dest="page_comments",
                action="store_const",
                const=False,
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

    # Legacy alias args
    if getattr(args, "source", None):
        cfg.input_pdf = str(Path(args.source).expanduser())
        cfg.output_mode = OUTPUT_TEXT
    if getattr(args, "pdf", None):
        cfg.input_pdf = str(Path(args.pdf).expanduser())
        cfg.output_mode = OUTPUT_TEXT

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

    if getattr(args, "input_pdf", None) or getattr(args, "source", None) or getattr(args, "pdf", None):
        if not args.title and not args.config:
            src = getattr(args, "input_pdf", None) or getattr(args, "source", None) or getattr(args, "pdf", None)
            cfg = CaptureConfig(
                title=Path(src).stem if src else DEFAULT_BOOK_TITLE,
                base_dir=str(Path(src).parent if src else "."),
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


def _cmd_gui(_: argparse.Namespace) -> int:
    from gui.app import run_gui

    run_gui()
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from core.job_runner import run_output_job

    deprecated = getattr(args, "_deprecated", None)
    if deprecated:
        print(f"Note: '{deprecated}' is deprecated; use: ebook-capture run --...", file=sys.stderr)

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
