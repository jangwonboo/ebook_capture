"""Analyze artifacts and plan output jobs (images / pdf / text)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core.config import OUTPUT_IMAGES, OUTPUT_PDF, OUTPUT_TEXT, CaptureConfig


class StepKind(str, Enum):
    CAPTURE = "capture"
    OCR_FROM_PNG = "ocr_from_png"
    OCR_FROM_PDF = "ocr_from_pdf"
    BUILD_PDF = "build_pdf"
    ASSEMBLE = "assemble"


@dataclass(frozen=True)
class PlannedStep:
    kind: StepKind
    label: str


def _glob_any(pattern: str, root: Path) -> bool:
    return any(root.glob(pattern))


def resolve_pdf_source(cfg: CaptureConfig) -> Path | None:
    if cfg.input_pdf.strip():
        path = Path(cfg.input_pdf).expanduser()
        if path.is_file():
            return path.resolve()
    book_pdf = cfg.final_pdf_path()
    if book_pdf.is_file():
        return book_pdf.resolve()
    return None


def artifact_status(cfg: CaptureConfig) -> dict[str, bool]:
    tmp = cfg.tmp_dir()
    title = cfg.title
    return {
        "png": _glob_any(f"{title}_*.png", tmp),
        "ocr_json": _glob_any(f"{title}_*.ocr.json", tmp),
        "pdf": cfg.final_pdf_path().is_file(),
        "markdown": cfg.final_markdown_path().is_file(),
        "input_pdf": resolve_pdf_source(cfg) is not None,
    }


def can_screen_capture(cfg: CaptureConfig) -> bool:
    if cfg.capture_mode == "manual":
        return cfg.rect.width >= 1 and cfg.rect.height >= 1
    return bool(cfg.target_window_title.strip())


def plan_job(cfg: CaptureConfig) -> tuple[list[PlannedStep], CaptureConfig]:
    """Return steps to run and a cfg copy with skip_capture / input_pdf adjusted."""
    import dataclasses

    cfg = dataclasses.replace(cfg)
    cfg.normalize()
    status = artifact_status(cfg)
    steps: list[PlannedStep] = []

    if cfg.output_mode == OUTPUT_IMAGES:
        if not status["png"] or cfg.should_force("capture"):
            if can_screen_capture(cfg) or cfg.capture_mode != "manual":
                steps.append(PlannedStep(StepKind.CAPTURE, "Capture page images (PNG)"))
                cfg.skip_capture = False
            elif not status["png"]:
                raise ValueError(
                    "No PNG files found and screen capture is not configured "
                    "(set window title or manual rect)."
                )
        else:
            cfg.skip_capture = True
        return steps, cfg

    if cfg.output_mode == OUTPUT_PDF:
        if not status["png"] or cfg.should_force("capture"):
            if can_screen_capture(cfg) or cfg.capture_mode != "manual":
                steps.append(
                    PlannedStep(StepKind.CAPTURE, "Capture page images (PNG) for PDF")
                )
                cfg.skip_capture = False
            elif not status["png"]:
                raise ValueError(
                    "No PNG files for PDF build; configure screen capture or run --images first."
                )
        else:
            cfg.skip_capture = True
        if not status["pdf"] or cfg.should_force("pdf"):
            steps.append(PlannedStep(StepKind.BUILD_PDF, f"Build PDF → {cfg.final_pdf_path()}"))
        return steps, cfg

    if cfg.output_mode == OUTPUT_TEXT:
        pdf_path = resolve_pdf_source(cfg)
        ocr_source: str | None = None

        if status["png"]:
            ocr_source = "png"
        elif pdf_path is not None:
            ocr_source = "pdf"
            cfg.input_pdf = str(pdf_path)

        need_ocr = not status["ocr_json"] or cfg.should_force("ocr")

        if need_ocr:
            if ocr_source == "png":
                steps.append(
                    PlannedStep(
                        StepKind.OCR_FROM_PNG,
                        "OCR from existing PNG → tmp/*.ocr.json",
                    )
                )
                cfg.skip_capture = True
            elif ocr_source == "pdf":
                steps.append(
                    PlannedStep(
                        StepKind.OCR_FROM_PDF,
                        f"OCR from PDF → tmp/*.ocr.json ({pdf_path})",
                    )
                )
                cfg.skip_capture = True
            elif can_screen_capture(cfg) or cfg.capture_mode != "manual":
                steps.append(PlannedStep(StepKind.CAPTURE, "Capture page images (PNG)"))
                steps.append(
                    PlannedStep(StepKind.OCR_FROM_PNG, "OCR from PNG → tmp/*.ocr.json")
                )
                cfg.skip_capture = False
            else:
                raise ValueError(
                    "No PNG or PDF source for text output. "
                    "Add tmp/*.png, place {title}.pdf, pass --input-pdf, "
                    "or configure screen capture."
                )

        if not status["markdown"] or cfg.should_force("ocr"):
            style = cfg.assemble_style
            steps.append(
                PlannedStep(
                    StepKind.ASSEMBLE,
                    f"Assemble Markdown ({style}) → {cfg.final_markdown_path()}",
                )
            )
        return steps, cfg

    raise ValueError(f"Unknown output_mode: {cfg.output_mode}")


def confirm_steps(steps: list[PlannedStep], *, assume_yes: bool = False) -> bool:
    if not steps:
        print("Nothing to do — outputs already exist (use --no-resume or --force-phase).")
        return False
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print("Non-interactive shell: pass --yes to run without confirmation.", file=sys.stderr)
        return False

    print("Planned steps:")
    for idx, step in enumerate(steps, start=1):
        print(f"  {idx}. {step.label}")
    try:
        answer = input("Proceed? [Y/n]: ").strip().lower()
    except EOFError:
        return False
    return answer in ("", "y", "yes")
