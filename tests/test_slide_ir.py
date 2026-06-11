from ppt_enhance.schemas.slide_ir import BBox, ElementType, SlideElement, SlideIR, SlidePage


def test_bbox_iou():
    a = BBox(x0=0, y0=0, x1=100, y1=100)
    b = BBox(x0=50, y0=50, x1=150, y1=150)
    assert 0.14 < a.iou(b) < 0.15


def test_apply_corrections():
    elem = SlideElement(
        id="e1",
        type=ElementType.TEXT,
        text="学刁",
        bbox=BBox(x0=0, y0=0, x1=100, y1=30),
        page_no=1,
    )
    ir = SlideIR(
        source_pdf="test.pdf",
        pages=[SlidePage(page_no=1, width=960, height=540, elements=[elem])],
    )
    ir.apply_corrections({"e1": "学习"})
    assert elem.final_text == "学习"
