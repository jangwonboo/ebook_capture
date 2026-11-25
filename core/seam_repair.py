"""Repair text that page breaks and OCR block detection cut apart.

Two artefacts survive the per-page OCR:

* **A paragraph cut by a page break.** The cut can fall inside a word
  ("순" | "탄하지 않았다") or between words ("삶의" | "의미를"). Whether the
  seam needs a space cannot be told from the two fragments alone, so the book
  itself is used as the dictionary: :func:`word_starts` counts how every word
  in the book begins, and :func:`seam_glue` checks whether the joined form
  occurs elsewhere and whether the second fragment ever starts a word.
* **A heading printed on two lines.** OCR returns two heading blocks
  ("나를 잃으면" / "모든 것을 잃는다"), or leaves the first line behind as a
  short body or caption block ("마흔," / "삶에서") right before the heading.
  :func:`merge_split_headings` joins them.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable, Mapping

from core.ocr_json_loader import PageRecord, SectionBlock

HEADING_TYPES = frozenset({"subtitle", "section_title"})
_LEAD_IN_TYPES = frozenset({"body", "caption", "other"})
_MAX_PREFIX = 10
_MAX_HEADING_CHARS = 60
_MAX_LEAD_IN_CHARS = 15

_NON_LETTERS_RE = re.compile(r"[^0-9A-Za-z가-힣]")
_HANGUL_END_RE = re.compile(r"[가-힣]$")
_HANGUL_START_RE = re.compile(r"^[가-힣]")
_CLOSING_END_RE = re.compile(r"[’'」』》)\]]$")
# A bare particle or ending cannot start a word: "우리" | "는 외부의".
_BOUND_TOKEN_RE = re.compile(r"^[은는을를에의와과도로만씩며고면]$")
_SENTENCE_FINAL_DA_RE = re.compile(r"^다[.!?]")
# "정착" | "하지 못했다": a verb ending attaches to the noun before it ...
_VERB_ENDING_RE = re.compile(r"^(하지|하고|하며|하는|하게|하여|해서|한다|했다|되는|되고|되지|된다|됐다)$")
# ... unless that word already carries a particle: "계산밖에" | "하지 못하는".
_PARTICLE_END_RE = re.compile(r"[의와과을를에도만은는이가로서]$")

_ENDS_SENTENCE_RE = re.compile(r"[.?!…。:;”\"][\"'”’」』》)\]]*$")
_NUMBERED_START_RE = re.compile(r"^(\(?\d+[.)]|제\s*\d+|[①-⑳]|[IVX]+[.)]|[A-Z][.)]|[-•·■□▶◆])")
_LEAD_IN_BODY_RE = re.compile(r"^[가-힣\s,]+$")
# Single syllables are limited to particles that rarely end a noun; "내면", "태도", "결과" must not match.
_LEAD_IN_END_RE = re.compile(r"(,|에서|에게|으로|부터|까지|처럼|보다|으면|하면|라면|이면|하고|이고|하며|이며|해서|지만|에는|에도|[을를은는에])$")


def _letters(token: str) -> str:
    return _NON_LETTERS_RE.sub("", token)


def word_starts(texts: Iterable[str]) -> Counter[str]:
    """Count every leading substring (up to 10 characters) of every word."""
    starts: Counter[str] = Counter()
    for text in texts:
        for token in text.split():
            word = _letters(token)
            for length in range(1, min(len(word), _MAX_PREFIX) + 1):
                starts[word[:length]] += 1
    return starts


def book_word_starts(pages: Iterable[PageRecord]) -> Counter[str]:
    return word_starts(sec.text for page in pages for sec in page.content_sections())


def seam_glue(before: str, after: str, starts: Mapping[str, int]) -> str:
    """``""`` when a page break cut a word in two, ``" "`` when it fell between words."""
    from core.text_reflow import _ends_with_space_joiner

    left = before.rstrip()
    right = after.lstrip()
    if not left or not right:
        return ""
    last_token = left.split()[-1]
    first_token = right.split()[0]
    head = _letters(last_token)
    tail = _letters(first_token)

    hangul_end = bool(_HANGUL_END_RE.search(last_token))
    if not hangul_end and not _CLOSING_END_RE.search(last_token):
        return " "  # after a comma, digit or Latin letter
    if not _HANGUL_START_RE.search(first_token) or not tail:
        return " "
    if _BOUND_TOKEN_RE.match(tail) or _SENTENCE_FINAL_DA_RE.match(first_token):
        return ""
    if not hangul_end:
        return " "
    if _VERB_ENDING_RE.match(tail) and not _PARTICLE_END_RE.search(head):
        return ""
    if head and starts.get(head + tail[0], 0) > 0:
        return ""  # the joined form occurs elsewhere in the book as a word
    if _ends_with_space_joiner(left):
        return " "  # the first half is a finished word ("인터넷의" | "정보들이")
    if len(tail) >= 2 and starts.get(tail[:2], 0) < 2:
        return ""  # the second half never starts a word anywhere else
    return " "


def join_at_seam(before: str, after: str, starts: Mapping[str, int]) -> str:
    left = before.rstrip()
    right = after.lstrip()
    if left.endswith("-") and right[:1].isalpha():
        return left[:-1] + right  # hyphenated Latin word
    return f"{left}{seam_glue(left, right, starts)}{right}"


def _flat(text: str) -> str:
    return " ".join(text.split())


def is_lead_in(text: str) -> bool:
    """A short dangling phrase that is really the first line of the next heading:
    Hangul only, at most 15 characters, ending in a comma or in a particle that
    cannot close a sentence ("마흔,", "삶에서"). A label such as "고요" or
    "비트겐슈타인의 내면" is left alone."""
    phrase = _flat(text).strip("*").strip()
    if not phrase or len(phrase) > _MAX_LEAD_IN_CHARS or not _LEAD_IN_BODY_RE.match(phrase):
        return False
    return bool(_LEAD_IN_END_RE.search(phrase))


def is_split_heading(first: SectionBlock, second: SectionBlock) -> bool:
    """Two same-type headings in a row read as one phrase, unless the first
    already ends a sentence or the second starts like a separate numbered item."""
    if first.type != second.type or first.type not in HEADING_TYPES:
        return False
    a, b = _flat(first.text), _flat(second.text)
    if not a or not b or len(a) + len(b) > _MAX_HEADING_CHARS:
        return False
    if _ENDS_SENTENCE_RE.search(a):
        return False
    return not _NUMBERED_START_RE.match(b)


def merge_split_headings(sections: list[SectionBlock]) -> list[SectionBlock]:
    out: list[SectionBlock] = []
    for sec in sections:
        prev = out[-1] if out else None
        if prev is not None and is_split_heading(prev, sec):
            out[-1] = SectionBlock(type=sec.type, text=f"{_flat(prev.text)} {_flat(sec.text)}")
        elif (
            prev is not None
            and sec.type in HEADING_TYPES
            and prev.type in _LEAD_IN_TYPES
            and is_lead_in(prev.text)
        ):
            lead = _flat(prev.text).strip("*").strip()
            out[-1] = SectionBlock(type=sec.type, text=f"{lead} {_flat(sec.text)}")
        else:
            out.append(sec)
    return out


def repair_split_headings(pages: list[PageRecord]) -> list[PageRecord]:
    return [
        PageRecord(page_num=page.page_num, sections=merge_split_headings(list(page.sections)))
        for page in pages
    ]
