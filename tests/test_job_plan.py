"""Tests for job planning (images / pdf / text)."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from core.config import OUTPUT_IMAGES, OUTPUT_PDF, OUTPUT_TEXT, CaptureConfig, Rect
from core.job_plan import StepKind, artifact_status, plan_job


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def test_plan_images_empty(tmp_path: Path) -> None:
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_IMAGES,
        rect=Rect(0, 0, 100, 100),
    )
    steps, planned = plan_job(cfg)
    assert len(steps) == 1
    assert steps[0].kind == StepKind.CAPTURE
    assert planned.skip_capture is False


def test_plan_images_existing_png(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_IMAGES)
    _touch(cfg.page_png_path(1))
    steps, planned = plan_job(cfg)
    assert steps == []
    assert planned.skip_capture is True


def test_plan_pdf_needs_build_only(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_PDF)
    _touch(cfg.page_png_path(1))
    steps, planned = plan_job(cfg)
    assert len(steps) == 1
    assert steps[0].kind == StepKind.BUILD_PDF
    assert planned.skip_capture is True


def test_plan_pdf_partial_png_resumes_capture(tmp_path: Path) -> None:
    """Existing early pages must not skip capture when later pages are missing."""
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_PDF,
        start_page=1,
        n_pages=5,
        target_window_title="Kindle",
        capture_mode="screen_left_third",
    )
    for page in (1, 2, 3):
        _touch(cfg.page_png_path(page))
    steps, planned = plan_job(cfg)
    kinds = [s.kind for s in steps]
    assert StepKind.CAPTURE in kinds
    assert StepKind.BUILD_PDF in kinds
    assert planned.skip_capture is False
    assert "2 missing" in steps[0].label


def test_plan_pdf_resume_mid_book_range(tmp_path: Path) -> None:
    """Full-book range with pages 1..N present resumes the remainder."""
    cfg = CaptureConfig(
        title="the_meaning_of_your_life",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_PDF,
        start_page=1,
        n_pages=292,
        target_window_title="Kindle",
        capture_mode="screen_left_third",
    )
    for page in range(1, 147):
        _touch(cfg.page_png_path(page))
    steps, planned = plan_job(cfg)
    assert planned.skip_capture is False
    assert steps[0].kind == StepKind.CAPTURE
    assert "146 missing" in steps[0].label
    assert steps[1].kind == StepKind.BUILD_PDF


def test_plan_text_from_png_and_assemble(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_TEXT)
    _touch(cfg.page_png_path(1))
    steps, planned = plan_job(cfg)
    kinds = [s.kind for s in steps]
    assert StepKind.OCR_FROM_PNG in kinds
    assert StepKind.ASSEMBLE in kinds
    assert planned.skip_capture is True


def test_plan_text_assemble_only(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_TEXT)
    _touch(cfg.page_ocr_json_path(1))
    steps, _ = plan_job(cfg)
    assert len(steps) == 1
    assert steps[0].kind == StepKind.ASSEMBLE


def test_plan_text_partial_ocr_resumes_from_pdf(tmp_path: Path) -> None:
    """Without PNGs, a short PDF clamps n_pages and OCRs from PDF."""
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_TEXT,
        n_pages=10,
    )
    _touch(cfg.page_ocr_json_path(1))
    cfg.final_markdown_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.final_markdown_path().write_text("# partial\n", encoding="utf-8")
    pdf = cfg.final_pdf_path()
    c = canvas.Canvas(str(pdf))
    for _ in range(5):
        c.drawString(72, 720, "x")
        c.showPage()
    c.save()

    steps, planned = plan_job(cfg)
    kinds = [s.kind for s in steps]
    assert planned.n_pages == 5
    assert StepKind.CAPTURE not in kinds
    assert StepKind.OCR_FROM_PDF in kinds
    assert StepKind.ASSEMBLE in kinds
    assert planned.skip_capture is True
    assert "4 missing" in steps[0].label


def test_plan_text_partial_png_clamps_and_ocrs_png(tmp_path: Path) -> None:
    """Partial PNG set clamps job range and OCRs PNGs (not the shorter book PDF)."""
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_TEXT,
        n_pages=5,
        target_window_title="Kindle",
        capture_mode="screen_left_third",
    )
    for page in (1, 2, 3):
        _touch(cfg.page_png_path(page))
    _touch(cfg.page_ocr_json_path(1))
    cfg.final_markdown_path().parent.mkdir(parents=True, exist_ok=True)
    cfg.final_markdown_path().write_text("# partial\n", encoding="utf-8")
    pdf = cfg.final_pdf_path()
    c = canvas.Canvas(str(pdf))
    for _ in range(3):
        c.drawString(72, 720, "x")
        c.showPage()
    c.save()

    steps, planned = plan_job(cfg)
    assert planned.n_pages == 3
    assert steps[0].kind == StepKind.OCR_FROM_PNG
    assert "2 missing" in steps[0].label
    assert steps[1].kind == StepKind.ASSEMBLE
    assert planned.skip_capture is True


def test_plan_text_partial_ocr_resumes_from_complete_png(tmp_path: Path) -> None:
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_TEXT,
        n_pages=3,
    )
    for page in (1, 2, 3):
        _touch(cfg.page_png_path(page))
    _touch(cfg.page_ocr_json_path(1))
    steps, planned = plan_job(cfg)
    assert steps[0].kind == StepKind.OCR_FROM_PNG
    assert "2 missing" in steps[0].label
    assert steps[1].kind == StepKind.ASSEMBLE
    assert planned.skip_capture is True


def test_plan_text_from_pdf(tmp_path: Path) -> None:
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_TEXT,
        n_pages=1,
    )
    pdf = cfg.final_pdf_path()
    pdf.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "x")
    c.showPage()
    c.save()

    steps, planned = plan_job(cfg)
    assert any(s.kind == StepKind.OCR_FROM_PDF for s in steps)
    assert planned.input_pdf == str(pdf.resolve())


def test_plan_text_no_source_raises(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_TEXT)
    with pytest.raises(ValueError, match="No PNG or PDF"):
        plan_job(cfg)


def test_artifact_status(tmp_path: Path) -> None:
    cfg = CaptureConfig(title="Book", base_dir=str(tmp_path), output_mode=OUTPUT_TEXT)
    _touch(cfg.page_png_path(1))
    status = artifact_status(cfg)
    assert status["png"] is True
    assert status["png_complete"] is True
    assert status["ocr_json"] is False
    assert status["ocr_complete"] is False


def test_artifact_status_partial_png_incomplete(tmp_path: Path) -> None:
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_PDF,
        n_pages=3,
    )
    _touch(cfg.page_png_path(1))
    status = artifact_status(cfg)
    assert status["png"] is True
    assert status["png_complete"] is False


def test_artifact_status_partial_ocr_incomplete(tmp_path: Path) -> None:
    cfg = CaptureConfig(
        title="Book",
        base_dir=str(tmp_path),
        output_mode=OUTPUT_TEXT,
        n_pages=3,
    )
    _touch(cfg.page_ocr_json_path(1))
    status = artifact_status(cfg)
    assert status["ocr_json"] is True
    assert status["ocr_complete"] is False
