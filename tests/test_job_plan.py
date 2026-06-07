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
    assert status["ocr_json"] is False
