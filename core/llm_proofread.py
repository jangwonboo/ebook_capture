"""LLM proofreading of OCR text: Claude finds character-level misreads.

The dictionary pass (``ocr_typo_fix``) only knows the typos we have seen.
This pass sends each page's prose to Claude and asks for a *list of
corrections* (``from`` → ``to``), not a rewritten page: the output stays tiny
(cost is almost all input tokens), and every proposed fix is validated
locally before it is applied —

* ``from`` must occur in that segment, outside math / code / link spans;
* the edit must be small (``difflib`` similarity ≥ 0.5, length within ±4),
  so a stylistic rewrite can never slip through;
* only Hangul-bearing edits are accepted by default (the engine misreads
  jamo; numbers, English identifiers and symbols are left to the OCR).

Results are cached per page in ``tmp/{title}_NNNN.proof.json`` keyed by the
hash of the page text and the model, so re-assembling is free.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.ocr_json_loader import PageRecord, SectionBlock
from core.ocr_typo_fix import SKIP_TYPO_SECTION_TYPES, _rewrite_runs_text

DEFAULT_MODEL = "claude-opus-5-5"
PROOF_SUFFIX = ".proof.json"
# USD per million tokens (input, output) for cost reporting only.
_PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

SKIP_PROOF_SECTION_TYPES = SKIP_TYPO_SECTION_TYPES | {"table"}

SYSTEM_PROMPT = """당신은 OCR 결과 교정자입니다. 한국어 기술서를 화면 캡처 → OCR 한 텍스트를 받습니다.
OCR 엔진이 글자를 잘못 읽은 곳만 찾아 교정 목록을 만드세요.

고칠 것 (OCR 오인):
- 자모 하나가 바뀐 단어: 맴리듀스→맵리듀스, 텐드로그램→덴드로그램, 올긴이→옮긴이, 테이터→데이터
- 받침이 빠지거나 붙은 단어, 비슷한 모양의 글자(ㅂ/ㅁ, ㄷ/ㅌ, ㅇ/ㅎ, ㅐ/ㅔ)로 잘못 읽힌 단어
- 한글 사이에 잘못 끼어든 기호나 영문자(예: 데이O터)

고치지 말 것:
- 문체, 띄어쓰기, 조사, 어순, 맞춤법 취향. 원문 그대로 둡니다.
- 수식($…$), 코드(`…`), 영문 식별자, 숫자, 파일명, URL, 마크다운 기호
- 전문용어의 표기 방식(예: '데이터'/'데이타' 중 원문 표기, 외래어 표기법)
- 문맥상 자연스럽지 않아 보여도 OCR 오인이 아니라 원문일 수 있는 표현

출력은 JSON 하나만:
{"fixes":[{"seg":<번호>,"from":"<원문 그대로의 문자열>","to":"<고친 문자열>"}]}
- from 은 해당 세그먼트에 실제로 들어 있는 짧은 문자열(단어 하나, 조사 포함 가능)이어야 하고,
  그 세그먼트 안에서 한 번만 나타나야 합니다. 같은 단어가 여러 번 나오면 앞뒤 단어를 붙여 유일하게 만드세요.
