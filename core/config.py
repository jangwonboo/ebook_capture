from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILENAME = "default_config.json"
DEFAULT_BOOK_TITLE = "unknown"
DEFAULT_BASE_DIR = str(Path(__file__).resolve().parent.parent)
DEFAULT_ASSEMBLE_STYLE = "full"

# Canonical job outputs.
OUTPUT_IMAGES = "images"
OUTPUT_PDF = "pdf"
OUTPUT_TEXT = "text"
OUTPUT_MODES = frozenset({OUTPUT_IMAGES, OUTPUT_PDF, OUTPUT_TEXT})

CAPTURE_MANUAL = "manual"
CAPTURE_WINDOW_FULL = "window_full"
CAPTURE_WINDOW_LEFT_THIRD = "window_left_third"
CAPTURE_WINDOW_RIGHT_THIRD = "window_right_third"
CAPTURE_SCREEN_LEFT_THIRD = "screen_left_third"
CAPTURE_MODES = {
    CAPTURE_MANUAL,
    CAPTURE_WINDOW_FULL,
    CAPTURE_WINDOW_LEFT_THIRD,
    CAPTURE_WINDOW_RIGHT_THIRD,
    CAPTURE_SCREEN_LEFT_THIRD,
}


def is_fixed_screen_capture_mode(capture_mode: str) -> bool:
    return capture_mode == CAPTURE_SCREEN_LEFT_THIRD

WINDOW_CAPTURE_PRINTWINDOW = "printwindow"
WINDOW_CAPTURE_SCREEN = "screen"

KEY_DELIVERY_AUTO = "auto"
KEY_DELIVERY_SENDINPUT = "sendinput"
KEY_DELIVERY_POSTMESSAGE = "postmessage"
KEY_DELIVERY_POSTMESSAGE_TOP = "postmessage_top"
KEY_DELIVERY_PYAUTOGUI = "pyautogui"
KEY_DELIVERY_MODES = frozenset(
    {
        KEY_DELIVERY_AUTO,
        KEY_DELIVERY_SENDINPUT,
        KEY_DELIVERY_POSTMESSAGE,
        KEY_DELIVERY_POSTMESSAGE_TOP,
        KEY_DELIVERY_PYAUTOGUI,
    }
)

PHASE_CAPTURE = "capture"
PHASE_OCR = "ocr"
PHASE_PDF = "pdf"
PHASE_ALL = "all"
FORCE_PHASES = {"", PHASE_CAPTURE, PHASE_OCR, PHASE_PDF, PHASE_ALL}


def bundled_default_config_path() -> Path:
    jsonc = PACKAGE_ROOT / "default_config.jsonc"
    if jsonc.is_file():
        return jsonc
    return PACKAGE_ROOT / DEFAULT_CONFIG_FILENAME


def bundled_default_ocr_prompt_path() -> Path:
    return PACKAGE_ROOT / "assets" / "ocr_default_prompt.txt"


def normalize_output_mode(raw: str) -> str:
    key = str(raw or OUTPUT_PDF).strip().lower()
    if key in OUTPUT_MODES:
        return key
    raise ValueError(f"output_mode must be one of: {', '.join(sorted(OUTPUT_MODES))}")


def normalize_key_delivery(raw: str) -> str:
    key = str(raw or KEY_DELIVERY_AUTO).strip().lower()
    if key in KEY_DELIVERY_MODES:
        return key
    raise ValueError(
        "key_delivery must be one of: "
        + ", ".join(sorted(KEY_DELIVERY_MODES))
    )


def strip_json_comments(text: str) -> str:
    """Remove // and /* */ comments outside JSON strings (JSONC-style)."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                i += 2
                while i < n and text[i] not in "\r\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i = min(n, i + 2)
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_json_file(path: Path | str) -> Any:
    """Load JSON from disk; ``//`` and ``/* */`` comments are allowed."""
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(strip_json_comments(text))


def _output_mode_from_mapping(data: Mapping[str, Any]) -> str:
    raw = str(data.get("output_mode", OUTPUT_PDF)).strip()
    if not raw:
        return OUTPUT_PDF
    return normalize_output_mode(raw)


@dataclass
class Rect:
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


