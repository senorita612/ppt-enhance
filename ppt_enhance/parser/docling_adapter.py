"""Docling 解析适配器: PDF → SlideIR."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

from ppt_enhance.parser.pdf_renderer import get_page_size, render_pdf_pages
from ppt_enhance.schemas.slide_ir import BBox, ElementType, SlideElement, SlideIR, SlidePage


_LABEL_MAP: dict[str, ElementType] = {
    "title": ElementType.TITLE,
    "section_header": ElementType.TITLE,
    "heading": ElementType.TITLE,
    "paragraph": ElementType.TEXT,
    "text": ElementType.TEXT,
    "list_item": ElementType.LIST,
    "caption": ElementType.CAPTION,
    "footnote": ElementType.FOOTER,
    "page_footer": ElementType.FOOTER,
    "page_header": ElementType.FOOTER,
    "table": ElementType.TABLE,
    "picture": ElementType.IMAGE,
    "figure": ElementType.IMAGE,
}


def _map_label(label: str | None) -> ElementType:
    if not label:
        return ElementType.TEXT
    key = str(label).lower().replace("-", "_")
    return _LABEL_MAP.get(key, ElementType.OTHER)


def _bbox_from_prov(prov, page_sizes: dict[int, tuple[float, float]], dpi: int) -> BBox | None:
    """将 Docling provenance bbox 转为像素坐标（左上角原点）.

    Docling 的 BoundingBox 常用 **左下角原点**（PDF 坐标系，y 向上，t>b）。
    必须翻转 y 轴到屏幕坐标系（左上角原点，y 向下），否则 y1-y0 为负、
    被 max(0,…) 夹成 0，导致：文本框零高度、字号恒为下限、垂直位置颠倒。
    """
    if prov is None or not hasattr(prov, "bbox"):
        return None
    bbox = prov.bbox
    page_no = getattr(prov, "page_no", 1) or 1
    page_w, page_h = page_sizes.get(page_no, (1920, 1080))  # 像素，DPI 下

    l, t, r, b = float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)

    # 判定坐标原点：优先用 Docling 的 coord_origin，回退到 t>b 启发式
    coord_origin = getattr(bbox, "coord_origin", None)
    if coord_origin is not None:
        is_bottom_left = str(coord_origin).upper().endswith("BOTTOMLEFT")
    else:
        is_bottom_left = t > b

    if max(abs(l), abs(t), abs(r), abs(b)) <= 1.5:
        # 归一化 0~1 坐标
        if is_bottom_left:
            ty, by = 1.0 - t, 1.0 - b
        else:
            ty, by = t, b
        return BBox(
            x0=l * page_w,
            y0=min(ty, by) * page_h,
            x1=r * page_w,
            y1=max(ty, by) * page_h,
        )

    # point 坐标（72 DPI）→ 渲染像素
    scale = dpi / 72.0
    page_h_pts = page_h / scale if scale else page_h
    if is_bottom_left:
        ty = page_h_pts - t
        by = page_h_pts - b
    else:
        ty, by = t, b
    return BBox(
        x0=l * scale,
        y0=min(ty, by) * scale,
        x1=r * scale,
        y1=max(ty, by) * scale,
    )


def _extract_protected_terms(texts: list[str]) -> list[str]:
    """从文本中抽取可能的专有名词（大写词组、中英文混合词）."""
    terms: set[str] = set()
    for text in texts:
        for m in re.finditer(r"[A-Z][A-Za-z0-9\-]{2,}", text):
            terms.add(m.group())
        for m in re.finditer(r"[\u4e00-\u9fff]{2,4}(?:模型|算法|框架|系统|平台|网络|因子)", text):
            # 仅收录紧凑术语；OCR 截断碎片（如"捉的系统"）因后缀前非连续 2~4 汉字而被排除
            terms.add(m.group())
    return sorted(terms)[:50]


def parse_with_docling(
    pdf_path: str | Path,
    work_dir: str | Path,
    dpi: int = 150,
    enable_ocr: bool = False,
) -> SlideIR:
    """使用 Docling 将 PDF 解析为 SlideIR.

    enable_ocr=False（默认）: 直接读取 PDF 矢量文本，无需联网下载 OCR 模型，
    适用于 NotebookLM 等数字原生 PDF；速度快、可离线、可复现。
    enable_ocr=True: 对扫描件启用 OCR（需联网下载模型）。
    """
    pdf_path = Path(pdf_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    render_dir = work_dir / "renders"
    page_images = render_pdf_pages(pdf_path, render_dir, dpi=dpi)
    page_sizes = get_page_size(pdf_path, dpi=dpi)

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = enable_ocr
    pipeline_options.do_table_structure = True
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )
    result = converter.convert(str(pdf_path))
    doc = result.document

    pages_dict: dict[int, SlidePage] = {}
    for page_no, (w, h) in page_sizes.items():
        pages_dict[page_no] = SlidePage(
            page_no=page_no,
            width=w,
            height=h,
            render_path=str(page_images[page_no]),
            elements=[],
        )

    all_texts: list[str] = []

    # 文本元素
    for item in getattr(doc, "texts", []) or []:
        text = getattr(item, "text", "") or ""
        if not text.strip():
            continue
        label = getattr(item, "label", None)
        elem_type = _map_label(str(label) if label else None)
        prov_list = getattr(item, "prov", []) or []
        if not prov_list:
            continue
        prov = prov_list[0]
        page_no = getattr(prov, "page_no", 1) or 1
        bbox = _bbox_from_prov(prov, page_sizes, dpi)
        if bbox is None or page_no not in pages_dict:
            continue
        all_texts.append(text)
        pages_dict[page_no].elements.append(
            SlideElement(
                id=f"txt_{uuid.uuid4().hex[:8]}",
                type=elem_type,
                text=text.strip(),
                bbox=bbox,
                page_no=page_no,
                font_size_hint=max(8.0, bbox.height * 0.75),
            )
        )

    # 图片元素
    pictures_dir = work_dir / "pictures"
    pictures_dir.mkdir(exist_ok=True)
    for idx, item in enumerate(getattr(doc, "pictures", []) or []):
        prov_list = getattr(item, "prov", []) or []
        if not prov_list:
            continue
        prov = prov_list[0]
        page_no = getattr(prov, "page_no", 1) or 1
        bbox = _bbox_from_prov(prov, page_sizes, dpi)
        if bbox is None or page_no not in pages_dict:
            continue
        page = pages_dict[page_no]
        if page.render_path:
            from ppt_enhance.parser.pdf_renderer import crop_region

            crop_path = pictures_dir / f"pic_p{page_no}_{idx}.png"
            crop_region(page.render_path, (bbox.x0, bbox.y0, bbox.x1, bbox.y1), crop_path)
            page.elements.append(
                SlideElement(
                    id=f"img_{uuid.uuid4().hex[:8]}",
                    type=ElementType.IMAGE,
                    bbox=bbox,
                    page_no=page_no,
                    image_path=str(crop_path),
                )
            )

    pages = [pages_dict[k] for k in sorted(pages_dict)]
    return SlideIR(
        source_pdf=str(pdf_path.resolve()),
        parser="docling",
        dpi=dpi,
        pages=pages,
        protected_terms=_extract_protected_terms(all_texts),
        metadata={"element_count": sum(len(p.elements) for p in pages)},
    )
