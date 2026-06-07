"""Render assembled book structure to Markdown."""

from __future__ import annotations

from core.book_structure import (
    BACK_MATTER_KIND,
    BookStructure,
    ChapterDoc,
    ContentBlock,
    FRONT_MATTER_KIND,
)


def _render_block(block: ContentBlock, *, body_only: bool = False) -> list[str]:
    text = block.text.strip()
    if not text:
        return []
    if body_only and block.section_type != "body":
        return []

    if block.section_type == "body":
        return [text, ""]
    if block.section_type in {"section_title", "title"}:
        flat = text.replace("\n", " ")
        return [f"### {flat}", ""]
    if block.section_type == "subtitle":
        return [f"#### {text.replace(chr(10), ' ')}", ""]
    if block.section_type == "toc":
        return ["### 목차 (원본)", "", text, ""]
    if block.section_type == "figure":
        return ["> **Figure**", ">", text.replace("\n", "\n> "), ""]
    if block.section_type == "caption":
        return [f"*{text.replace(chr(10), ' ')}*", ""]
    if block.section_type == "footnote":
        return [f"> **Footnote** {text}", ""]
    return [text, ""]


def _chapter_heading_level(chapter: ChapterDoc) -> str:
    if chapter.kind == FRONT_MATTER_KIND:
        return "##"
    if chapter.kind == BACK_MATTER_KIND:
        return "##"
    return "##"


def render_chapter(
    chapter: ChapterDoc,
    *,
    include_page_comments: bool,
    body_only: bool = False,
) -> list[str]:
    if chapter.kind == FRONT_MATTER_KIND:
        lines = ["## Front matter", ""]
    else:
        lines = [f"{_chapter_heading_level(chapter)} {chapter.heading}", ""]
    if include_page_comments:
        lines.append(f"<!-- pages: {chapter.start_page}-{chapter.end_page} -->")
        lines.append("")
    for block in chapter.blocks:
        lines.extend(_render_block(block, body_only=body_only))
    lines.append("---")
    lines.append("")
    return lines


def render_markdown(
    structure: BookStructure,
    *,
    include_page_comments: bool = True,
    body_only: bool = False,
) -> str:
    lines = [
        "---",
        f'title: "{structure.title}"',
        "assembled_from: tmp/*.ocr.json",
        "---",
        "",
        f"# {structure.title}",
        "",
    ]

    toc_chapters = [
        ch
        for ch in structure.chapters
        if ch.kind == "chapter" or ch.kind == BACK_MATTER_KIND
    ]
    if toc_chapters:
        lines.append("## 목차")
        lines.append("")
        for chapter in toc_chapters:
            lines.append(
                f"- [{chapter.heading}](#{chapter.slug}) *(p.{chapter.start_page})*"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    for chapter in structure.chapters:
        lines.extend(
            render_chapter(
                chapter,
                include_page_comments=include_page_comments,
                body_only=body_only,
            )
        )

    return "\n".join(lines).rstrip() + "\n"
