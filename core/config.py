from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_FILENAME = "default_config.json"
DEFAULT_BOOK_TITLE = "unknown"
DEFAULT_BASE_DIR = str(Path(__file__).resolve().parent.parent)


def bundled_default_config_path() -> Path:
    """Shipped default JSON (same schema as CaptureConfig)."""
    return PACKAGE_ROOT / DEFAULT_CONFIG_FILENAME


@dataclass
class Rect:
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height


# Capture region relative to target window (when not manual).
CAPTURE_MANUAL = "manual"
CAPTURE_WINDOW_FULL = "window_full"
CAPTURE_WINDOW_LEFT_THIRD = "window_left_third"
CAPTURE_WINDOW_RIGHT_THIRD = "window_right_third"
CAPTURE_MODES = {
    CAPTURE_MANUAL,
    CAPTURE_WINDOW_FULL,
    CAPTURE_WINDOW_LEFT_THIRD,
    CAPTURE_WINDOW_RIGHT_THIRD,
}

# Window capture implementation (Windows). ``printwindow`` captures HWND client pixels.
WINDOW_CAPTURE_PRINTWINDOW = "printwindow"
WINDOW_CAPTURE_SCREEN = "screen"

PHASE_CAPTURE = "capture"
PHASE_OCR = "ocr"
PHASE_PDF = "pdf"
PHASE_VOICE = "voice"
PHASE_ALL = "all"
OUTPUT_CAPTURE_ONLY = "capture_only"
OUTPUT_PDF = "pdf"
OUTPUT_TEXT = "text"
OUTPUT_SEARCHABLE_PDF = "searchable_pdf"
OUTPUT_IMAGES = "images"
OUTPUT_PDF_IMAGE = "pdf_image"
OUTPUT_PDF_SEARCHABLE = "pdf_searchable"
OUTPUT_AUDIO = "audio"
OUTPUT_MODES = {
    OUTPUT_IMAGES,
    OUTPUT_TEXT,
    OUTPUT_PDF_IMAGE,
    OUTPUT_PDF_SEARCHABLE,
    OUTPUT_AUDIO,
}
FORCE_PHASES = {
    "",
    PHASE_CAPTURE,
    PHASE_OCR,
    PHASE_PDF,
    PHASE_VOICE,
    PHASE_ALL,
}