- 확신이 없으면 넣지 마세요. 고칠 것이 없으면 {"fixes":[]} 를 내세요."""

_JSON_RE = re.compile(r"\{.*\}", re.S)
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎ]")  # syllables, or bare jamo (index letters ㄱ/ㄴ/ㄷ)
_PROTECTED_SPAN_RE = re.compile(r"\$[^$\n]+\$|`[^`\n]+`")


@dataclass
class ProofFix:
    page: int
    seg: int
    src: str
    dst: str
    applied: bool = True
    reason: str = ""


@dataclass
class ProofUsage:
    pages: int = 0
    cached: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = DEFAULT_MODEL

    def usd(self) -> float:
        pin, pout = _PRICES.get(self.model, (4.0, 20.0))
        return (self.input_tokens * pin + self.output_tokens * pout) / 1_000_000

    def summary(self) -> str:
        return (
            f"pages={self.pages} cached={self.cached} failed={self.failed} "
            f"in={self.input_tokens} out={self.output_tokens} usd={self.usd():.2f}"
        )


@dataclass
class ProofreadResult:
    pages: list[PageRecord]
    fixes: list[ProofFix]
    usage: ProofUsage
    errors: list[str] = field(default_factory=list)

    @property
    def applied(self) -> list[ProofFix]:
        return [f for f in self.fixes if f.applied]

    def report_text(self) -> str:
        lines = [
            "",
            f"# LLM 교정 ({self.usage.model}; {self.usage.summary()})",
            "# 쪽  원문 -> 수정",
            "",
        ]
        applied = self.applied
        if not applied:
            lines.append("(교정 없음)")
        for f in applied:
            lines.append(f"p{f.page:04d}  {f.src} -> {f.dst}")
        rejected = [f for f in self.fixes if not f.applied]
        if rejected:
            lines += ["", "# 제안됐지만 적용하지 않음 (검증 실패)"]
            for f in rejected:
                lines.append(f"p{f.page:04d}  {f.src} -> {f.dst}  [{f.reason}]")
        if self.errors:
            lines += ["", "# 오류"] + [f"  {e}" for e in self.errors]
        return "\n".join(lines) + "\n"


# ── request ───────────────────────────────────────────────────────────────

RequestFn = Callable[[str], tuple[str, int, int]]
"""(page_prompt) -> (raw model text, input_tokens, output_tokens)"""


def _load_env() -> None:
    try:
        from core.google_ocr import _load_env as load

        load()
    except Exception:
        pass


def make_anthropic_request(model: str = DEFAULT_MODEL) -> RequestFn:
    """Build the default request function (Anthropic SDK, corporate CA aware)."""
    import anthropic

    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is not set (environment or .env)")

    http_client = None
    try:
        from core.google_ocr import _ssl_context

        http_client = anthropic.DefaultHttpxClient(verify=_ssl_context())
    except Exception:
        http_client = None
    client = anthropic.Anthropic(http_client=http_client, max_retries=5, timeout=300.0)
    state = {"fallbacks": True}

    def request(prompt: str) -> tuple[str, int, int]:
        kwargs: dict = dict(
            model=model,
            max_tokens=4000,
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
        )
        if state["fallbacks"]:
            try:
                resp = client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            except anthropic.BadRequestError:
                # Fallback routing not available for this key/model: plain request.
                state["fallbacks"] = False
                resp = client.messages.create(**kwargs)
        else:
            resp = client.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            return '{"fixes":[]}', resp.usage.input_tokens, resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens

    return request


# ── page handling ─────────────────────────────────────────────────────────


def _eligible(sec: SectionBlock) -> bool:
    return sec.type not in SKIP_PROOF_SECTION_TYPES and bool(sec.text.strip())


def page_prompt(page: PageRecord) -> tuple[str, list[int]]:
    """Numbered segments for one page plus the section indexes they map to."""
    lines: list[str] = []
    idx: list[int] = []
    for i, sec in enumerate(page.sections):
        if not _eligible(sec):
            continue
        idx.append(i)
        lines.append(f"[{len(idx)}] {sec.text}")
    return "\n\n".join(lines), idx


_WS_RE = re.compile(r"\s+")


def _page_hash(prompt: str, model: str) -> str:
    """Cache key: the page text with whitespace removed, so spacing-only
    changes in the HTML→text conversion do not cost another request."""
    return hashlib.sha1(f"{model}\n{_WS_RE.sub('', prompt)}".encode("utf-8")).hexdigest()


def _legacy_page_hash(prompt: str, model: str) -> str:
    return hashlib.sha1(f"{model}\n{prompt}".encode("utf-8")).hexdigest()


def parse_fixes(raw: str) -> list[dict]:
    m = _JSON_RE.search(raw or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    fixes = data.get("fixes") if isinstance(data, dict) else None
    return [f for f in fixes or [] if isinstance(f, dict)]


def validate_fix(segment: str, src: str, dst: str, *, hangul_only: bool = True) -> str:
    """'' when the fix is acceptable, else the rejection reason."""
    if not src or not dst or src == dst:
        return "empty"
    if src not in segment:
        return "not-found"
    if segment.count(src) > 1:
        return "ambiguous"
    if len(src) > 40:
        return "too-long"
    if abs(len(src) - len(dst)) > 4:
        return "length"
    # Math / code inside the edit is fine only when it is carried over untouched
    # ("바이러스 $b$를" → "바이어스 $b$를"); any change to it is refused.
    if _PROTECTED_SPAN_RE.findall(src) != _PROTECTED_SPAN_RE.findall(dst):
        return "protected"
    stripped = _PROTECTED_SPAN_RE.sub("", src) + _PROTECTED_SPAN_RE.sub("", dst)
    if "$" in stripped or "`" in stripped:
        return "protected"  # an unmatched delimiter: the edit cuts into math/code
    if hangul_only and not (_HANGUL_RE.search(src) or _HANGUL_RE.search(dst)):
        return "no-hangul"
    # One or two syllables (뻗→밴, 허둠→하둡) can share no character and still be
    # a misread; longer edits must keep at least half of their characters.
    if len(src) > 2 and difflib.SequenceMatcher(None, src, dst).ratio() < 0.5:
        return "too-different"
    return ""


def apply_fixes_to_page(
    page: PageRecord, idx: list[int], fixes: list[dict], *, hangul_only: bool = True
) -> tuple[PageRecord, list[ProofFix]]:
    sections = list(page.sections)
    records: list[ProofFix] = []
    for f in fixes:
        try:
            seg = int(f.get("seg", 0))
        except (TypeError, ValueError):
            continue
        src, dst = str(f.get("from", "")), str(f.get("to", ""))
        if not 1 <= seg <= len(idx):
            records.append(ProofFix(page.page_num, seg, src, dst, False, "bad-seg"))
            continue
        si = idx[seg - 1]
        text = sections[si].text
        why = validate_fix(text, src, dst, hangul_only=hangul_only)
        if why:
            records.append(ProofFix(page.page_num, seg, src, dst, False, why))
            continue
        if _PROTECTED_SPAN_RE.search(src):
            # validate_fix proved the math/code spans are carried over unchanged.
            new_text = text.replace(src, dst, 1)
        else:
            new_text = _rewrite_runs_text(text, lambda s: s.replace(src, dst))
        if new_text == text:
            records.append(ProofFix(page.page_num, seg, src, dst, False, "inside-protected"))
            continue
        sections[si] = SectionBlock(type=sections[si].type, text=new_text)
        records.append(ProofFix(page.page_num, seg, src, dst, True))
    return PageRecord(page_num=page.page_num, sections=sections), records


def _cache_path(tmp_dir: Path, title: str, page_num: int) -> Path:
    return Path(tmp_dir) / f"{title}_{page_num:04d}{PROOF_SUFFIX}"


def proofread_pages(
    pages: list[PageRecord],
    *,
    tmp_dir: Path | str,
    title: str,
    model: str = DEFAULT_MODEL,
    request: RequestFn | None = None,
    workers: int = 4,
    progress: Callable[[str], None] | None = None,
) -> ProofreadResult:
    """Ask the model for corrections page by page (cached) and apply the valid ones."""
    tmp = Path(tmp_dir)
    usage = ProofUsage(model=model)
    errors: list[str] = []
    lock = threading.Lock()
    req = request or make_anthropic_request(model)

    def one(page: PageRecord) -> tuple[PageRecord, list[ProofFix]]:
        prompt, idx = page_prompt(page)
        if not idx:
            return page, []
        digest = _page_hash(prompt, model)
        cache = _cache_path(tmp, title, page.page_num)
        fixes: list[dict] | None = None
        if cache.is_file():
            try:
                data = json.loads(cache.read_text(encoding="utf-8"))
                if data.get("hash") in (digest, _legacy_page_hash(prompt, model)):
                    fixes = list(data.get("fixes") or [])
                    with lock:
                        usage.cached += 1
            except (OSError, json.JSONDecodeError):
                fixes = None
        if fixes is None:
            try:
                raw, tin, tout = req(prompt)
            except Exception as exc:  # noqa: BLE001 - report, keep the page as is
                with lock:
                    usage.failed += 1
                    errors.append(f"p{page.page_num:04d}: {type(exc).__name__}: {exc}")
                return page, []
            fixes = parse_fixes(raw)
            with lock:
                usage.input_tokens += tin
                usage.output_tokens += tout
            tmp.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps(
                    {"hash": digest, "model": model, "fixes": fixes,
                     "usage": {"input_tokens": tin, "output_tokens": tout}},
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
        with lock:
            usage.pages += 1
        new_page, recs = apply_fixes_to_page(page, idx, fixes)
        if progress and recs:
            progress(f"PROOFREAD p{page.page_num:04d} fixes={sum(r.applied for r in recs)}")
        return new_page, recs

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(one, pages))

    out_pages = [p for p, _ in results]
    all_fixes = [f for _, recs in results for f in recs]
    return ProofreadResult(out_pages, all_fixes, usage, errors)
