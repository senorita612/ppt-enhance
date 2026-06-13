from ppt_enhance.agents.contributor import _rule_based_corrections
from ppt_enhance.agents.reviewer import review_corrections
from ppt_enhance.schemas.slide_ir import BBox, ElementType, SlideElement


def test_rule_based_correction():
    elem = SlideElement(
        id="e1",
        type=ElementType.TEXT,
        text="机器学刁与深渡学习",
        bbox=BBox(x0=0, y0=0, x1=200, y1=40),
        page_no=1,
    )
    corrections = _rule_based_corrections([elem])
    assert len(corrections) == 1
    assert "学习" in corrections[0]["corrected"]


def test_reviewer_rejects_large_edit():
    proposals = [{
        "id": "e1",
        "original": "短文本",
        "corrected": "这是一段完全不同的长文本内容",
        "reason": "test",
    }]
    result = review_corrections(proposals, [], max_edit_ratio=0.15)
    assert "e1" not in result.accepted


def test_reviewer_rejects_protected_term_removal():
    proposals = [{
        "id": "e1",
        "original": "Transformer 架构",
        "corrected": "模型架构",
        "reason": "test",
    }]
    result = review_corrections(proposals, ["Transformer"], max_edit_ratio=0.8)
    assert "e1" not in result.accepted
    assert result.rejected[0]["reject_reason"] == "触及受保护专有名词"


def test_reviewer_rejects_number_change():
    proposals = [{
        "id": "e1",
        "original": "GPT-4 在 2023 年发布",
        "corrected": "GPT-4 在 2024 年发布",
        "reason": "test",
    }]
    result = review_corrections(proposals, ["GPT-4"], max_edit_ratio=0.8)
    assert "e1" not in result.accepted
    assert result.rejected[0]["reject_reason"] == "数字被改动"
