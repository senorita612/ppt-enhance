"""图层提取器：从纯图片页面分离出「无字背景版」+ 文字色。

之前用连通块抓装饰块的方法是错的——文字本身也是前景，会被一起裁进装饰块，
导致重建时「原图文字 + 可编辑文字」双重重影。

正确做法（业界标准）：文字擦除 inpainting。
1. 用所有文字 bbox 构建掩膜，cv2.inpaint 把文字像素抹掉、用周围颜色填充。
   → 得到「无字背景版」：框线/箭头/圆环/渐变/插画全部保留，唯独没有文字。
2. 文字色：每个文字框内取与局部背景对比最大的颜色（笔画色）。
重建时：无字背景版整页铺底（作为背景层）+ 可编辑文字叠上层（采样色）。
删掉某个文本框，露出的是干净的框，而非原始像素文字——真正可编辑。

仅依赖 numpy + opencv + PIL，全部已是项目依赖。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ppt_enhance.schemas.slide_ir import BBox, SlidePage


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{int(r):02X}{int(g):02X}{int(b):02X}"


def _build_text_mask(shape: tuple[int, int], elements, pad: int = 6) -> np.ndarray:
    """所有文字框标 255 的掩膜（供 inpaint 使用）。"""
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for e in elements:
        if not e.is_textual:
            continue
        x0 = max(0, int(e.bbox.x0) - pad)
        y0 = max(0, int(e.bbox.y0) - pad)
        x1 = min(w, int(e.bbox.x1) + pad)
        y1 = min(h, int(e.bbox.y1) + pad)
        mask[y0:y1, x0:x1] = 255
    return mask


def _sample_background_color(img_rgb: np.ndarray, text_mask: np.ndarray) -> str:
    """非文字区域主色（中位数），作为纯色背景回退。"""
    bg_pixels = img_rgb[text_mask == 0]
    if bg_pixels.size == 0:
        bg_pixels = img_rgb.reshape(-1, 3)
    med = np.median(bg_pixels, axis=0)
    return _hex((med[0], med[1], med[2]))


def _sample_text_color(img_rgb: np.ndarray, bbox: BBox, bg_rgb: tuple[int, int, int]) -> str:
    """文字框内取与背景对比最大的颜色作为笔画色。"""
    h, w = img_rgb.shape[:2]
    x0, y0 = max(0, int(bbox.x0)), max(0, int(bbox.y0))
    x1, y1 = min(w, int(bbox.x1)), min(h, int(bbox.y1))
    if x1 <= x0 or y1 <= y0:
        return "#000000"
    patch = img_rgb[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    bg = np.array(bg_rgb, dtype=np.float32)
    dist = np.linalg.norm(patch - bg, axis=1)
    if dist.max() < 30:
        return "#000000"
    thresh = np.percentile(dist, 80)
    stroke = patch[dist >= thresh]
    if stroke.size == 0:
        return "#000000"
    med = np.median(stroke, axis=0)
    return _hex((med[0], med[1], med[2]))


def _build_clean_background(
    img_rgb: np.ndarray, text_mask: np.ndarray, out_path: Path
) -> str:
    """用 inpaint 抹掉文字，保留装饰/渐变，得到无字背景版。"""
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    # Telea 算法，半径随分辨率适配
    radius = max(3, int(min(img_rgb.shape[:2]) / 300))
    clean = cv2.inpaint(bgr, text_mask, radius, cv2.INPAINT_TELEA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), clean)
    return str(out_path)


def enrich_page_layers(page: SlidePage, work_dir: str | Path) -> SlidePage:
    """为单页补全无字背景版、背景色、文字色（就地修改并返回）。"""
    if not page.render_path or not Path(page.render_path).exists():
        return page

    bgr = cv2.imread(page.render_path)
    if bgr is None:
        return page
    img_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    text_mask = _build_text_mask(img_rgb.shape, page.elements)

    # 背景纯色（回退用）
    bg_hex = _sample_background_color(img_rgb, text_mask)
    page.background_color = bg_hex
    bg_rgb = (int(bg_hex[1:3], 16), int(bg_hex[3:5], 16), int(bg_hex[5:7], 16))

    # 无字背景版（保留装饰）
    clean_dir = Path(work_dir) / "clean_bg"
    clean_path = clean_dir / f"clean_p{page.page_no:04d}.png"
    page.background_image = _build_clean_background(img_rgb, text_mask, clean_path)

    # 文字色
    for e in page.elements:
        if e.is_textual:
            e.text_color = _sample_text_color(img_rgb, e.bbox, bg_rgb)

    return page


def enrich_layers(slide_ir, work_dir: str | Path):
    """对整个 SlideIR 的每页补全无字背景版 + 颜色。"""
    for page in slide_ir.pages:
        enrich_page_layers(page, work_dir)
    return slide_ir
