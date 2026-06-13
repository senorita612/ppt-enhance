"""命令行入口."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ppt_enhance.pipeline.main_pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PPT Enhance: 高保真 PDF-to-PPTX 重建与智能纠错",
    )
    parser.add_argument("pdf", type=str, help="输入 PDF 路径")
    parser.add_argument("-o", "--output", type=str, default=None, help="输出目录")
    parser.add_argument("--mineru-json", type=str, default=None, help="MinerU JSON 路径（可选）")
    parser.add_argument(
        "--parser",
        type=str,
        default="docling",
        choices=["docling", "qwen-ocr"],
        help="解析器：docling（矢量文本）或 qwen-ocr（纯图片 PDF，如 NotebookLM 导出）",
    )
    parser.add_argument("--no-correction", action="store_true", help="跳过智能纠错")
    parser.add_argument("--no-eval", action="store_true", help="跳过质量评测")
    parser.add_argument("--dpi", type=int, default=150, help="渲染 DPI")
    parser.add_argument("--no-background", action="store_true", help="不使用整页背景图模式")
    parser.add_argument("--ground-truth", type=str, default=None, help="Ground truth 文本文件（CER 评测）")
    parser.add_argument(
        "--protected-term",
        type=str,
        action="append",
        default=[],
        help="额外专有名词保护词；可重复传入，或用逗号/顿号分隔",
    )
    parser.add_argument("--speaker-notes", action="store_true", help="Generate PPT speaker notes")
    parser.add_argument(
        "--notes-material",
        type=str,
        action="append",
        default=[],
        help="Supplemental material path for speaker notes; can be passed multiple times",
    )
    parser.add_argument("--notes-seconds", type=int, default=75, help="Target seconds per slide")
    parser.add_argument("--notes-style", type=str, default="课程讲解", help="Speaker notes style")
    args = parser.parse_args()

    gt_text = None
    if args.ground_truth:
        gt_text = Path(args.ground_truth).read_text(encoding="utf-8")

    result = run_pipeline(
        pdf_path=args.pdf,
        output_dir=args.output,
        mineru_json=args.mineru_json,
        enable_correction=not args.no_correction,
        enable_eval=not args.no_eval,
        dpi=args.dpi,
        use_background=not args.no_background,
        ground_truth_text=gt_text,
        parser=args.parser,
        enable_speaker_notes=args.speaker_notes or bool(args.notes_material),
        reference_paths=args.notes_material,
        notes_seconds_per_slide=args.notes_seconds,
        speaker_notes_style=args.notes_style,
        extra_protected_terms=args.protected_term,
    )

    print(f"\n✅ 转换完成")
    print(f"📄 PPTX: {result.pptx_path}")
    print(f"📊 SlideIR: {result.pptx_path.parent / 'slide_ir_corrected.json'}")
    if result.slide_ir.protected_terms:
        print(f"🛡️  专有名词保护: {len(result.slide_ir.protected_terms)} 个")
    if result.correction_records:
        accepted = sum(1 for r in result.correction_records if r.accepted)
        print(f"✏️  纠错: {accepted}/{len(result.correction_records)} 条通过审查")
    if result.speaker_notes:
        print(f"Speaker Notes: {len(result.speaker_notes)} pages")
        model_tag = f" ({result.speaker_notes_model})" if result.speaker_notes_model else ""
        print(f"Speaker Notes mode: {result.speaker_notes_mode or 'fallback'}{model_tag}")
        print(f"Speaker Notes Markdown: {result.pptx_path.parent / 'speaker_notes.md'}")
    if result.eval_report:
        rep = result.eval_report
        tag = "" if rep.visual_reliable else "  (占位图，不可信)"
        print(f"📈 SSIM: {rep.ssim_mean:.4f}{tag}")
        print(f"📈 PSNR: {rep.psnr_mean:.2f} dB{tag}")
        print(f"📈 可编辑性: {rep.editability_ratio:.1%}")
        if rep.cer is not None:
            print(f"📈 CER: {rep.cer:.4f}")
        if rep.token_error_rate is not None:
            print(f"📈 Token Error Rate: {rep.token_error_rate:.4f}")
        print(f"📈 文本改动率: {rep.text_quality.char_change_ratio:.1%}")
        print(f"📈 文本框溢出风险: {rep.layout_risk.text_overflow_risk_ratio:.1%}")
        if rep.text_quality.numeric_mismatches:
            print(f"⚠️  数字变化风险: {len(rep.text_quality.numeric_mismatches)} 处")
        if rep.text_quality.protected_term_violations:
            print(f"⚠️  专有名词缺失风险: {len(rep.text_quality.protected_term_violations)} 处")
        if rep.notes:
            for note in rep.notes:
                print(f"ℹ️  {note}")


if __name__ == "__main__":
    main()
