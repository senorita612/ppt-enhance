import numpy as np

from ppt_enhance.eval.metrics import (
    compute_cer,
    compute_layout_risk,
    compute_ssim_psnr,
    compute_text_quality,
    compute_token_error_rate,
)
from ppt_enhance.schemas.slide_ir import BBox, ElementType, SlideElement, SlideIR, SlidePage


def test_ssim_identical():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    ssim, psnr = compute_ssim_psnr(img, img)
    assert ssim == 1.0
    assert psnr == float("inf")


def test_cer():
    assert compute_cer("深度学习", "深度学习") == 0.0
    assert compute_cer("学习", "学刁") > 0


def test_token_error_rate_mixed_chinese_english():
    assert compute_token_error_rate("Transformer 深度学习 95.3%", "Transformer 深度学习 95.3%") == 0.0
    assert compute_token_error_rate("深度学习", "深度学刁") > 0


def test_text_quality_protection_checks():
    elem = SlideElement(
        id="e1",
        type=ElementType.TEXT,
        text="Transformer 在 2017 年提出",
        corrected_text="模型 在 年提出",
        bbox=BBox(x0=0, y0=0, x1=300, y1=40),
        page_no=1,
    )
    ir = SlideIR(
        source_pdf="sample.pdf",
        pages=[SlidePage(page_no=1, width=960, height=540, elements=[elem])],
        protected_terms=["Transformer"],
    )

    metric = compute_text_quality(ir)
    assert metric.changed_text_elements == 1
    assert metric.protected_term_violations == [{"term": "Transformer"}]
    assert metric.numeric_mismatches[0]["original_numbers"] == ["2017"]


def test_layout_risk_detects_overflow():
    elem = SlideElement(
        id="e1",
        type=ElementType.TEXT,
        text="这是一段非常非常非常非常非常非常非常非常长的文本",
        bbox=BBox(x0=0, y0=0, x1=80, y1=20),
        page_no=1,
        font_size_hint=18,
    )
    ir = SlideIR(
        source_pdf="sample.pdf",
        pages=[SlidePage(page_no=1, width=960, height=540, elements=[elem])],
    )

    metric, page_counts = compute_layout_risk(ir)
    assert metric.text_overflow_risks == 1
    assert page_counts[1][0] == 1
