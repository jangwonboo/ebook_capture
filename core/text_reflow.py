"""Reflow OCR body text: collapse layout line breaks, keep paragraph breaks."""

from __future__ import annotations

import re

from core.ocr_json_loader import SectionBlock
from core.paragraph_merge import looks_like_new_paragraph, paragraph_ends

_HANGUL = re.compile(r"[가-힣]")
_BLANK_LINES = re.compile(r"\n\s*\n+")

_SPACE_JOIN_SUFFIXES = (
    "에서",
    "으로",
    "까지",
    "부터",
    "이나",
    "거나",
    "라는",
    "라고",
    "이며",
    "이고",
    "인데",
    "이지만",
    "하기",
    "하는",
    "하다",
    "이다",
    "습니다",
    "였다",
    "것이",
    "것을",
    "것은",
    "밖에",
    "위해",
    "통해",
    "에게",
    "처럼",
    "보다",
    "만큼",
)
_SPACE_JOIN_CHARS = frozenset("의와과을를에도만은는이가로")


def _ends_with_space_joiner(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return True
    if stripped[-1] in ',.;:!?…)]}"\'""''':
        return True
    for suffix in _SPACE_JOIN_SUFFIXES:
        if stripped.endswith(suffix):
            return True
    if stripped[-1] in _SPACE_JOIN_CHARS:
        return True
    return False


def join_wrapped_lines(prev: str, nxt: str) -> str:
    left = prev.rstrip()
    right = nxt.lstrip()
    if not left:
        return right
    if not right:
        return left
    if left.endswith("-") and right[0].isalpha():
        return left[:-1] + right

    need_space = True
    if _HANGUL.match(left[-1]) and _HANGUL.match(right[0]):
        need_space = _ends_with_space_joiner(left)
    elif left[-1].isascii() and left[-1].isalpha() and right[0].isascii() and right[0].islower():
        need_space = False

    sep = " " if need_space else ""
    return f"{left}{sep}{right}"


def reflow_body_text(text: str) -> str:
    """Collapse single newlines inside paragraphs; preserve blank-line breaks."""
    if not text or "\n" not in text:
        return text

    chunks = _BLANK_LINES.split(text.strip())
    reflowed: list[str] = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        merged = lines[0]
        for line in lines[1:]:
            if paragraph_ends(merged) and looks_like_new_paragraph(line):
                reflowed.append(merged)
                merged = line
            else:
                merged = join_wrapped_lines(merged, line)
        reflowed.append(merged)
    return "\n\n".join(reflowed)


def reflow_page_sections(sections: list[SectionBlock]) -> list[SectionBlock]:
    out: list[SectionBlock] = []
    for sec in sections:
        if sec.type == "body":
            out.append(SectionBlock(type=sec.type, text=reflow_body_text(sec.text)))
        else:
            out.append(sec)
    return out
