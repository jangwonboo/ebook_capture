"""Fix OCR character errors in Korean text before Markdown assembly.

The OCR engine (Datalab / Gemini) misreads single jamo now and then:
``맵리듀스`` → ``맴리듀스`` (ㅂ→ㅁ), ``덴드로그램`` → ``텐드로그램`` (ㄷ→ㅌ),
``옮긴이`` → ``올긴이`` (ㄻ→ㄹ). Two sources of corrections are applied over
the whole book in one pass:

1. **Explicit dictionary** — built-in entries plus optional ``ocr_typos.txt``
   files (``wrong -> right`` per line, ``!word`` protects a word, ``#`` comments).
   Keys match at the start of a Hangul run so particles stay attached
   (``맴리듀스를`` → ``맵리듀스를``).
2. **Book-internal frequency** — a Hangul-run prefix that is rare in this book
   and one *visually confusable* jamo away from a prefix that is frequent is
   taken to be a misread of it.  Only a fixed confusion set (ㅂ/ㅁ, ㄷ/ㅌ, ㅇ/ㅎ,
   tense/plain pairs, complex finals, ㅐ/ㅔ ...) is tried, so legitimate
   near-words such as 수행/주행 are never touched.

Inline math, code spans, image/link targets and URLs are protected; code,
equation and figure sections are skipped.  Every replacement is recorded so
the caller can write a review report next to the Markdown.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from core.ocr_json_loader import PageRecord, SectionBlock

# --------------------------------------------------------------------------
# Jamo arithmetic
# --------------------------------------------------------------------------

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ("", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ",
         "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")
_HANGUL_BASE = 0xAC00


def decompose(syllable: str) -> tuple[str, str, str]:
    code = ord(syllable) - _HANGUL_BASE
    if not 0 <= code < 11172:
        raise ValueError(f"not a Hangul syllable: {syllable!r}")
    return _CHO[code // 588], _JUNG[(code % 588) // 28], _JONG[code % 28]


def compose(cho: str, jung: str, jong: str) -> str:
    return chr(_HANGUL_BASE + (_CHO.index(cho) * 21 + _JUNG.index(jung)) * 28 + _JONG.index(jong))


def _pairs(groups: Iterable[str]) -> dict[str, set[str]]:
    """``"ㅂㅁ"`` → {ㅂ: {ㅁ}, ㅁ: {ㅂ}} for every group of mutually confusable jamo."""
    out: dict[str, set[str]] = {}
    for group in groups:
        members = list(group) if isinstance(group, str) else list(group)
        for a in members:
            out.setdefault(a, set()).update(m for m in members if m != a)
    return out


# Visually similar shapes as seen by a VLM OCR on screen-rendered Korean.
_CHO_CONFUSION = _pairs(["ㅂㅁ", "ㅍㅁ", "ㄷㅌ", "ㅇㅎ", "ㄱㅋ", "ㅈㅊ",
                         "ㅅㅆ", "ㄱㄲ", "ㄷㄸ", "ㅂㅃ", "ㅈㅉ"])
_JUNG_CONFUSION = _pairs(["ㅐㅔ", "ㅒㅖ", "ㅙㅚㅞ"])
_JONG_CONFUSION = _pairs(["ㅂㅁ", "ㅍㅁ", "ㄷㅌ", "ㅇㅎ", "ㄱㅋ", "ㅈㅊ", "ㅅㅆ", "ㄱㄲ",
                          # complex finals whose second stroke is dropped / added
                          ["ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ"],
                          ["ㄴ", "ㄵ", "ㄶ"], ["ㄱ", "ㄳ"], ["ㅂ", "ㅄ"]])


def confusable_syllables(syllable: str) -> list[str]:
    """Syllables one confusable jamo away from ``syllable``."""
    cho, jung, jong = decompose(syllable)
    out: list[str] = []
    for alt in _CHO_CONFUSION.get(cho, ()):
        out.append(compose(alt, jung, jong))
    for alt in _JUNG_CONFUSION.get(jung, ()):
        out.append(compose(cho, alt, jong))
    for alt in _JONG_CONFUSION.get(jong, ()):
        out.append(compose(cho, jung, alt))
    return out


# --------------------------------------------------------------------------
# Dictionary
# --------------------------------------------------------------------------

# wrong -> right; keys match at the start of a Hangul run.
BUILTIN_TYPOS: dict[str, str] = {
    "맴리듀스": "맵리듀스",
    "텐드로그램": "덴드로그램",
    "올긴이": "옮긴이",
    "올겼": "옮겼",
    "테이터": "데이터",
    "알고리듬": "알고리즘",
}

TYPO_DICT_FILENAME = "ocr_typos.txt"


@dataclass
class TypoDictionary:
    fixes: dict[str, str] = field(default_factory=dict)
    protected: set[str] = field(default_factory=set)

    def update_from_text(self, text: str) -> None:
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("!"):
                self.protected.add(line[1:].strip())
                continue
            if "->" in line:
                wrong, right = (part.strip() for part in line.split("->", 1))
            else:
                parts = line.split()
                if len(parts) != 2:
                    continue
                wrong, right = parts
            if wrong and right and wrong != right:
                self.fixes[wrong] = right

    def update_from_file(self, path: Path | str) -> bool:
        p = Path(path)
        if not p.is_file():
            return False
        self.update_from_text(p.read_text(encoding="utf-8"))
        return True


def load_typo_dictionary(paths: Iterable[Path | str] = ()) -> TypoDictionary:
    d = TypoDictionary(fixes=dict(BUILTIN_TYPOS))
    for p in paths:
        d.update_from_file(p)
    return d


# --------------------------------------------------------------------------
# Text scanning
# --------------------------------------------------------------------------

_HANGUL_RUN_RE = re.compile(r"[가-힣]+")
# Spans whose contents must never be rewritten.
_PROTECT_RE = re.compile(
    r"\$\$.*?\$\$"            # display math
    r"|\$[^$\n]+\$"           # inline math
    r"|```.*?```"             # fenced code inside a text block
    r"|`[^`\n]+`"             # code span
    r"|!\[[^\]]*\]\([^)]*\)"  # image
    r"|\]\([^)]*\)"           # link target
    r"|https?://\S+",         # bare URL
    re.S,
)

SKIP_TYPO_SECTION_TYPES = frozenset({"code", "equation", "figure", "header", "page_number"})

# Frequency heuristic thresholds.
MIN_PREFIX_LEN = 3      # never judge on fewer than 3 syllables
RARE_MAX = 5            # a prefix seen more often than this is established vocabulary
FREQ_MIN = 5            # the correction must itself be this common ...
FREQ_RATIO = 3          # ... and at least this many times more common than the misread


def _editable_segments(text: str) -> list[tuple[int, int]]:
    """(start, end) spans of ``text`` outside protected spans."""
    segments: list[tuple[int, int]] = []
    pos = 0
    for m in _PROTECT_RE.finditer(text):
        if m.start() > pos:
            segments.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        segments.append((pos, len(text)))
    return segments


def _eligible(sec: SectionBlock) -> bool:
    return sec.type not in SKIP_TYPO_SECTION_TYPES


def _iter_runs(text: str) -> Iterable[str]:
    for start, end in _editable_segments(text):
        for m in _HANGUL_RUN_RE.finditer(text, start, end):
            yield m.group(0)


def _prefix_counts(pages: Iterable[PageRecord]) -> tuple[Counter[str], Counter[str]]:
    """Counts of every Hangul run and of every prefix (length ≥ 2) of it."""
    runs: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    for page in pages:
        for sec in page.sections:
            if not _eligible(sec):
                continue
            for run in _iter_runs(sec.text):
                runs[run] += 1
                for length in range(2, len(run) + 1):
                    prefixes[run[:length]] += 1
    return runs, prefixes


def _variants_of_prefix(prefix: str, positions: Iterable[int]) -> Iterable[str]:
    for i in positions:
        for alt in confusable_syllables(prefix[i]):
            yield prefix[:i] + alt + prefix[i + 1:]


@dataclass
class FixRecord:
    wrong: str
    right: str
    source: str          # "dict" | "freq"
    occurrences: int = 0
    evidence: str = ""


def infer_frequency_fixes(
    runs: Counter[str],
    prefixes: Counter[str],
    *,
    protected: Iterable[str] = (),
) -> dict[str, FixRecord]:
    """Map rare run → corrected run, judged prefix by prefix."""
    protected_set = set(protected)
    fixes: dict[str, FixRecord] = {}
    for run in runs:
        if len(run) < MIN_PREFIX_LEN or run in protected_set:
            continue
        for length in range(MIN_PREFIX_LEN, len(run) + 1):
            prefix = run[:length]
            seen = prefixes[prefix]
            if seen > RARE_MAX:
                continue  # established in this book at this length; look further right
            positions = range(length) if length == MIN_PREFIX_LEN else (length - 1,)
            best: tuple[int, str] | None = None
            for variant in _variants_of_prefix(prefix, positions):
                count = prefixes.get(variant, 0)
                if count < FREQ_MIN or count < FREQ_RATIO * seen:
                    continue
                if best is None or count > best[0]:
                    best = (count, variant)
            if best is None:
                continue
            count, variant = best
            right = variant + run[length:]
            if right in protected_set or right == run:
                break
            fixes[run] = FixRecord(
                wrong=run,
                right=right,
                source="freq",
                evidence=f"{variant} {count}회 vs {prefix} {seen}회",
            )
            break
    return fixes


def _dict_pattern(d: TypoDictionary) -> re.Pattern[str] | None:
    keys = sorted((k for k in d.fixes if _HANGUL_RUN_RE.fullmatch(k)), key=len, reverse=True)
    if not keys:
        return None
    return re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, keys)) + r")")


@dataclass
class TypoFixResult:
    pages: list[PageRecord]
    records: list[FixRecord]

    @property
    def total(self) -> int:
        return sum(r.occurrences for r in self.records)

    def report_text(self) -> str:
        lines = ["# OCR 오타 보정 내역", "# 원문 -> 수정  횟수  근거", ""]
        if not self.records:
            lines.append("(보정 없음)")
        for r in sorted(self.records, key=lambda r: (-r.occurrences, r.wrong)):
            why = "사전" if r.source == "dict" else f"빈도: {r.evidence}"
            lines.append(f"{r.wrong} -> {r.right}  x{r.occurrences}  ({why})")
        return "\n".join(lines) + "\n"


def fix_ocr_typos(
    pages: list[PageRecord],
    *,
    dictionary: TypoDictionary | None = None,
    use_frequency: bool = False,
) -> TypoFixResult:
    """Return corrected copies of ``pages`` plus the list of applied fixes.

    ``use_frequency`` is off by default: on real books the in-book frequency
    heuristic mostly flagged legitimate rare words that happen to sit one jamo
    from a frequent one (``빅테이블``→``빅데이블``, ``앉는다``→``않는다``), so it is
    an opt-in whose report must be reviewed by hand."""
    d = dictionary or load_typo_dictionary()
    pattern = _dict_pattern(d)
    dict_records: dict[str, FixRecord] = {}

    def apply_dict(text: str) -> str:
        if pattern is None:
            return text

        def repl(m: re.Match[str]) -> str:
            wrong = m.group(0)
            rec = dict_records.setdefault(wrong, FixRecord(wrong, d.fixes[wrong], "dict"))
            rec.occurrences += 1
            return rec.right

        return _rewrite_runs_text(text, lambda seg: pattern.sub(repl, seg))

    after_dict = [
        PageRecord(
            page_num=p.page_num,
            sections=[
                SectionBlock(type=s.type, text=apply_dict(s.text)) if _eligible(s) else s
                for s in p.sections
            ],
        )
        for p in pages
    ]

    freq_records: dict[str, FixRecord] = {}
    if use_frequency:
        runs, prefixes = _prefix_counts(after_dict)
        freq_records = infer_frequency_fixes(runs, prefixes, protected=d.protected)

    if not freq_records:
        return TypoFixResult(after_dict, list(dict_records.values()))

    def apply_freq(text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            rec = freq_records.get(m.group(0))
            if rec is None:
                return m.group(0)
            rec.occurrences += 1
            return rec.right

        return _rewrite_runs_text(text, lambda seg: _HANGUL_RUN_RE.sub(repl, seg))

    final = [
        PageRecord(
            page_num=p.page_num,
            sections=[
                SectionBlock(type=s.type, text=apply_freq(s.text)) if _eligible(s) else s
                for s in p.sections
            ],
        )
        for p in after_dict
    ]
    records = list(dict_records.values()) + [r for r in freq_records.values() if r.occurrences]
    return TypoFixResult(final, records)


def _rewrite_runs_text(text: str, transform) -> str:
    """Apply ``transform`` to the editable segments of ``text`` only."""
    out: list[str] = []
    pos = 0
    for start, end in _editable_segments(text):
        out.append(text[pos:start])
        out.append(transform(text[start:end]))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def default_dictionary_paths(book_dir: Path | str | None) -> list[Path]:
    """``ocr_typos.txt`` next to the book output, then in the project root."""
    paths: list[Path] = []
    if book_dir is not None:
        paths.append(Path(book_dir) / TYPO_DICT_FILENAME)
    paths.append(Path(__file__).resolve().parent.parent / TYPO_DICT_FILENAME)
    return paths
