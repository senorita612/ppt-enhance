"""主流水线: PDF → 解析 → 纠错 → 生成 → 评测."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from ppt_enhance.agents.pipeline import CorrectionPipeline
from ppt_enhance.builder.pptx_builder import build_pptx
from ppt_enhance.config import settings
from ppt_enhance.eval.metrics import EvalReport, evaluate_conversion
from ppt_enhance.eval.renderer import pptx_to_images
from ppt_enhance.parser.docling_adapter import parse_with_docling
from ppt_enhance.parser.mineru_adapter import parse_with_mineru
from ppt_enhance.parser.pdf_renderer import render_pdf_pages
from ppt_enhance.parser.qwen_ocr_adapter import parse_with_qwen_ocr
from ppt_enhance.schemas.slide_ir import SlideIR


@dataclass
class PipelineResult:
    slide_ir: SlideIR
    pptx_path: Path
    eval_report: EvalReport | None = None
    correction_records: list = field(default_factory=list)
    work_dir: Path = Path(".")


def run_pipeline(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    mineru_json: str | Path | None = None,
    enable_correction: bool = True,
    enable_eval: bool = True,
    dpi: int | None = None,
    use_background: bool = True,
    ground_truth_text: str | None = None,
    parser: str = "docling",
) -> PipelineResult:
    pdf_path = Path(pdf_path)
    dpi = dpi or settings.default_dpi
    output_dir = Path(output_dir) if output_dir else pdf_path.parent / f"{pdf_path.stem}_output"
    work_dir = settings.work_dir / pdf_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    steps = ["解析 PDF", "智能纠错", "生成 PPTX", "质量评测"]
    bar = tqdm(total=len(steps), desc="PPT Enhance")

    # 1. 解析
    bar.set_description(steps[0])
    if mineru_json:
        slide_ir = parse_with_mineru(pdf_path, mineru_json, work_dir, dpi=dpi)
    elif parser == "qwen-ocr":
        slide_ir = parse_with_qwen_ocr(pdf_path, work_dir, dpi=dpi)
    else:
        slide_ir = parse_with_docling(pdf_path, work_dir, dpi=dpi)
    ir_path = output_dir / "slide_ir.json"
    slide_ir.save(ir_path)
    bar.update(1)

    # 2. 纠错
    bar.set_description(steps[1])
    pipeline = CorrectionPipeline()
    slide_ir = pipeline.run(slide_ir, enable_correction=enable_correction)
    slide_ir.save(output_dir / "slide_ir_corrected.json")
    bar.update(1)

    # 3. 生成
    bar.set_description(steps[2])
    pptx_path = output_dir / f"{pdf_path.stem}_enhanced.pptx"
    build_pptx(slide_ir, pptx_path, use_background=use_background)
    bar.update(1)

    # 4. 评测
    eval_report = None
    if enable_eval:
        bar.set_description(steps[3])
        source_images = render_pdf_pages(pdf_path, work_dir / "eval_source", dpi=dpi)
        ppt_images, visual_reliable, rendered_pdf = pptx_to_images(pptx_path, work_dir / "eval_pptx", dpi=dpi)
        eval_report = evaluate_conversion(
            slide_ir,
            source_images,
            ppt_images,
            ground_truth_text=ground_truth_text,
            visual_reliable=visual_reliable,
            output_pdf=rendered_pdf,
        )
        import json
        (output_dir / "eval_report.json").write_text(
            json.dumps(eval_report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        bar.update(1)

    bar.set_description("完成")
    bar.close()

    return PipelineResult(
        slide_ir=slide_ir,
        pptx_path=pptx_path,
        eval_report=eval_report,
        correction_records=pipeline.records,
        work_dir=work_dir,
    )
