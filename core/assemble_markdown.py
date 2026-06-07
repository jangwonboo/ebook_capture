"""Assemble per-page OCR JSON into one holistic Markdown file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

from core.assemble_options import AssembleOptions
from core.book_structure import build_book_structure, structure_to_mapping
from core.markdown_render import render_markdown
from core.ocr_json_loader import load_ocr_pages
from core.paragraph_merge import normalize_paragraphs

ProgressFn = Callable[[str], None]


def _emit(progress: ProgressFn | None, msg: str) -> None:
    if progress:
        progress(msg)
    print(msg, flush=True)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


def _atomic_write_json(path: Path, data: dict) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def assemble_markdown(
    *,
    title: str,
    tmp_dir: Path | str,
    output_md_path: Path | str,
    structure_json_path: Path | str | None = None,
    options: AssembleOptions | None = None,
    progress: ProgressFn | None = None,
) -> Path:
    """Build ``output_md_path`` from ``tmp_dir/{title}_*.ocr.json``."""
    opts = options or AssembleOptions()

    pages = load_ocr_pages(tmp_dir, title)
    _emit(progress, f"ASSEMBLE_LOAD pages={len(pages)} tmp={tmp_dir}")
    _emit(progress, f"ASSEMBLE_STYLE {opts.style.value}")

    if opts.fix_text:
        pages = normalize_paragraphs(pages)
        _emit(progress, "ASSEMBLE_FIX_TEXT reflow + paragraph merge")

    structure = build_book_structure(title, pages)
    _emit(
        progress,
        f"ASSEMBLE_STRUCTURE chapters={len(structure.chapters)} "
        f"page_range={structure.page_range}",
    )

    markdown = render_markdown(
        structure,
        include_page_comments=opts.include_page_comments(),
        body_only=opts.body_only,
    )
    out = Path(output_md_path)
    _atomic_write_text(out, markdown)
    _emit(progress, f"ASSEMBLE_MD_OK {out}")

    if structure_json_path is not None:
        struct_path = Path(structure_json_path)
        _atomic_write_json(struct_path, structure_to_mapping(structure))
        _emit(progress, f"ASSEMBLE_STRUCTURE_OK {struct_path}")

    return out

