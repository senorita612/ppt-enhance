"""转换质量评测: SSIM / PSNR / IoU / CER."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio, structural_similarity

from ppt_enhance.schemas.slide_ir import SlideIR


@dataclass
class PageMetrics:
    page_no: int
    ssim: float = 0.0
    psnr: float = 0.0
    bbox_iou_mean: float = 0.0
    text_overflow_risks: int = 0
    overlap_pairs: int = 0


@dataclass
class TextQualityMetrics:
    source_chars: int = 0
    output_chars: int = 0
    char_change_ratio: float = 0.0
    changed_text_elements: int = 0
    changed_text_ratio: float = 0.0
    avg_text_edit_ratio: float = 0.0
    token_error_rate: float | None = None
    protected_term_violations: list[dict] = field(default_factory=list)
    numeric_mismatches: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source_chars": self.source_chars,
            "output_chars": self.output_chars,
            "char_change_ratio": round(self.char_change_ratio, 4),
            "changed_text_elements": self.changed_text_elements,
            "changed_text_ratio": round(self.changed_text_ratio, 4),
            "avg_text_edit_ratio": round(self.avg_text_edit_ratio, 4),
            "token_error_rate": round(self.token_error_rate, 4) if self.token_error_rate is not None else None,
            "protected_term_violations": self.protected_term_violations,
            "numeric_mismatches": self.numeric_mismatches,
        }


@dataclass
class LayoutRiskMetrics:
    text_elements: int = 0
    text_overflow_risks: int = 0
    text_overflow_risk_ratio: float = 0.0
    overlap_pairs: int = 0
    overlap_pair_ratio: float = 0.0
    overflow_details: list[dict] = field(default_factory=list)
    overlap_details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text_elements": self.text_elements,
            "text_overflow_risks": self.text_overflow_risks,
            "text_overflow_risk_ratio": round(self.text_overflow_risk_ratio, 4),
            "overlap_pairs": self.overlap_pairs,
            "overlap_pair_ratio": round(self.overlap_pair_ratio, 4),
            "overflow_details": self.overflow_details,
            "overlap_details": self.overlap_details,
        }


@dataclass
class EvalReport:
    page_metrics: list[PageMetrics] = field(default_factory=list)
    ssim_mean: float = 0.0
    psnr_mean: float = 0.0
    # 往返版面 IoU：None 表示无法独立测量（如缺 LibreOffice），绝不伪造
    layout_iou_mean: float | None = None
    layout_match_rate: float | None = None
    layout_iou_details: list = field(default_factory=list)
    cer: float | None = None
    token_error_rate: float | None = None
    editability_ratio: float = 0.0
    text_quality: TextQualityMetrics = field(default_factory=TextQualityMetrics)
    layout_risk: LayoutRiskMetrics = field(default_factory=LayoutRiskMetrics)
    visual_reliable: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ssim_mean": round(self.ssim_mean, 4),
            "psnr_mean": round(self.psnr_mean, 2),
            "layout_iou_mean": round(self.layout_iou_mean, 4) if self.layout_iou_mean is not None else None,
            "layout_match_rate": round(self.layout_match_rate, 4) if self.layout_match_rate is not None else None,
            "cer": round(self.cer, 4) if self.cer is not None else None,
            "token_error_rate": round(self.token_error_rate, 4) if self.token_error_rate is not None else None,
            "editability_ratio": round(self.editability_ratio, 4),
            "text_quality": self.text_quality.to_dict(),
            "layout_risk": self.layout_risk.to_dict(),
            "visual_reliable": self.visual_reliable,
            "pages": [
                {
                    "page": p.page_no,
                    "ssim": round(p.ssim, 4),
                    "psnr": round(p.psnr, 2),
                    "text_overflow_risks": p.text_overflow_risks,
                    "overlap_pairs": p.overlap_pairs,
                }
                for p in self.page_metrics
            ],
            "notes": self.notes,
        }


def _load_and_resize(path: Path, target_size: tuple[int, int]) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    img = img.resize(target_size, Image.Resampling.LANCZOS)
    return np.asarray(img)


def compute_ssim_psnr(img_a: np.ndarray, img_b: np.ndarray) -> tuple[float, float]:
    ssim = structural_similarity(img_a, img_b, channel_axis=2, data_range=255)
    psnr = peak_signal_noise_ratio(img_a, img_b, data_range=255)
    return float(ssim), float(psnr)


def compute_cer(reference: str, hypothesis: str) -> float:
    try:
        import jiwer

        return float(jiwer.cer(reference, hypothesis))
    except Exception:
        if not reference:
            return 0.0 if not hypothesis else 1.0
        # 简易 fallback
        matches = sum(1 for a, b in zip(reference, hypothesis) if a == b)
        return 1.0 - matches / max(len(reference), len(hypothesis))


def _normalize_for_distance(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def _levenshtein_distance(a, b) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, start=1):
            old = dp[j]
            if ca == cb:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = old
    return dp[-1]


def _edit_ratio(original: str, output: str) -> float:
    original = _normalize_for_distance(original)
    output = _normalize_for_distance(output)
    if not original:
        return 1.0 if output else 0.0
    return _levenshtein_distance(original, output) / len(original)


def _tokenize_mixed(text: str) -> list[str]:
    """Tokenize Chinese as characters and keep Latin words/numbers as tokens."""
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_\-]*|\d+(?:\.\d+)?%?|[\u4e00-\u9fff]", text):
        tokens.append(match.group(0).lower())
    return tokens


def compute_token_error_rate(reference: str, hypothesis: str) -> float:
    ref_tokens = _tokenize_mixed(reference)
    hyp_tokens = _tokenize_mixed(hypothesis)
    if not ref_tokens:
        return 0.0 if not hyp_tokens else 1.0
    return _levenshtein_distance(ref_tokens, hyp_tokens) / len(ref_tokens)


def _extract_numbers(text: str) -> list[str]:
    return re.findall(r"[-+]?\d+(?:\.\d+)?%?", text)


def _visual_text_width(text: str, font_px: float) -> float:
    width = 0.0
    for ch in text:
        if ch.isspace():
            width += font_px * 0.35
        elif ord(ch) > 0x2E80:
            width += font_px
        else:
            width += font_px * 0.55
    return width


def _estimate_text_overflow(elem) -> tuple[bool, float]:
    text = elem.final_text.strip()
    if not text or elem.bbox.width <= 1 or elem.bbox.height <= 1:
        return False, 0.0
    font_px = float(elem.font_size_hint or max(8.0, elem.bbox.height * 0.75))
    font_px = min(font_px, max(8.0, elem.bbox.height * 0.95))
    available_w = max(1.0, elem.bbox.width * 0.92)
    lines = max(1.0, np.ceil(_visual_text_width(text, font_px) / available_w))
    required_h = lines * font_px * 1.25
    ratio = required_h / max(1.0, elem.bbox.height)
    return ratio > 1.18, float(ratio)


def compute_text_quality(slide_ir: SlideIR, ground_truth_text: str | None = None) -> TextQualityMetrics:
    elements = slide_ir.all_text_elements()
    source_text = "\n".join(e.text for e in elements)
    output_text = "\n".join(e.final_text for e in elements)
    source_norm = _normalize_for_distance(source_text)
    output_norm = _normalize_for_distance(output_text)

    metric = TextQualityMetrics(
        source_chars=len(source_norm),
        output_chars=len(output_norm),
    )
    if source_norm:
        metric.char_change_ratio = _levenshtein_distance(source_norm, output_norm) / len(source_norm)

    edit_ratios: list[float] = []
    for elem in elements:
        ratio = _edit_ratio(elem.text, elem.final_text)
        edit_ratios.append(ratio)
        if ratio > 0:
            metric.changed_text_elements += 1

        original_nums = _extract_numbers(elem.text)
        output_nums = _extract_numbers(elem.final_text)
        if original_nums != output_nums:
            metric.numeric_mismatches.append(
                {
                    "page": elem.page_no,
                    "element_id": elem.id,
                    "original_numbers": original_nums,
                    "output_numbers": output_nums,
                    "text": elem.final_text[:80],
                }
            )

    if elements:
        metric.changed_text_ratio = metric.changed_text_elements / len(elements)
    if edit_ratios:
        metric.avg_text_edit_ratio = float(np.mean(edit_ratios))

    for term in slide_ir.protected_terms:
        if not term:
            continue
        if term in source_text and term not in output_text:
            metric.protected_term_violations.append({"term": term})

    if ground_truth_text:
        metric.token_error_rate = compute_token_error_rate(ground_truth_text, output_text)
    return metric


def compute_layout_risk(slide_ir: SlideIR) -> tuple[LayoutRiskMetrics, dict[int, tuple[int, int]]]:
    metric = LayoutRiskMetrics()
    page_counts: dict[int, tuple[int, int]] = {}

    for page in slide_ir.pages:
        text_elements = page.text_elements()
        metric.text_elements += len(text_elements)
        overflow_count = 0
        overlap_count = 0

        for elem in text_elements:
            overflow, ratio = _estimate_text_overflow(elem)
            if overflow:
                overflow_count += 1
                if len(metric.overflow_details) < 30:
                    metric.overflow_details.append(
                        {
                            "page": elem.page_no,
                            "element_id": elem.id,
                            "ratio": round(ratio, 3),
                            "text": elem.final_text[:80],
                        }
                    )

        for i, a in enumerate(text_elements):
            for b in text_elements[i + 1 :]:
                iou = a.bbox.iou(b.bbox)
                if iou > 0.03:
                    overlap_count += 1
                    if len(metric.overlap_details) < 30:
                        metric.overlap_details.append(
                            {
                                "page": page.page_no,
                                "a": a.id,
                                "b": b.id,
                                "iou": round(iou, 3),
                            }
                        )

        metric.text_overflow_risks += overflow_count
        metric.overlap_pairs += overlap_count
        page_counts[page.page_no] = (overflow_count, overlap_count)

    if metric.text_elements:
        metric.text_overflow_risk_ratio = metric.text_overflow_risks / metric.text_elements
    possible_pairs = sum(max(0, len(p.text_elements()) * (len(p.text_elements()) - 1) // 2) for p in slide_ir.pages)
    if possible_pairs:
        metric.overlap_pair_ratio = metric.overlap_pairs / possible_pairs
    return metric, page_counts


def evaluate_conversion(
    slide_ir: SlideIR,
    source_page_images: dict[int, Path],
    output_page_images: list[Path],
    ground_truth_text: str | None = None,
    visual_reliable: bool = True,
    output_pdf: str | Path | None = None,
) -> EvalReport:
    """对比原 PDF 渲染图与输出 PPT 渲染图.

    visual_reliable=False 表示 PPT 渲染图为占位图（无 LibreOffice），
    此时 SSIM/PSNR 不反映真实视觉保真度，仅作占位，报告中明确标注不可信。

    output_pdf: 由 PPTX 经 LibreOffice 渲染回的 PDF，用于独立计算往返版面 IoU。
    为 None（缺 LibreOffice）时 layout_iou_mean 保持 None，绝不伪造数值。
    """
    report = EvalReport()
    report.visual_reliable = visual_reliable
    page_ssims: list[float] = []
    page_psnrs: list[float] = []

    sorted_pages = sorted(slide_ir.pages, key=lambda p: p.page_no)
    for i, page in enumerate(sorted_pages):
        src_path = source_page_images.get(page.page_no)
        if not src_path or not Path(src_path).exists():
            continue
        out_idx = min(i, len(output_page_images) - 1)
        if out_idx < 0 or not output_page_images:
            break
        out_path = output_page_images[out_idx]
        if not out_path.exists():
            continue

        src_img = Image.open(src_path)
        target_size = src_img.size
        arr_a = _load_and_resize(Path(src_path), target_size)
        arr_b = _load_and_resize(out_path, target_size)
        ssim, psnr = compute_ssim_psnr(arr_a, arr_b)
        page_ssims.append(ssim)
        page_psnrs.append(psnr)
        report.page_metrics.append(PageMetrics(page_no=page.page_no, ssim=ssim, psnr=psnr))

    if page_ssims:
        report.ssim_mean = float(np.mean(page_ssims))
        report.psnr_mean = float(np.mean(page_psnrs))

    report.text_quality = compute_text_quality(slide_ir, ground_truth_text)
    report.token_error_rate = report.text_quality.token_error_rate
    report.layout_risk, layout_page_counts = compute_layout_risk(slide_ir)
    metrics_by_page = {p.page_no: p for p in report.page_metrics}
    for page in sorted_pages:
        pm = metrics_by_page.get(page.page_no)
        if pm is None:
            pm = PageMetrics(page_no=page.page_no)
            report.page_metrics.append(pm)
            metrics_by_page[page.page_no] = pm
        overflow_count, overlap_count = layout_page_counts.get(page.page_no, (0, 0))
        pm.text_overflow_risks = overflow_count
        pm.overlap_pairs = overlap_count

    # 往返版面 IoU：独立重解析渲染后的 PDF，绝不伪造
    from ppt_enhance.eval.layout_iou import compute_layout_iou

    iou_mean, match_rate, iou_details = compute_layout_iou(slide_ir, output_pdf)
    report.layout_iou_mean = iou_mean
    report.layout_match_rate = match_rate
    report.layout_iou_details = iou_details
    if iou_mean is not None:
        for pm in report.page_metrics:
            pm.bbox_iou_mean = iou_mean  # 页级暂用全局均值占位（明细见 layout_iou_details）

    # 可编辑性：文本元素占比
    total = sum(len(p.elements) for p in slide_ir.pages)
    textual = sum(len(p.text_elements()) for p in slide_ir.pages)
    report.editability_ratio = textual / total if total else 0.0

    # CER（若提供 ground truth）
    if ground_truth_text:
        output_text = "\n".join(e.final_text for e in slide_ir.all_text_elements())
        report.cer = compute_cer(ground_truth_text, output_text)

    if report.text_quality.protected_term_violations:
        report.notes.append(
            f"专有名词保护风险：{len(report.text_quality.protected_term_violations)} 个受保护术语在输出中缺失。"
        )
    if report.text_quality.numeric_mismatches:
        report.notes.append(
            f"数字保护风险：{len(report.text_quality.numeric_mismatches)} 个文本元素的数字发生变化。"
        )
    if report.layout_risk.text_overflow_risks:
        report.notes.append(
            f"文本框溢出风险：{report.layout_risk.text_overflow_risks}/{report.layout_risk.text_elements} "
            f"个文本元素可能需要缩小字号或调整框高。"
        )
    if report.layout_risk.overlap_pairs:
        report.notes.append(f"元素重叠风险：检测到 {report.layout_risk.overlap_pairs} 对文本框存在明显重叠。")

    if not output_page_images:
        report.notes.append("未能渲染 PPTX 页面图，SSIM 未计算。请安装 LibreOffice 以启用完整评测。")
    elif not visual_reliable:
        report.notes.append(
            "⚠️ 未检测到 LibreOffice，PPTX 渲染回退为占位图。"
            "SSIM/PSNR 仅为占位数值，不反映真实视觉保真度，请勿用于报告结论。"
            "安装 LibreOffice 后重跑可获得可信视觉指标。"
        )

    if report.layout_iou_mean is None:
        report.notes.append(
            "版面 IoU 未计算：需 LibreOffice 将 PPTX 渲染回 PDF 后独立重解析。"
            "本指标绝不使用写死的占位值——无法独立测量时即为 None。"
        )
    else:
        report.notes.append(
            f"版面 IoU 为往返独立测量：PPTX→PDF→重新检测文本框坐标，"
            f"匹配回源元素后计算真实 IoU；文本找回率 {report.layout_match_rate:.1%}。"
        )

    return report
