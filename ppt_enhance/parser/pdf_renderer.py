"""PDF 页面渲染为 PNG，供视觉保真与图片裁剪使用."""

from __future__ import annotations

from pathlib import Path

import fitz
from PIL import Image


def render_pdf_pages(
    pdf_path: str | Path,
    output_dir: str | Path,
    dpi: int = 150,
) -> dict[int, Path]:
    """将 PDF 每页渲染为 PNG，返回 {page_no: png_path}."""
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_path)
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    page_images: dict[int, Path] = {}

    for i in range(len(doc)):
        page_no = i + 1
        out_path = output_dir / f"page_{page_no:04d}.png"
        if not out_path.exists():
            pix = doc[i].get_pixmap(matrix=matrix, alpha=False)
            pix.save(str(out_path))
        page_images[page_no] = out_path

    doc.close()
    return page_images


def get_page_size(pdf_path: str | Path, dpi: int = 150) -> dict[int, tuple[float, float]]:
    """获取每页渲染后的像素尺寸 (width, height)."""
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)
    scale = dpi / 72.0
    sizes: dict[int, tuple[float, float]] = {}
    for i in range(len(doc)):
        rect = doc[i].rect
        sizes[i + 1] = (rect.width * scale, rect.height * scale)
    doc.close()
    return sizes


def crop_region(
    image_path: str | Path,
    bbox: tuple[float, float, float, float],
    output_path: str | Path | None = None,
    padding: int = 2,
) -> Path:
    """从页面图中按 bbox 裁剪子区域."""
    image_path = Path(image_path)
    x0, y0, x1, y1 = bbox
    img = Image.open(image_path)
    w, h = img.size
    left = max(0, int(x0) - padding)
    top = max(0, int(y0) - padding)
    right = min(w, int(x1) + padding)
    bottom = min(h, int(y1) + padding)
    cropped = img.crop((left, top, right, bottom))
    if output_path is None:
        output_path = image_path.parent / f"crop_{left}_{top}_{right}_{bottom}.png"
    output_path = Path(output_path)
    cropped.save(output_path)
    return output_path
