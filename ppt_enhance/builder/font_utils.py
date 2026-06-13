"""字体与文本框尺寸工具."""

from __future__ import annotations

import sys

from pptx.oxml.ns import qn
from pptx.util import Pt


_PLATFORM_CJK_DEFAULTS = {"PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC"}


def default_cjk_font() -> str:
    """Return a Chinese font name that is normally available on this platform."""
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform.startswith("win"):
        return "Microsoft YaHei"
    return "Noto Sans CJK SC"


def resolve_cjk_font(font_name: str | None = None) -> str:
    """Resolve stale platform defaults to the current platform's CJK font."""
    if not font_name or font_name in _PLATFORM_CJK_DEFAULTS:
        return default_cjk_font()
    return font_name


def set_run_cjk_font(run, font_name: str | None = None) -> str:
    """Set Latin, complex-script, and East Asian font hints for a PPT run.

    PowerPoint and LibreOffice can ignore ``run.font.name`` for CJK text unless
    the DrawingML eastAsia font slot is also populated. This helper writes both.
    """
    name = resolve_cjk_font(font_name)
    run.font.name = name
    try:
        r_pr = run._r.get_or_add_rPr()
        for tag in ("a:latin", "a:ea", "a:cs"):
            node = r_pr.find(qn(tag))
            if node is None:
                node = r_pr.makeelement(qn(tag), {})
                r_pr.append(node)
            node.set("typeface", name)
    except Exception:
        pass
    return name


def set_paragraph_cjk_font(paragraph, font_name: str | None = None) -> str:
    """Set paragraph default font and all existing runs to a CJK-safe font."""
    name = resolve_cjk_font(font_name)
    paragraph.font.name = name
    for run in paragraph.runs:
        set_run_cjk_font(run, name)
    return name


def estimate_font_size(bbox_height: float, line_count: int = 1, min_pt: float = 8.0) -> float:
    """根据 bbox 高度估算字号（磅）."""
    if line_count <= 1:
        pt = bbox_height * 0.75 * 0.75  # px → pt 近似
    else:
        pt = (bbox_height / line_count) * 0.75 * 0.75
    return max(min_pt, pt)


def pt_to_ppt(pt: float) -> Pt:
    return Pt(pt)
