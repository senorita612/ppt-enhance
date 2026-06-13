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
from ppt_enhance.notes import (
    SpeakerNote,
    SpeakerNotesResult,
    generate_speaker_notes,
    load_reference_text,
    save_speaker_notes_json,
    save_speaker_notes_markdown,
    write_speaker_notes,
)
from ppt_enhance.nlp.protected_terms import merge_protected_terms
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
    speaker_notes: list[SpeakerNote] = field(default_factory=list)
    speaker_notes_mode: str = ""
    speaker_notes_model: str = ""
    speaker_notes_outline: dict | None = None
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
    enable_speaker_notes: bool = False,
    reference_paths: list[str | Path] | None = None,
    reference_text: str | None = None,
    notes_seconds_per_slide: int = 75,
    speaker_notes_style: str = "课程讲解",
    extra_protected_terms: list[str] | str | None = None,
) -> PipelineResult:
    pdf_path = Path(pdf_path)
    dpi = dpi or settings.default_dpi
    output_dir = Path(output_dir) if output_dir else pdf_path.parent / f"{pdf_path.stem}_output"
    work_dir = settings.work_dir / pdf_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    steps = ["parse PDF", "correct text", "build PPTX"]
    if enable_speaker_notes:
        steps.append("generate speaker notes")
    if enable_eval:
        steps.append("evaluate quality")
    bar = tqdm(total=len(steps), desc="PPT Enhance")

    # 1. 解析
    bar.set_description(steps[0])
    if mineru_json:
        slide_ir = parse_with_mineru(pdf_path, mineru_json, work_dir, dpi=dpi)
    elif parser == "qwen-ocr":
        slide_ir = parse_with_qwen_ocr(pdf_path, work_dir, dpi=dpi)
    else:
        slide_ir = parse_with_docling(pdf_path, work_dir, dpi=dpi)
    slide_ir.protected_terms = merge_protected_terms(
        slide_ir.protected_terms,
        extra_protected_terms,
    )
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

    # 4. Speaker Notes
    speaker_notes: list[SpeakerNote] = []
    speaker_notes_result: SpeakerNotesResult | None = None
    if enable_speaker_notes:
        bar.set_description("generate speaker notes")
        material_text = load_reference_text(reference_paths, reference_text)
        speaker_notes_result = generate_speaker_notes(
            slide_ir,
            reference_text=material_text,
            seconds_per_slide=notes_seconds_per_slide,
            style=speaker_notes_style,
        )
        speaker_notes = speaker_notes_result.notes
        write_speaker_notes(pptx_path, speaker_notes)
        save_speaker_notes_json(speaker_notes_result, output_dir / "speaker_notes.json")
        save_speaker_notes_markdown(speaker_notes_result, output_dir / "speaker_notes.md")
        bar.update(1)

    # 5. 评测
    eval_report = None
    if enable_eval:
        bar.set_description("evaluate quality")
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
        speaker_notes=speaker_notes,
        speaker_notes_mode=speaker_notes_result.generation_mode if speaker_notes_result else "",
        speaker_notes_model=speaker_notes_result.model if speaker_notes_result else "",
        speaker_notes_outline=speaker_notes_result.plan.to_dict() if speaker_notes_result else None,
        work_dir=work_dir,
    )
