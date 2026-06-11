"""MinerU JSON 解析适配器（兼容 NotebookLM2PPT 格式）."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ppt_enhance.parser.pdf_renderer import get_page_size, render_pdf_pages
from ppt_enhance.schemas.slide_ir import BBox, ElementType, SlideElement, SlideIR, SlidePage


_TYPE_MAP = {
    "title": ElementType.TITLE,
    "text": ElementType.TEXT,
    "list": ElementType.LIST,
    "table": ElementType.TABLE,
    "image": ElementType.IMAGE,
    "figure": ElementType.IMAGE,
}


def _parse_bbox(block: dict, page_w: float, page_h: float) -> BBox | None:
    bbox = block.get("bbox") or block.get("box")
    if not bbox or len(bbox) < 4:
        return None
    x0, y0, x1, y1 = map(float, bbox[:4])
    # MinerU 通常用 PDF 点坐标，需按页面尺寸缩放
    if x1 <= 2 and y1 <= 2:
        return BBox(x0=x0 * page_w, y0=y0 * page_h, x1=x1 * page_w, y1=y1 * page_h)
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _extract_blocks(page_data: dict) -> list[dict]:
    blocks: list[dict] = []
    for key in ("para_blocks", "discarded_blocks", "preproc_blocks"):
        blocks.extend(page_data.get(key, []) or [])
    return blocks


def parse_with_mineru(
    pdf_path: str | Path,
    mineru_json_path: str | Path,
    work_dir: str | Path,
    dpi: int = 150,
) -> SlideIR:
    """从 MinerU JSON 构建 SlideIR."""
    pdf_path = Path(pdf_path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(mineru_json_path).read_text(encoding="utf-8"))
    pdf_info = data.get("pdf_info") or data.get("pages") or []
    if isinstance(pdf_info, dict):
        pdf_info = pdf_info.get("pages", [])

    render_dir = work_dir / "renders"
    page_images = render_pdf_pages(pdf_path, render_dir, dpi=dpi)
    page_sizes = get_page_size(pdf_path, dpi=dpi)

    pages: list[SlidePage] = []
    all_texts: list[str] = []

    for i, page_data in enumerate(pdf_info):
        page_no = page_data.get("page_idx", i) + 1
        pw, ph = page_sizes.get(page_no, (1920, 1080))
        slide_page = SlidePage(
            page_no=page_no,
            width=pw,
            height=ph,
            render_path=str(page_images.get(page_no, "")),
            elements=[],
        )

        for block in _extract_blocks(page_data):
            block_type = str(block.get("type", "text")).lower()
            elem_type = _TYPE_MAP.get(block_type, ElementType.TEXT)
            bbox = _parse_bbox(block, pw, ph)
            if bbox is None:
                continue

            text = ""
            for line in block.get("lines", []) or []:
                for span in line.get("spans", []) or []:
                    text += span.get("content", "") or span.get("text", "")
            text = text.strip()

            if elem_type == ElementType.IMAGE:
                from ppt_enhance.parser.pdf_renderer import crop_region

                pictures_dir = work_dir / "pictures"
                pictures_dir.mkdir(exist_ok=True)
                crop_path = pictures_dir / f"mineru_p{page_no}_{uuid.uuid4().hex[:6]}.png"
                if slide_page.render_path:
                    crop_region(slide_page.render_path, (bbox.x0, bbox.y0, bbox.x1, bbox.y1), crop_path)
                slide_page.elements.append(
                    SlideElement(
                        id=f"img_{uuid.uuid4().hex[:8]}",
                        type=ElementType.IMAGE,
                        bbox=bbox,
                        page_no=page_no,
                        image_path=str(crop_path),
                    )
                )
            elif text:
                all_texts.append(text)
                slide_page.elements.append(
                    SlideElement(
                        id=f"txt_{uuid.uuid4().hex[:8]}",
                        type=elem_type,
                        text=text,
                        bbox=bbox,
                        page_no=page_no,
                        font_size_hint=max(8.0, bbox.height * 0.75),
                    )
                )

        pages.append(slide_page)

    return SlideIR(
        source_pdf=str(pdf_path.resolve()),
        parser="mineru",
        dpi=dpi,
        pages=pages,
        protected_terms=[],
        metadata={"mineru_json": str(mineru_json_path)},
    )
