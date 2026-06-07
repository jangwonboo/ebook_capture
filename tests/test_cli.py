"""CLI parser and command wiring tests."""

from __future__ import annotations

import pytest

from cli import _build_parser, main


def test_parser_run_output_pdf() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["run", "--pages", "10", "--base-dir", "E:/out", "--pdf"]
    )
    assert args.command == "run"
    assert args.output_mode == "pdf"


def test_parser_capture_alias() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["capture", "--pages", "10", "--base-dir", "E:/out", "--pdf"]
    )
    assert args.command == "capture"
    assert args.output_mode == "pdf"


def test_parser_ocr_command() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["ocr", "E:/book.pdf", "--title", "Book", "--base-dir", "E:/out"]
    )
    assert args.command == "ocr"
    assert str(args.source).replace("\\", "/") == "E:/book.pdf"


def test_parser_assemble_command() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["assemble", "--title", "MyBook", "--base-dir", "E:/out", "--style", "prose"]
    )
    assert args.command == "assemble"
    assert args.style == "prose"


def test_parser_assemble_md_alias() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        ["assemble-md", "--title", "MyBook", "--base-dir", "E:/out"]
    )
    assert args.command == "assemble-md"


def test_main_assemble_missing_args_returns_2() -> None:
    rc = main(["assemble"])
    assert rc == 2