@dataclass
class CaptureConfig:
    """Shared CLI/GUI settings. Phases derive from ``output_mode``."""

    title: str = DEFAULT_BOOK_TITLE
    n_pages: int = 1
    start_page: int = 1
    base_dir: str = DEFAULT_BASE_DIR
    rect: Rect = field(default_factory=Rect)
    capture_mode: str = CAPTURE_MANUAL
    target_window_title: str = ""
    use_window_client_rect: bool = True
    prefer_foreground_window_match: bool = True
    window_capture_backend: str = WINDOW_CAPTURE_PRINTWINDOW
    hide_cursor_during_capture: bool = False
    debug_capture: bool = False
    debug_capture_max_pages: int = 5
    delay_sec: float = 1.0
    next_key: str = "pagedown"
    reader_focus_clicks: int = 2
    key_delivery: str = KEY_DELIVERY_AUTO
    output_mode: str = OUTPUT_PDF
    skip_capture: bool = False
    resume: bool = True
    force_phase: str = ""
    ocr_lang: str = "eng"
    ocr_text_prompt: str = ""
    ocr_prompt_file: str = ""
    assemble_style: str = DEFAULT_ASSEMBLE_STYLE
    input_pdf: str = ""
    pinned_target_hwnd: int = 0
    pinned_capture_rect: tuple[int, int, int, int] | None = None

    def normalize(self) -> CaptureConfig:
        self.output_mode = normalize_output_mode(self.output_mode)
        self.title = self.title.strip() or DEFAULT_BOOK_TITLE
        self.capture_mode = self.capture_mode.strip()
        self.assemble_style = self.assemble_style.strip().lower()
        self.key_delivery = normalize_key_delivery(self.key_delivery)
        return self

    @property
    def run_capture_phase(self) -> bool:
        if self.skip_capture or self.uses_pdf_input():
            return False
        return self.output_mode in OUTPUT_MODES

    @property
    def run_ocr_phase(self) -> bool:
        return self.output_mode == OUTPUT_TEXT

    @property
    def run_pdf_phase(self) -> bool:
        if self.skip_capture or self.uses_pdf_input():
            return False
        return self.output_mode == OUTPUT_PDF

    def output_dir(self) -> Path:
        return Path(self.base_dir) / self.title

    def tmp_dir(self) -> Path:
        return self.output_dir() / "tmp"

    def prefix_path(self) -> Path:
        return self.tmp_dir() / self.title

    def final_prefix_path(self) -> Path:
        return self.output_dir() / self.title

    def state_path(self) -> Path:
        return self.output_dir() / "capture_state.json"

    def page_path(self, page_num: int, suffix: str) -> Path:
        return Path(f"{self.prefix_path()}_{page_num:04d}{suffix}")

    def page_png_path(self, page_num: int) -> Path:
        return self.page_path(page_num, ".png")

    def page_txt_path(self, page_num: int) -> Path:
        return self.page_path(page_num, ".txt")

    def page_ocr_json_path(self, page_num: int) -> Path:
        return self.page_path(page_num, ".ocr.json")

    def page_image_pdf_path(self, page_num: int) -> Path:
        return self.page_path(page_num, ".page.pdf")

    def final_pdf_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}.pdf")

    def final_ocr_text_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}_ocr.txt")

    def final_markdown_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}.md")

    def structure_json_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}_structure.json")

    def resolved_ocr_prompt_file(self) -> str:
        if self.ocr_prompt_file.strip():
            return str(Path(self.ocr_prompt_file).expanduser())
        default = bundled_default_ocr_prompt_path()
        return str(default) if default.is_file() else ""

    def resolved_input_pdf(self) -> Path | None:
        if not self.input_pdf.strip():
            return None
        path = Path(self.input_pdf).expanduser()
        return path.resolve() if path.is_file() else path.resolve()

    def uses_pdf_input(self) -> bool:
        return bool(self.input_pdf.strip())

    def page_numbers(self, n_run: int | None = None) -> list[int]:
        count = self.n_pages if n_run is None else n_run
        return [self.start_page + i for i in range(count)]

    def pdf_page_index(self, page_num: int) -> int:
        return page_num - 1

    def should_force(self, phase: str) -> bool:
        return self.force_phase in {PHASE_ALL, phase}

    def validate(self) -> None:
        self.normalize()
        if self.capture_mode not in CAPTURE_MODES:
            raise ValueError(
                "capture_mode must be one of: manual, window_full, "
                "window_left_third, window_right_third, screen_left_third"
            )
        if self.n_pages < 1 or self.n_pages > 10000:
            raise ValueError("n_pages must be between 1 and 10000")
        if self.start_page < 1 or self.start_page > 999999:
            raise ValueError("start_page must be between 1 and 999999")
        if self.assemble_style not in {"full", "prose", "raw"}:
            raise ValueError("assemble_style must be one of: full, prose, raw")
        pdf_path = self.resolved_input_pdf()
        if self.uses_pdf_input():
            if pdf_path is None or not pdf_path.is_file():
                raise ValueError(f"input_pdf not found: {self.input_pdf}")
            from core.pdf_input import pdf_page_count

            total = pdf_page_count(pdf_path)
            if self.start_page > total:
                raise ValueError(
                    f"start_page {self.start_page} exceeds PDF page count {total}"
                )
            last_page = self.start_page + self.n_pages - 1
            if last_page > total:
                raise ValueError(
                    f"requested pages {self.start_page}..{last_page} exceed "
                    f"PDF page count {total}"
                )
        elif self.run_capture_phase and self.capture_mode == CAPTURE_MANUAL:
            if self.rect.width < 1 or self.rect.height < 1:
                raise ValueError(
                    "rect width and height must be positive for manual capture"
                )
        elif self.run_capture_phase:
            if not self.target_window_title.strip():
                raise ValueError(
                    "target_window_title is required for window capture modes"
                )
            if self.window_capture_backend not in (
                WINDOW_CAPTURE_PRINTWINDOW,
                WINDOW_CAPTURE_SCREEN,
            ):
                raise ValueError(
                    "window_capture_backend must be "
                    f"{WINDOW_CAPTURE_PRINTWINDOW!r} or {WINDOW_CAPTURE_SCREEN!r}"
                )
        p = Path(self.base_dir)
        if not p.drive and not p.is_absolute():
            raise ValueError("base_dir must be an absolute path")
        if self.force_phase not in FORCE_PHASES:
            raise ValueError(
                "force_phase must be one of: '', capture, ocr, pdf, all"
            )
        if self.reader_focus_clicks < 0 or self.reader_focus_clicks > 5:
            raise ValueError("reader_focus_clicks must be between 0 and 5")
        normalize_key_delivery(self.key_delivery)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CaptureConfig:
        rect_raw = data.get("rect") or {}
        cfg = cls(
            title=str(data.get("title", DEFAULT_BOOK_TITLE)).strip()
            or DEFAULT_BOOK_TITLE,
            n_pages=int(data.get("n_pages", 1)),
            start_page=int(data.get("start_page", 1)),
            base_dir=str(data.get("base_dir", DEFAULT_BASE_DIR)),
            rect=Rect(
                left=int(rect_raw.get("left", 0)),
                top=int(rect_raw.get("top", 0)),
                width=int(rect_raw.get("width", 0)),
                height=int(rect_raw.get("height", 0)),
            ),
            capture_mode=str(data.get("capture_mode", CAPTURE_MANUAL)),
            target_window_title=str(data.get("target_window_title", "")),
            use_window_client_rect=bool(data.get("use_window_client_rect", True)),
            prefer_foreground_window_match=bool(
                data.get("prefer_foreground_window_match", True)
            ),
            window_capture_backend=str(
                data.get("window_capture_backend", WINDOW_CAPTURE_PRINTWINDOW)
            ),
            hide_cursor_during_capture=bool(
                data.get("hide_cursor_during_capture", False)
            ),
            debug_capture=bool(data.get("debug_capture", False)),
            debug_capture_max_pages=int(data.get("debug_capture_max_pages", 5)),
            delay_sec=float(data.get("delay_sec", 1.0)),
            next_key=str(data.get("next_key", "pagedown")),
            reader_focus_clicks=int(data.get("reader_focus_clicks", 2)),
            key_delivery=str(data.get("key_delivery", KEY_DELIVERY_AUTO)),
            output_mode=_output_mode_from_mapping(data),
            skip_capture=bool(data.get("skip_capture", False)),
            resume=bool(data.get("resume", True)),
            force_phase=str(data.get("force_phase", "")),
            ocr_lang=str(data.get("ocr_lang", "eng")),
            ocr_text_prompt=str(data.get("ocr_text_prompt", "")),
            ocr_prompt_file=str(data.get("ocr_prompt_file", "")),
            assemble_style=str(data.get("assemble_style", DEFAULT_ASSEMBLE_STYLE)),
            input_pdf=str(data.get("input_pdf", "")),
        )
        return cfg.normalize()

    @classmethod
    def from_json_file(cls, path: Path | str) -> CaptureConfig:
        return cls.from_mapping(load_json_file(path))

    def to_json_file(self, path: Path | str) -> None:
        data = asdict(self)
        data.pop("pinned_target_hwnd", None)
        data.pop("pinned_capture_rect", None)
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
