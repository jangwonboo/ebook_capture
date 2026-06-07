"""Execute a planned output job (images / pdf / text)."""

from __future__ import annotations

from core.assemble_markdown import assemble_markdown
from core.assemble_options import AssembleOptions
from core.config import OUTPUT_TEXT, CaptureConfig
from core.job_plan import StepKind, confirm_steps, plan_job
from core.pipeline import run_capture


def run_output_job(cfg: CaptureConfig, *, assume_yes: bool = False) -> int:
    try:
        steps, planned_cfg = plan_job(cfg)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if not confirm_steps(steps, assume_yes=assume_yes):
        return 1

    kinds = {s.kind for s in steps}

    if kinds & {StepKind.CAPTURE, StepKind.OCR_FROM_PNG, StepKind.OCR_FROM_PDF, StepKind.BUILD_PDF}:
        rc = run_capture(planned_cfg)
        if rc != 0:
            return rc

    if StepKind.ASSEMBLE in kinds:
        options = AssembleOptions.from_cli(style=planned_cfg.assemble_style)
        try:
            planned_cfg.skip_capture = True
            planned_cfg.validate()
            assemble_markdown(
                title=planned_cfg.title,
                tmp_dir=planned_cfg.tmp_dir(),
                output_md_path=planned_cfg.final_markdown_path(),
                structure_json_path=planned_cfg.structure_json_path(),
                options=options,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    if planned_cfg.output_mode == OUTPUT_TEXT:
        print(f"TEXT_OK {planned_cfg.final_markdown_path()}")
    return 0
