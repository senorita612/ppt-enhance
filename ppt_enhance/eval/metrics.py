"""转换质量评测: SSIM / PSNR / IoU / CER."""

from __future__ import annotations

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
    editability_ratio: float = 0.0
    visual_reliable: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ssim_mean": round(self.ssim_mean, 4),
            "psnr_mean": round(self.psnr_mean, 2),
            "layout_iou_mean": round(self.layout_iou_mean, 4) if self.layout_iou_mean is not None else None,
            "layout_match_rate": round(self.layout_match_rate, 4) if self.layout_match_rate is not None else None,
            "cer": round(self.cer, 4) if self.cer is not None else None,
            "editability_ratio": round(self.editability_ratio, 4),
            "visual_reliable": self.visual_reliable,
            "pages": [
                {"page": p.page_no, "ssim": round(p.ssim, 4), "psnr": round(p.psnr, 2)}
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
