"""CLI parser and command wiring tests."""

from __future__ import annotations

from cli import _build_parser, main


def test_parser_run_output_pdf() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["run", "--pages", "10", "--base-dir", "E:/out", "--pdf"]
    )
    assert args.command == "run"
    assert args.output_mode == "pdf"


def test_parser_run_text_with_input_pdf() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--title",
            "Book",
            "--base-dir",
            "E:/out",
            "--text",
            "--input-pdf",
            "E:/book.pdf",
        ]
    )
    assert args.command == "run"
    assert args.output_mode == "text"
    assert str(args.input_pdf).replace("\\", "/") == "E:/book.pdf"


def test_main_run_missing_args_returns_2() -> None:
    rc = main(["run"])
    assert rc == 2
