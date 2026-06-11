"""检测框可视化: 把 Qwen-OCR 的文字定位框画回原图，用于人工核对坐标对齐。

参照百炼 draw_bbox.py：对每个文字行的四顶点 location 连线成框，并在框上方标注
识别文本，保存为 <原图名>_location.png。这是验证「VLM 输出坐标 ↔ 原图像素」是否
对齐的金标准——坐标错位会一眼看出。
"""

from __future__ import annotations

from pathlib import Path

import cv2

from ppt_enhance.schemas.slide_ir import SlidePage


def draw_page_boxes(
    page: SlidePage,
    output_path: str | Path | None = None,
    color: tuple[int, int, int] = (0, 0, 255),
    thickness: int = 2,
    label: bool = True,
) -> Path:
    """在页面渲染图上画出所有元素的 BBox，返回保存路径。

    color 为 BGR（OpenCV 约定），默认红色。
    """
    if not page.render_path:
        raise ValueError(f"page {page.page_no} 无 render_path，无法可视化")

    img = cv2.imread(page.render_path)
    if img is None:
        raise FileNotFoundError(f"无法读取渲染图: {page.render_path}")

    for elem in page.elements:
        b = elem.bbox
        p0 = (int(b.x0), int(b.y0))
        p1 = (int(b.x1), int(b.y1))
        cv2.rectangle(img, p0, p1, color, thickness)
        if label and elem.text:
            tag = elem.text[:12]
            cv2.putText(
                img,
                tag,
                (int(b.x0), max(0, int(b.y0) - 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                1,
                cv2.LINE_AA,
            )

    if output_path is None:
        src = Path(page.render_path)
        output_path = src.parent / f"{src.stem}_location{src.suffix}"
    output_path = Path(output_path)
    cv2.imwrite(str(output_path), img)
    return output_path


def draw_ir_boxes(slide_ir, output_dir: str | Path) -> list[Path]:
    """对 SlideIR 的每一页生成检测框可视化图，返回所有保存路径。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for page in slide_ir.pages:
        out = output_dir / f"page_{page.page_no:04d}_location.png"
        try:
            saved.append(draw_page_boxes(page, out))
        except (ValueError, FileNotFoundError):
            continue
    return saved