@dataclass
class CaptureConfig:
    """Options shared by CLI and GUI (serialized for subprocess CLI runs)."""

    title: str = DEFAULT_BOOK_TITLE
    n_pages: int = 1
    start_page: int = 1
    base_dir: str = DEFAULT_BASE_DIR
    rect: Rect = field(default_factory=Rect)
    # manual: use rect (screen coords). Otherwise target_window_title + capture_mode.
    capture_mode: str = CAPTURE_MANUAL
    target_window_title: str = ""
    # Window modes (Windows): client rect = inside frame (better for RDP); frame = outer GetWindowRect.
    use_window_client_rect: bool = True
    # If several windows match target_window_title substring, prefer the foreground window.
    prefer_foreground_window_match: bool = True
    # Windows window_* modes: printwindow = HWND bitmap (recommended for RDP); screen = mss/region.
    window_capture_backend: str = WINDOW_CAPTURE_PRINTWINDOW
    # Move mouse outside the capture rectangle only while taking each screenshot, then restore.
    hide_cursor_during_capture: bool = False
    # Log window/crop coordinates; cap all phases to min(n_pages, debug_capture_max_pages).
    debug_capture: bool = False
    debug_capture_max_pages: int = 5
    delay_sec: float = 1.0
    next_key: str = "pagedown"
    capture_images: bool = True
    build_pdf: bool = True
    ocr: bool = False
    output_mode: str = OUTPUT_PDF_IMAGE
    run_capture_phase: bool = True
    run_ocr_phase: bool = False
    run_pdf_phase: bool = True
    resume: bool = True
    force_phase: str = ""
    ocr_lang: str = "eng"
    voice: bool = False
    voice_lang_code: str = "en-US"
    voice_model: str = "en-US-Wavenet-A"
    voice_gender: str = "FEMALE"

    def output_dir(self) -> Path:
        return Path(self.base_dir) / self.title

    def tmp_dir(self) -> Path:
        return self.output_dir() / "tmp"

    def prefix_path(self) -> Path:
        """Path prefix for page files (without extension)."""
        return self.tmp_dir() / self.title

    def final_prefix_path(self) -> Path:
        """Final output prefix outside tmp (without extension)."""
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

    def page_pdf_path(self, page_num: int) -> Path:
        return self.page_path(page_num, ".searchable.pdf")

    def final_pdf_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}.pdf")

    def final_ocr_text_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}_ocr.txt")

    def final_voice_path(self) -> Path:
        return Path(f"{self.final_prefix_path()}_voice.mp3")

    def page_numbers(self, n_run: int | None = None) -> list[int]:
        count = self.n_pages if n_run is None else n_run
        return [self.start_page + i for i in range(count)]

    def should_force(self, phase: str) -> bool:
        return self.force_phase in {PHASE_ALL, phase}

    def apply_output_mode(self) -> None:
        """Apply one of the user-facing capture output modes to phase flags."""
        # Backward-compat aliases for old configs/CLI values.
        if self.output_mode == OUTPUT_CAPTURE_ONLY:
            self.output_mode = OUTPUT_IMAGES
        elif self.output_mode == OUTPUT_PDF:
            self.output_mode = OUTPUT_PDF_IMAGE
        elif self.output_mode == OUTPUT_SEARCHABLE_PDF:
            self.output_mode = OUTPUT_PDF_SEARCHABLE

        if self.output_mode == OUTPUT_IMAGES:
            self.capture_images = True
            self.ocr = False
            self.build_pdf = False
            self.run_capture_phase = True
            self.run_ocr_phase = False
            self.run_pdf_phase = False
            self.voice = False
        elif self.output_mode == OUTPUT_TEXT:
            self.capture_images = True
            self.ocr = True
            self.build_pdf = False
            self.run_capture_phase = True
            self.run_ocr_phase = True
            self.run_pdf_phase = False
            self.voice = False
        elif self.output_mode == OUTPUT_PDF_SEARCHABLE:
            self.capture_images = True
            self.ocr = True
            self.build_pdf = True
            self.run_capture_phase = True
            self.run_ocr_phase = True
            self.run_pdf_phase = True
            self.voice = False
        elif self.output_mode == OUTPUT_AUDIO:
            self.capture_images = True
            self.ocr = True
            self.build_pdf = False
            self.run_capture_phase = True
            self.run_ocr_phase = True
            self.run_pdf_phase = False
            self.voice = True
        else:
            self.output_mode = OUTPUT_PDF_IMAGE
            self.capture_images = True
            self.ocr = False
            self.build_pdf = True
            self.run_capture_phase = True
            self.run_ocr_phase = False
            self.run_pdf_phase = True
            self.voice = False

    def validate(self) -> None:
        self.title = self.title.strip() or DEFAULT_BOOK_TITLE
        self.capture_mode = self.capture_mode.strip()
        if self.output_mode not in OUTPUT_MODES:
            raise ValueError(
                "output_mode must be one of: images, text, pdf_image, pdf_searchable, audio"
            )
        if self.capture_mode not in CAPTURE_MODES:
            raise ValueError(
                "capture_mode must be one of: manual, window_full, "
                "window_left_third, window_right_third"
            )
        if self.n_pages < 1 or self.n_pages > 10000:
            raise ValueError("n_pages must be between 1 and 10000")
        if self.start_page < 1 or self.start_page > 999999:
            raise ValueError("start_page must be between 1 and 999999")
        if self.run_capture_phase and self.capture_mode == CAPTURE_MANUAL:
            if self.rect.width < 1 or self.rect.height < 1:
                raise ValueError("rect width and height must be positive for manual capture")
        elif self.run_capture_phase:
            if not self.target_window_title.strip():
                raise ValueError("target_window_title is required for window capture modes")
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
                "force_phase must be one of: '', capture, ocr, pdf, voice, all"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> CaptureConfig:
        rect_raw = data.get("rect") or {}
        rect = Rect(
            left=int(rect_raw.get("left", 0)),
            top=int(rect_raw.get("top", 0)),
            width=int(rect_raw.get("width", 0)),
            height=int(rect_raw.get("height", 0)),
        )
        capture_images = bool(data.get("capture_images", True))
        build_pdf = bool(data.get("build_pdf", True))
        ocr = bool(data.get("ocr", False))
        output_mode_raw = str(data.get("output_mode", "")).strip()
        output_mode = output_mode_raw
        if not output_mode:
            run_ocr_phase = bool(data.get("run_ocr_phase", ocr))
            run_pdf_phase = bool(data.get("run_pdf_phase", build_pdf))
            if run_pdf_phase and run_ocr_phase:
                output_mode = OUTPUT_PDF_SEARCHABLE
            elif run_pdf_phase:
                output_mode = OUTPUT_PDF_IMAGE
            elif run_ocr_phase:
                output_mode = OUTPUT_AUDIO if bool(data.get("voice", False)) else OUTPUT_TEXT
            else:
                output_mode = OUTPUT_IMAGES
        cfg = cls(
            title=str(data.get("title", DEFAULT_BOOK_TITLE)).strip()
            or DEFAULT_BOOK_TITLE,
            n_pages=int(data.get("n_pages", 1)),
            start_page=int(data.get("start_page", 1)),
            base_dir=str(data.get("base_dir", DEFAULT_BASE_DIR)),
            rect=rect,
            capture_mode=str(
                data.get("capture_mode", CAPTURE_MANUAL)
            ),
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
            capture_images=capture_images,
            build_pdf=build_pdf,
            ocr=ocr,
            output_mode=output_mode,
            run_capture_phase=bool(data.get("run_capture_phase", capture_images)),
            run_ocr_phase=bool(data.get("run_ocr_phase", ocr)),
            run_pdf_phase=bool(data.get("run_pdf_phase", build_pdf)),
            resume=bool(data.get("resume", True)),
            force_phase=str(data.get("force_phase", "")),
            ocr_lang=str(data.get("ocr_lang", "eng")),
            voice=bool(data.get("voice", False)),
            voice_lang_code=str(data.get("voice_lang_code", "en-US")),
            voice_model=str(data.get("voice_model", "en-US-Wavenet-A")),
            voice_gender=str(data.get("voice_gender", "FEMALE")),
        )
        if output_mode_raw:
            cfg.apply_output_mode()
        return cfg

    @classmethod
    def from_json_file(cls, path: Path | str) -> CaptureConfig:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_mapping(raw)

    def to_json_file(self, path: Path | str) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), indent=2), encoding="utf-8"
        )
