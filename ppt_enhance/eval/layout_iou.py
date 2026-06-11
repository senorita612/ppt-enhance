"""往返版面 IoU: 独立测量重建 PPTX 的版面保真度.

核心思想（避免循环论证）：
不直接拿"写进 PPTX 的坐标"和"源坐标"比（那必然接近 1.0，是自证）。
而是把生成的 PPTX 经 LibreOffice 渲染回 PDF，再用 PyMuPDF 从渲染结果中
**独立地重新提取**文本块及其真实坐标，按文本内容匹配回源元素，
计算归一化边界框的真实 IoU。

这是一次真正的往返：源版面 → SlideIR → PPTX → 渲染 PDF → 重新检测版面。
能捕捉元素丢失、文本框出界、长宽比错配、自动换行撑破等真实缺陷。
LibreOffice 不可用时返回 None，绝不伪造数值。
"""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path

import fitz

from ppt_enhance.schemas.slide_ir import SlideIR


def _normalize(box: tuple[float, float, float, float], pw: float, ph: float) -> tuple[float, float, float, float]:
    """像素/点坐标 → 归一化 [0,1] (x0, y0, x1, y1)."""
    if pw <= 0 or ph <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (box[0] / pw, box[1] / ph, box[2] / pw, box[3] / ph)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _normalize_text(s: str) -> str:
    """去除空白与常见标点，便于跨渲染器匹配."""
    return "".join(ch for ch in s if not ch.isspace())


def _text_sim(a: str, b: str) -> float:
    a, b = _normalize_text(a), _normalize_text(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def extract_output_boxes(pdf_path: str | Path) -> dict[int, list[tuple[str, tuple[float, float, float, float], tuple[float, float]]]]:
    """从渲染后的 PDF 独立提取每页文本块及归一化坐标.

    返回 {page_index(0起): [(text, norm_bbox, (page_w, page_h)), ...]}。
    """
    doc = fitz.open(str(pdf_path))
    result: dict[int, list] = {}
    try:
        for pi in range(len(doc)):
            page = doc[pi]
            pw, ph = page.rect.width, page.rect.height
            blocks = page.get_text("blocks") or []
            page_boxes = []
            for b in blocks:
                # block: (x0, y0, x1, y1, text, block_no, block_type)
                if len(b) < 5:
                    continue
                text = (b[4] or "").strip()
                if not text:
                    continue
                norm = _normalize((b[0], b[1], b[2], b[3]), pw, ph)
                page_boxes.append((text, norm, (pw, ph)))
            result[pi] = page_boxes
    finally:
        doc.close()
    return result


def compute_layout_iou(
    slide_ir: SlideIR,
    output_pdf: str | Path | None,
    sim_threshold: float = 0.55,
) -> tuple[float | None, float | None, list[dict]]:
    """计算往返版面 IoU.

    返回 (mean_iou, match_rate, per_element_details)。
    output_pdf 为 None 或不存在时返回 (None, None, []) —— 不伪造。
    mean_iou: 成功匹配元素的平均 IoU。
    match_rate: 成功在输出中找回的源文本元素比例（衡量"有没有丢元素"）。
    """
    if not output_pdf or not Path(output_pdf).exists():
        return None, None, []

    output_boxes = extract_output_boxes(output_pdf)
    sorted_pages = sorted(slide_ir.pages, key=lambda p: p.page_no)

    ious: list[float] = []
    matched = 0
    total = 0
    details: list[dict] = []

    for page_idx, page in enumerate(sorted_pages):
        src_elems = page.text_elements()
        out_candidates = list(output_boxes.get(page_idx, []))
        for elem in src_elems:
            total += 1
            src_norm = elem.bbox.to_relative(page.width, page.height)
            src_norm_xyxy = (src_norm[0], src_norm[1], src_norm[0] + src_norm[2], src_norm[1] + src_norm[3])

            # 在输出页面找文本最相近的块
            best_sim = 0.0
            best_j = -1
            for j, (otext, _, _) in enumerate(out_candidates):
                sim = _text_sim(elem.final_text, otext)
                if sim > best_sim:
                    best_sim, best_j = sim, j

            if best_j >= 0 and best_sim >= sim_threshold:
                _, out_norm, _ = out_candidates.pop(best_j)  # 一对一匹配，用过即移除
                iou = _iou(src_norm_xyxy, out_norm)
                ious.append(iou)
                matched += 1
                details.append({
                    "page": page.page_no,
                    "text": elem.final_text[:30],
                    "sim": round(best_sim, 3),
                    "iou": round(iou, 3),
                })
            else:
                details.append({
                    "page": page.page_no,
                    "text": elem.final_text[:30],
                    "sim": round(best_sim, 3),
                    "iou": None,
                    "note": "未在输出中找回（疑似丢失/严重错位）",
                })

    mean_iou = sum(ious) / len(ious) if ious else 0.0
    match_rate = matched / total if total else 0.0
    return mean_iou, match_rate, details
