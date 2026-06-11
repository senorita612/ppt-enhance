"""SlideIR: 幻灯片中间表示（内容与版式解耦的核心数据结构）."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ElementType(str, Enum):
    TITLE = "title"
    TEXT = "text"
    LIST = "list"
    TABLE = "table"
    IMAGE = "image"
    CAPTION = "caption"
    FOOTER = "footer"
    OTHER = "other"


class CorrectionType(str, Enum):
    """修正类别，决定走哪套审查阈值。

    OCR_FIX 保守（只改错字、不动原意），FLUENCY 允许改写（去 AI 腔、顺语序）。
    两者哲学相反，故分类标注、分别审查。
    """

    OCR_FIX = "ocr_fix"
    FLUENCY = "fluency"


class BBox(BaseModel):
    """边界框，坐标系为 PDF 页面左上角原点，单位像素（渲染 DPI 下）."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    def iou(self, other: BBox) -> float:
        ix0 = max(self.x0, other.x0)
        iy0 = max(self.y0, other.y0)
        ix1 = min(self.x1, other.x1)
        iy1 = min(self.y1, other.y1)
        inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def to_relative(self, page_width: float, page_height: float) -> tuple[float, float, float, float]:
        """转为相对坐标 (left, top, width, height)，范围 0~1."""
        return (
            self.x0 / page_width,
            self.y0 / page_height,
            self.width / page_width,
            self.height / page_height,
        )


class SlideElement(BaseModel):
    id: str
    type: ElementType = ElementType.TEXT
    text: str = ""
    corrected_text: str | None = None
    bbox: BBox
    page_no: int
    image_path: str | None = None
    font_size_hint: float | None = None
    text_color: str | None = None  # 文字颜色，十六进制如 "#FFFFFF"；None 时回退黑色
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def final_text(self) -> str:
        return self.corrected_text if self.corrected_text is not None else self.text

    @property
    def is_textual(self) -> bool:
        return self.type in {
            ElementType.TITLE,
            ElementType.TEXT,
            ElementType.LIST,
            ElementType.CAPTION,
            ElementType.FOOTER,
        }


class SlidePage(BaseModel):
    page_no: int
    width: float
    height: float
    elements: list[SlideElement] = Field(default_factory=list)
    render_path: str | None = None
    background_color: str | None = None  # 背景主色，十六进制；None 时白底
    background_image: str | None = None  # 去除文字后的背景图（含装饰/渐变），可选

    def text_elements(self) -> list[SlideElement]:
        return [e for e in self.elements if e.is_textual and e.text.strip()]


class SlideIR(BaseModel):
    source_pdf: str
    parser: str = "docling"
    dpi: int = 150
    pages: list[SlidePage] = Field(default_factory=list)
    protected_terms: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> SlideIR:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(data)

    def all_text_elements(self) -> list[SlideElement]:
        return [e for p in self.pages for e in p.text_elements()]

    def apply_corrections(self, corrections: dict[str, str]) -> None:
        for page in self.pages:
            for elem in page.elements:
                if elem.id in corrections:
                    elem.corrected_text = corrections[elem.id]
