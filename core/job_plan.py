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


def _png_looks_present(path: Path) -> bool:
    """Fast presence check for planning (full verify happens at capture/PDF time)."""
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def missing_page_pngs(cfg: CaptureConfig) -> list[int]:
    """Page numbers in the configured range that do not yet have a PNG."""
    return [
        page_num
        for page_num in cfg.page_numbers()
        if not _png_looks_present(cfg.page_png_path(page_num))
    ]


def required_pngs_complete(cfg: CaptureConfig) -> bool:
    """True when every page in ``start_page``..``start_page+n_pages-1`` has a PNG."""
    return not missing_page_pngs(cfg)


def _ocr_json_looks_present(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def missing_page_ocr_jsons(cfg: CaptureConfig) -> list[int]:
    """Page numbers in the configured range that do not yet have OCR JSON."""
    return [
        page_num
        for page_num in cfg.page_numbers()
        if not _ocr_json_looks_present(cfg.page_ocr_json_path(page_num))
    ]


def required_ocr_complete(cfg: CaptureConfig) -> bool:
    """True when every page in the configured range has an OCR JSON file."""
    return not missing_page_ocr_jsons(cfg)


def consecutive_png_count_from_start(cfg: CaptureConfig) -> int:
    """Contiguous PNG count from ``start_page`` within the configured range."""
    count = 0
    for page_num in cfg.page_numbers():
        if not _png_looks_present(cfg.page_png_path(page_num)):
            break
        count += 1
    return count


def _clamp_n_pages(cfg: CaptureConfig, available: int, reason: str) -> bool:
    """Shrink ``n_pages`` to ``available`` when the job range is longer. Return True if changed."""
    if available < 1 or available >= cfg.n_pages:
        return False
    print(
        f"NOTE: clamping n_pages {cfg.n_pages} → {available} ({reason})",
        flush=True,
    )
    cfg.n_pages = available
    return True


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
    png_any = _glob_any(f"{title}_*.png", tmp)
    ocr_any = _glob_any(f"{title}_*.ocr.json", tmp)
    return {
        "png": png_any,
        "png_complete": required_pngs_complete(cfg),
        "ocr_json": ocr_any,
        "ocr_complete": required_ocr_complete(cfg),
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
        need_capture = not status["png_complete"] or cfg.should_force("capture")
        if need_capture:
            if can_screen_capture(cfg) or cfg.capture_mode != "manual":
                missing = missing_page_pngs(cfg)
                label = "Capture page images (PNG)"
                if status["png"] and missing and not cfg.should_force("capture"):
                    label = (
                        f"Resume capture ({len(missing)} missing PNG "
                        f"of {cfg.n_pages} pages)"
                    )
                steps.append(PlannedStep(StepKind.CAPTURE, label))
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
        need_capture = not status["png_complete"] or cfg.should_force("capture")
        if need_capture:
            if can_screen_capture(cfg) or cfg.capture_mode != "manual":
                missing = missing_page_pngs(cfg)
                label = "Capture page images (PNG) for PDF"
                if status["png"] and missing and not cfg.should_force("capture"):
                    label = (
                        f"Resume capture ({len(missing)} missing PNG "
                        f"of {cfg.n_pages} pages) for PDF"
                    )
                steps.append(PlannedStep(StepKind.CAPTURE, label))
                cfg.skip_capture = False
            elif not status["png"]:
                raise ValueError(
                    "No PNG files for PDF build; configure screen capture or run --images first."
                )
        else:
            cfg.skip_capture = True
        if not status["pdf"] or cfg.should_force("pdf") or need_capture:
            # Rebuild PDF when new pages were (or will be) captured.
            steps.append(PlannedStep(StepKind.BUILD_PDF, f"Build PDF → {cfg.final_pdf_path()}"))
        return steps, cfg

    if cfg.output_mode == OUTPUT_TEXT:
        pdf_path = resolve_pdf_source(cfg)
        ocr_source: str | None = None
        avail_png = consecutive_png_count_from_start(cfg)

        # Prefer contiguous PNGs already on disk (even if config n_pages is larger).
        # Fall back to book PDF, clamping to its length. Avoid failing validate()
        # when config still says the full book page count.
        if status["png_complete"]:
            ocr_source = "png"
        elif avail_png >= 1:
            _clamp_n_pages(
                cfg,
                avail_png,
                f"{avail_png} contiguous PNG from page {cfg.start_page}",
            )
            status = artifact_status(cfg)
            ocr_source = "png"
        elif pdf_path is not None:
            from core.pdf_input import pdf_page_count

            total = pdf_page_count(pdf_path)
            max_pages = max(0, total - cfg.start_page + 1)
            _clamp_n_pages(cfg, max_pages, f"PDF has {total} pages")
            status = artifact_status(cfg)
            ocr_source = "pdf"
            cfg.input_pdf = str(pdf_path)
        elif status["png"] and (
            can_screen_capture(cfg) or cfg.capture_mode != "manual"
        ):
            ocr_source = "png_resume"
        elif status["png"]:
            ocr_source = "png"

        need_ocr = not status["ocr_complete"] or cfg.should_force("ocr")

        if need_ocr:
            if ocr_source == "png_resume":
                missing = missing_page_pngs(cfg)
                steps.append(
                    PlannedStep(
                        StepKind.CAPTURE,
                        f"Resume capture ({len(missing)} missing PNG "
                        f"of {cfg.n_pages} pages)",
                    )
                )
                steps.append(
                    PlannedStep(
                        StepKind.OCR_FROM_PNG,
                        "OCR from PNG → tmp/*.ocr.json",
                    )
                )
                cfg.skip_capture = False
            elif ocr_source == "png":
                missing_ocr = missing_page_ocr_jsons(cfg)
                label = "OCR from existing PNG → tmp/*.ocr.json"
                if status["ocr_json"] and missing_ocr and not cfg.should_force("ocr"):
                    label = (
                        f"Resume OCR ({len(missing_ocr)} missing JSON "
                        f"of {cfg.n_pages} pages) from PNG"
                    )
                steps.append(PlannedStep(StepKind.OCR_FROM_PNG, label))
                cfg.skip_capture = True
            elif ocr_source == "pdf":
                missing_ocr = missing_page_ocr_jsons(cfg)
                label = f"OCR from PDF → tmp/*.ocr.json ({pdf_path})"
                if status["ocr_json"] and missing_ocr and not cfg.should_force("ocr"):
                    label = (
                        f"Resume OCR ({len(missing_ocr)} missing JSON "
                        f"of {cfg.n_pages} pages) from PDF"
                    )
                steps.append(PlannedStep(StepKind.OCR_FROM_PDF, label))
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

        # Re-assemble whenever OCR will (or did need to) run, even if an old
        # partial .md already exists from a one-page trial.
        if need_ocr or not status["markdown"] or cfg.should_force("ocr"):
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
