"""Streamlit web UI with staged review and page-level preview."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import streamlit as st

from ppt_enhance.agents.pipeline import CorrectionPipeline
from ppt_enhance.builder.pptx_builder import build_pptx
from ppt_enhance.config import settings
from ppt_enhance.eval.metrics import (
    EvalReport,
    compute_layout_risk,
    compute_text_quality,
    evaluate_conversion,
)
from ppt_enhance.eval.renderer import pptx_to_images
from ppt_enhance.nlp.protected_terms import merge_protected_terms
from ppt_enhance.notes import (
    SpeakerNote,
    SpeakerNotesResult,
    generate_speaker_notes,
    load_reference_text,
    save_speaker_notes_json,
    save_speaker_notes_markdown,
    write_speaker_notes,
)
from ppt_enhance.parser.docling_adapter import parse_with_docling
from ppt_enhance.parser.mineru_adapter import parse_with_mineru
from ppt_enhance.parser.pdf_renderer import render_pdf_pages
from ppt_enhance.parser.qwen_ocr_adapter import parse_with_qwen_ocr
from ppt_enhance.schemas.slide_ir import SlideIR, SlidePage


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "deck"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._") or "deck"


def _file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:12]


def _workspace_for_upload(filename: str, data: bytes) -> Path:
    return settings.work_dir / "ui_sessions" / f"{_safe_stem(filename)}_{_file_hash(data)}"


def _source_images(slide_ir: SlideIR, pdf_path: Path, work_dir: Path, dpi: int) -> dict[int, Path]:
    images = {
        page.page_no: Path(page.render_path)
        for page in slide_ir.pages
        if page.render_path and Path(page.render_path).exists()
    }
    missing = [page.page_no for page in slide_ir.pages if page.page_no not in images]
    if missing:
        rendered = render_pdf_pages(pdf_path, work_dir / "renders", dpi=dpi)
        images.update(rendered)
    return images


def _parse_and_correct(
    *,
    pdf_path: Path,
    output_dir: Path,
    work_dir: Path,
    mineru_json: Path | None,
    parser: str,
    dpi: int,
    enable_correction: bool,
    extra_protected_terms: str,
) -> tuple[SlideIR, list[Any], dict[int, Path]]:
    if mineru_json:
        slide_ir = parse_with_mineru(pdf_path, mineru_json, work_dir, dpi=dpi)
    elif parser == "qwen-ocr":
        slide_ir = parse_with_qwen_ocr(pdf_path, work_dir, dpi=dpi)
    else:
        slide_ir = parse_with_docling(pdf_path, work_dir, dpi=dpi)

    slide_ir.protected_terms = merge_protected_terms(
        slide_ir.protected_terms,
        extra_protected_terms or None,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    slide_ir.save(output_dir / "slide_ir.json")

    correction = CorrectionPipeline()
    corrected_ir = correction.run(slide_ir, enable_correction=enable_correction)
    corrected_ir.save(output_dir / "slide_ir_corrected.json")

    return corrected_ir, correction.records, _source_images(corrected_ir, pdf_path, work_dir, dpi)


def _page_by_no(slide_ir: SlideIR, page_no: int) -> SlidePage:
    for page in slide_ir.pages:
        if page.page_no == page_no:
            return page
    raise ValueError(f"Page {page_no} not found")


def _edit_key(prefix: str, element_id: str) -> str:
    return f"{prefix}:{element_id}"


def _apply_available_edits(slide_ir: SlideIR, key_prefix: str) -> None:
    for elem in slide_ir.all_text_elements():
        key = _edit_key(key_prefix, elem.id)
        if key not in st.session_state:
            continue
        new_text = st.session_state[key]
        elem.corrected_text = None if new_text == elem.text else new_text


def _reset_page_widgets(page: SlidePage, key_prefix: str) -> None:
    for elem in page.text_elements():
        st.session_state[_edit_key(key_prefix, elem.id)] = elem.text


def _single_page_ir(slide_ir: SlideIR, page_no: int) -> SlideIR:
    cloned = slide_ir.model_copy(deep=True)
    cloned.pages = [_page_by_no(cloned, page_no)]
    cloned.metadata = {**cloned.metadata, "preview_page": page_no}
    return cloned


def _save_note_materials(files: list[Any] | None, workspace: Path) -> list[Path]:
    if not files:
        return []
    material_dir = workspace / "notes_materials"
    material_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for uploaded in files:
        path = material_dir / Path(uploaded.name).name
        path.write_bytes(uploaded.getvalue())
        paths.append(path)
    return paths


def _render_current_page_preview(
    *,
    slide_ir: SlideIR,
    page_no: int,
    workspace: Path,
    use_background: bool,
    dpi: int,
) -> dict[str, Any]:
    preview_dir = workspace / "page_previews" / f"page_{page_no:04d}"
    preview_dir.mkdir(parents=True, exist_ok=True)
    pptx_path = preview_dir / f"page_{page_no:04d}_preview.pptx"
    build_pptx(_single_page_ir(slide_ir, page_no), pptx_path, use_background=use_background)
    images, visual_reliable, rendered_pdf = pptx_to_images(pptx_path, preview_dir / "rendered", dpi=dpi)
    return {
        "page_no": page_no,
        "pptx_path": str(pptx_path),
        "image_path": str(images[0]) if images else "",
        "visual_reliable": visual_reliable,
        "rendered_pdf": str(rendered_pdf) if rendered_pdf else "",
    }


def _generate_full_deck(
    *,
    slide_ir: SlideIR,
    pdf_path: Path,
    output_dir: Path,
    work_dir: Path,
    source_images: dict[int, Path],
    use_background: bool,
    dpi: int,
    preview_dpi: int,
    render_output_preview: bool,
    enable_eval: bool,
    ground_truth_text: str | None,
    enable_speaker_notes: bool,
    reference_paths: list[Path],
    reference_text: str | None,
    notes_seconds_per_slide: int,
    speaker_notes_style: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    final_ir_path = output_dir / "slide_ir_final.json"
    slide_ir.save(final_ir_path)

    pptx_path = output_dir / f"{Path(pdf_path).stem}_enhanced.pptx"
    build_pptx(slide_ir, pptx_path, use_background=use_background)

    speaker_notes: list[SpeakerNote] = []
    speaker_notes_result: SpeakerNotesResult | None = None
    if enable_speaker_notes:
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

    ppt_images: list[Path] = []
    visual_reliable = False
    rendered_pdf: Path | None = None
    if render_output_preview or enable_eval:
        render_dpi = dpi if enable_eval else preview_dpi
        ppt_images, visual_reliable, rendered_pdf = pptx_to_images(
            pptx_path,
            work_dir / "eval_pptx",
            dpi=render_dpi,
        )

    eval_report: EvalReport | None = None
    if enable_eval:
        eval_report = evaluate_conversion(
            slide_ir,
            source_images,
            ppt_images,
            ground_truth_text=ground_truth_text,
            visual_reliable=visual_reliable,
            output_pdf=rendered_pdf,
        )
        (output_dir / "eval_report.json").write_text(
            json.dumps(eval_report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    page_numbers = [page.page_no for page in sorted(slide_ir.pages, key=lambda p: p.page_no)]
    ppt_image_map = {
        page_no: str(path)
        for page_no, path in zip(page_numbers, ppt_images)
        if path.exists()
    }

    return {
        "pptx_path": str(pptx_path),
        "slide_ir_path": str(final_ir_path),
        "ppt_images": ppt_image_map,
        "visual_reliable": visual_reliable,
        "eval_report": eval_report,
        "speaker_notes": speaker_notes,
        "speaker_notes_mode": speaker_notes_result.generation_mode if speaker_notes_result else "",
        "speaker_notes_model": speaker_notes_result.model if speaker_notes_result else "",
        "speaker_notes_outline": speaker_notes_result.plan.to_dict() if speaker_notes_result else None,
    }


def _show_quality_summary(slide_ir: SlideIR, eval_report: EvalReport | None) -> None:
    text_quality = compute_text_quality(slide_ir)
    layout_risk, _ = compute_layout_risk(slide_ir)

    m1, m2, m3 = st.columns(3)
    m1.metric("文本改动率", f"{text_quality.char_change_ratio:.1%}")
    m2.metric("溢出风险", f"{layout_risk.text_overflow_risk_ratio:.1%}")
    m3.metric("重叠风险", f"{layout_risk.overlap_pairs}")

    if eval_report:
        e1, e2, e3 = st.columns(3)
        e1.metric("SSIM", f"{eval_report.ssim_mean:.4f}")
        e2.metric("PSNR", f"{eval_report.psnr_mean:.1f} dB")
        e3.metric("可编辑率", f"{eval_report.editability_ratio:.1%}")
        if eval_report.layout_iou_mean is not None:
            st.metric("版面 IoU", f"{eval_report.layout_iou_mean:.4f}")
        for note in eval_report.notes:
            st.info(note)

    if text_quality.numeric_mismatches:
        st.warning(f"数字变化风险：{len(text_quality.numeric_mismatches)} 处")
    if text_quality.protected_term_violations:
        st.warning(f"专有名词缺失风险：{len(text_quality.protected_term_violations)} 处")


def _show_page_metrics(slide_ir: SlideIR, page_no: int) -> None:
    layout_risk, page_counts = compute_layout_risk(slide_ir)
    page = _page_by_no(slide_ir, page_no)
    changed = sum(1 for elem in page.text_elements() if elem.final_text != elem.text)
    overflow_count, overlap_count = page_counts.get(page_no, (0, 0))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("文本元素", len(page.text_elements()))
    c2.metric("已修改", changed)
    c3.metric("溢出风险", overflow_count)
    c4.metric("重叠风险", overlap_count)

    overflow_details = [d for d in layout_risk.overflow_details if d.get("page") == page_no]
    overlap_details = [d for d in layout_risk.overlap_details if d.get("page") == page_no]
    if overflow_details:
        with st.expander("本页溢出风险详情", expanded=False):
            st.json(overflow_details)
    if overlap_details:
        with st.expander("本页重叠风险详情", expanded=False):
            st.json(overlap_details)


def _show_downloads(build_state: dict[str, Any]) -> None:
    pptx_path = Path(build_state.get("pptx_path", ""))
    if pptx_path.exists():
        st.download_button(
            "下载 PPTX",
            data=pptx_path.read_bytes(),
            file_name=pptx_path.name,
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )

    ir_path = Path(build_state.get("slide_ir_path", ""))
    if ir_path.exists():
        st.download_button(
            "下载校对后的 SlideIR JSON",
            data=ir_path.read_bytes(),
            file_name="slide_ir_final.json",
            mime="application/json",
        )

    notes_md = pptx_path.parent / "speaker_notes.md" if pptx_path.exists() else Path()
    if notes_md.exists():
        st.download_button(
            "下载 Speaker Notes Markdown",
            data=notes_md.read_text(encoding="utf-8"),
            file_name="speaker_notes.md",
            mime="text/markdown",
        )


def _show_speaker_notes(build_state: dict[str, Any]) -> None:
    speaker_notes = build_state.get("speaker_notes") or []
    if not speaker_notes:
        return

    st.subheader("Speaker Notes")
    mode = build_state.get("speaker_notes_mode") or "fallback"
    model = build_state.get("speaker_notes_model") or "local fallback"
    st.caption(f"生成模式：{mode} | 模型：{model}")

    outline = build_state.get("speaker_notes_outline")
    if outline:
        with st.expander("整场演讲主线", expanded=False):
            st.markdown(f"**开场**：{outline.get('opening', '')}")
            st.markdown(f"**主线**：{outline.get('throughline', '')}")
            st.markdown(f"**收束**：{outline.get('closing', '')}")

    for note in speaker_notes:
        with st.expander(f"第 {note.page_no} 页：{note.title}", expanded=note.page_no == 1):
            st.caption(
                f"生成模式：{note.generation_mode}"
                f"{f' | {note.model}' if note.model else ''}"
            )
            st.write(note.note_text)


st.set_page_config(page_title="PPT Enhance", layout="wide")

st.title("PPT Enhance")
st.caption("PDF-to-PPTX 重建、逐页校对、单页预览、质量评估与 Speaker Notes 生成")

with st.sidebar:
    st.header("处理设置")
    parser_choice = st.selectbox("解析器", ["docling", "qwen-ocr"])
    enable_correction = st.toggle("启用智能纠错", value=True)
    use_background = st.toggle("整页背景模式", value=True)
    dpi = st.slider("处理 DPI", 72, 300, 150, step=10)
    preview_dpi = st.slider("预览 DPI", 72, 180, 110, step=10)
    render_output_preview = st.toggle(
        "生成后渲染预览",
        value=False,
        help="渲染整份 PPTX 会启动 LibreOffice；需要逐页图片对比时再开启。",
    )
    enable_eval = st.toggle("生成后完整质量评估", value=False, help="需要 LibreOffice，速度会明显变慢。")
    mineru_json = st.file_uploader("MinerU JSON（可选）", type=["json"])
    protected_terms_text = st.text_area("额外专有名词保护词", height=80)
    ground_truth = st.text_area("Ground Truth 文本（CER/TER，可选）", height=100)

    st.divider()
    st.header("Speaker Notes")
    enable_speaker_notes = st.toggle("生成 Speaker Notes", value=False)
    notes_seconds = st.slider("每页讲稿时长（秒）", 30, 180, 75, step=15)
    notes_style = st.selectbox("讲稿风格", ["课程讲解", "商务汇报", "答辩陈述", "教学培训"])
    notes_materials = st.file_uploader(
        "演讲稿补充资料",
        type=["txt", "md", "json", "pdf", "docx"],
        accept_multiple_files=True,
    )
    notes_extra = st.text_area("额外讲稿要求", height=80)

uploaded = st.file_uploader("上传 PDF 文件", type=["pdf"])

if not uploaded:
    st.info("上传 PDF 后，先解析并进入人工校对，再按需生成当前页预览或导出整份 PPTX。")
    st.markdown(
        """
        **推荐流程**

        1. 解析 PDF，生成可编辑的 SlideIR。
        2. 逐页检查文本、专有名词和数字，必要时手动修正。
        3. 对当前页快速生成预览，确认版式后导出整份 PPTX。
        4. 需要报告时再打开完整质量评估，避免每次都等待 LibreOffice 渲染。
        """
    )
    st.stop()

upload_bytes = uploaded.getvalue()
upload_hash = _file_hash(upload_bytes)
workspace = _workspace_for_upload(uploaded.name, upload_bytes)
output_dir = workspace / "output"
work_dir = workspace / "work"
pdf_path = workspace / Path(uploaded.name).name

new_file_loaded = st.session_state.get("active_upload_hash") not in (None, upload_hash)
if new_file_loaded:
    st.info("检测到新的上传文件。点击“解析并进入人工校对”后会切换到新文件。")

parse_col, state_col = st.columns([1, 2])
with parse_col:
    parse_clicked = st.button("解析并进入人工校对", type="primary")
with state_col:
    if st.session_state.get("slide_ir") is not None:
        st.caption(f"当前缓存：{st.session_state.get('workspace', '')}")

if parse_clicked:
    workspace.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(upload_bytes)

    mineru_path = None
    if mineru_json is not None:
        mineru_path = workspace / "mineru.json"
        mineru_path.write_bytes(mineru_json.getvalue())

    with st.spinner("正在解析 PDF 并生成校对层..."):
        slide_ir, correction_records, source_images = _parse_and_correct(
            pdf_path=pdf_path,
            output_dir=output_dir,
            work_dir=work_dir,
            mineru_json=mineru_path,
            parser=parser_choice,
            dpi=dpi,
            enable_correction=enable_correction,
            extra_protected_terms=protected_terms_text,
        )

    st.session_state.active_upload_hash = upload_hash
    st.session_state.workspace = str(workspace)
    st.session_state.pdf_path = str(pdf_path)
    st.session_state.output_dir = str(output_dir)
    st.session_state.work_dir = str(work_dir)
    st.session_state.slide_ir = slide_ir
    st.session_state.correction_records = correction_records
    st.session_state.source_images = {k: str(v) for k, v in source_images.items()}
    st.session_state.edit_key_prefix = f"edit:{upload_hash}:{len(correction_records)}"
    st.session_state.page_preview = {}
    st.session_state.build_state = {}
    st.success("解析完成。现在可以逐页校对，再生成预览或导出 PPTX。")

if st.session_state.get("active_upload_hash") != upload_hash:
    st.stop()

slide_ir: SlideIR | None = st.session_state.get("slide_ir")
if slide_ir is None:
    st.info("请先点击“解析并进入人工校对”。")
    st.stop()

key_prefix = st.session_state.get("edit_key_prefix", f"edit:{upload_hash}")
source_images = {
    int(page_no): Path(path)
    for page_no, path in (st.session_state.get("source_images") or {}).items()
}
page_numbers = [page.page_no for page in sorted(slide_ir.pages, key=lambda p: p.page_no)]
selected_page_no = st.selectbox(
    "选择页面",
    page_numbers,
    format_func=lambda n: f"第 {n} 页",
)
selected_page = _page_by_no(slide_ir, selected_page_no)

tab_review, tab_export, tab_records = st.tabs(["逐页预览与校对", "生成与评估", "记录与数据"])

with tab_review:
    _show_page_metrics(slide_ir, selected_page_no)

    reset_col, apply_col, preview_col = st.columns([1, 1, 1.4])
    with reset_col:
        if st.button("本页恢复解析文本"):
            _reset_page_widgets(selected_page, key_prefix)
            _apply_available_edits(slide_ir, key_prefix)
            st.session_state.build_state = {}
            st.success("本页文本已恢复为解析文本。")
    with apply_col:
        apply_clicked = st.button("应用本页编辑")
    with preview_col:
        preview_clicked = st.button("快速重生成当前页预览")

    left, right = st.columns(2)
    with left:
        st.subheader("原始页面")
        source_path = source_images.get(selected_page_no)
        if source_path and source_path.exists():
            st.image(str(source_path), caption=f"原始 PDF 第 {selected_page_no} 页", use_column_width=True)
        else:
            st.info("没有找到原始页面渲染图。")

    with right:
        st.subheader("生成预览")
        preview_state = st.session_state.get("page_preview") or {}
        full_preview = (st.session_state.get("build_state") or {}).get("ppt_images") or {}
        preview_image = ""
        if preview_state.get("page_no") == selected_page_no:
            preview_image = preview_state.get("image_path", "")
        elif selected_page_no in full_preview:
            preview_image = full_preview[selected_page_no]
        if preview_image and Path(preview_image).exists():
            st.image(str(preview_image), caption=f"生成 PPT 第 {selected_page_no} 页", use_column_width=True)
        else:
            st.info("点击“快速重生成当前页预览”后，这里会显示当前页生成效果。")

    st.subheader("本页文本校对")
    text_elements = selected_page.text_elements()
    if not text_elements:
        st.info("本页没有可编辑文本元素。")
    for idx, elem in enumerate(text_elements, start=1):
        label = f"{idx}. {elem.type.value} | {elem.id}"
        with st.expander(label, expanded=idx <= 3):
            if elem.corrected_text is not None and elem.corrected_text != elem.text:
                st.caption(f"解析原文：{elem.text}")
            st.text_area(
                "校对文本",
                value=elem.final_text,
                key=_edit_key(key_prefix, elem.id),
                height=90,
                label_visibility="collapsed",
            )
            st.caption(
                f"bbox=({elem.bbox.x0:.0f}, {elem.bbox.y0:.0f}, "
                f"{elem.bbox.x1:.0f}, {elem.bbox.y1:.0f})"
            )

    if apply_clicked:
        _apply_available_edits(slide_ir, key_prefix)
        st.session_state.build_state = {}
        st.success("本页编辑已应用到中间结果。")

    if preview_clicked:
        _apply_available_edits(slide_ir, key_prefix)
        st.session_state.build_state = {}
        with st.spinner("正在生成并渲染当前页预览..."):
            st.session_state.page_preview = _render_current_page_preview(
                slide_ir=slide_ir,
                page_no=selected_page_no,
                workspace=workspace,
                use_background=use_background,
                dpi=preview_dpi,
            )
        st.success("当前页预览已更新。")

with tab_export:
    st.subheader("导出整份 PPTX")
    st.caption("这里不会重新解析 PDF，只会使用当前校对后的 SlideIR 重新生成 PPTX。")

    gen_col, info_col = st.columns([1, 2])
    with gen_col:
        generate_clicked = st.button("生成 / 重新生成整份 PPTX", type="primary")
    with info_col:
        if enable_eval:
            st.info("已开启完整质量评估：会调用 LibreOffice 渲染 PPTX，耗时更长。")
        elif render_output_preview:
            st.info("已开启生成后预览：会渲染 PPTX 图片，但不跑完整评估。")
        else:
            st.info("当前为最快导出模式：不渲染生成预览，也不跑完整评估。")

    if generate_clicked:
        _apply_available_edits(slide_ir, key_prefix)
        reference_paths = _save_note_materials(notes_materials, workspace)
        with st.spinner("正在生成整份 PPTX..."):
            st.session_state.build_state = _generate_full_deck(
                slide_ir=slide_ir,
                pdf_path=Path(st.session_state.pdf_path),
                output_dir=Path(st.session_state.output_dir),
                work_dir=Path(st.session_state.work_dir),
                source_images=source_images,
                use_background=use_background,
                dpi=dpi,
                preview_dpi=preview_dpi,
                render_output_preview=render_output_preview,
                enable_eval=enable_eval,
                ground_truth_text=ground_truth or None,
                enable_speaker_notes=enable_speaker_notes or bool(notes_materials) or bool(notes_extra),
                reference_paths=reference_paths,
                reference_text=notes_extra or None,
                notes_seconds_per_slide=notes_seconds,
                speaker_notes_style=notes_style,
            )
        st.success("整份 PPTX 已生成。")

    build_state = st.session_state.get("build_state") or {}
    if build_state:
        _show_downloads(build_state)
        _show_quality_summary(slide_ir, build_state.get("eval_report"))
        _show_speaker_notes(build_state)

with tab_records:
    st.subheader("解析概览")
    _apply_available_edits(slide_ir, key_prefix)
    st.json(
        {
            "pages": len(slide_ir.pages),
            "elements": sum(len(page.elements) for page in slide_ir.pages),
            "text_elements": len(slide_ir.all_text_elements()),
            "protected_terms": slide_ir.protected_terms[:20],
            "protected_term_count": len(slide_ir.protected_terms),
            "parser": slide_ir.parser,
            "dpi": slide_ir.dpi,
        }
    )

    st.download_button(
        "下载当前校对中的 SlideIR JSON",
        data=json.dumps(slide_ir.model_dump(), ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="slide_ir_reviewing.json",
        mime="application/json",
    )

    records = st.session_state.get("correction_records") or []
    if records:
        st.subheader("纠错记录")
        accepted = [record for record in records if record.accepted]
        rejected = [record for record in records if not record.accepted]
        tab_a, tab_r = st.tabs([f"已通过 ({len(accepted)})", f"已拒绝 ({len(rejected)})"])
        with tab_a:
            for record in accepted:
                st.markdown(f"**{record.element_id}**")
                st.markdown(f"- 原文: `{record.original}`")
                st.markdown(f"- 修正: `{record.corrected}`")
                st.markdown(f"- 原因: {record.reason}")
        with tab_r:
            for record in rejected:
                st.markdown(f"**{record.element_id}**: {record.reject_reason}")
