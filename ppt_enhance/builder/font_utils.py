"""字体与文本框尺寸工具."""

from __future__ import annotations

from pptx.util import Pt


def estimate_font_size(bbox_height: float, line_count: int = 1, min_pt: float = 8.0) -> float:
    """根据 bbox 高度估算字号（磅）."""
    if line_count <= 1:
        pt = bbox_height * 0.75 * 0.75  # px → pt 近似
    else:
        pt = (bbox_height / line_count) * 0.75 * 0.75
    return max(min_pt, pt)


def pt_to_ppt(pt: float) -> Pt:
    return Pt(pt)
