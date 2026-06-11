"""Contributor Agent: 提议 OCR 错字修正 + 去 AI 腔润色.

两类修正分开标注（CorrectionType），因哲学相反：
- OCR_FIX：保守，只改明显错字/形近误识，绝不改原意。
- FLUENCY：去除 NotebookLM 等生成式工具的"AI 腔"（过度修饰、翻译腔、机械排比、
  冗余"的"字、生硬连接词），让表达自然，但不改事实与专名。

关键改进：上下文从"同页 neighbors"升级为"全文档"——注入跨页术语表 + 全篇文本，
让模型用别处出现的完整词形校正此处的残字（如全篇有"特质波动率"则敢把"特股"修对）。
单页信息不足时纠错保守，全文档上下文下召回与精度同时提升。
"""

from __future__ import annotations

import json
from typing import Any

from ppt_enhance.agents.llm_client import LLMClient
from ppt_enhance.schemas.slide_ir import CorrectionType, SlideElement

CONTRIBUTOR_SYSTEM = """你是 PPT 文本质量专家，同时承担两项任务：OCR 纠错 与 去 AI 腔润色。

你会收到整份演示文稿的全部文本（含页码）和一份术语表（已确认的专有名词/英文缩写）。
请利用全文档上下文判断：某处的可疑文字，是否在别处有完整、正确的形态可参照。

【任务一：OCR 纠错】type = "ocr_fix"
- 修正明显的 OCR 错字、形近误识（如"学刁"→"学习"、"特股"→"特质"、"投睿"→"投资"）
- 修正 OCR 造成的多余/缺失标点
- 严禁改变原意、专有名词、人名、数字、公式、术语表中的词
- 依据：优先用术语表和全文档中出现过的正确词形来判定

【任务二：去 AI 腔润色】type = "fluency"
- 仅当表达明显"AI 化/不自然"时才改：过度堆砌的修饰语、翻译腔、机械排比、
  冗余的"的/了"、生硬的连接词、空洞的套话
- 改写要保持原意和所有事实/数字/专名不变，只让中文更自然简练
- 不确定是否更好就不要改；宁可不改，不要为改而改

【通用规则】
- 没有问题的文本不要提议修正
- 每条修正必须给出简短 reason
- 区分清楚 type：改错字=ocr_fix，顺语言=fluency

输出 JSON：
{
  "corrections": [
    {"id": "元素ID", "type": "ocr_fix", "original": "原文", "corrected": "修正后", "reason": "原因"},
    {"id": "元素ID", "type": "fluency", "original": "原文", "corrected": "润色后", "reason": "原因"}
  ]
}
"""


def _build_document_context(all_elements: list[SlideElement]) -> list[dict[str, Any]]:
    """全文档文本快照（按页），供模型做跨页参照。"""
    by_page: dict[int, list[str]] = {}
    for e in all_elements:
        if e.text.strip():
            by_page.setdefault(e.page_no, []).append(e.text)
    return [{"page": pno, "texts": by_page[pno]} for pno in sorted(by_page)]


def propose_corrections(
    elements: list[SlideElement],
    protected_terms: list[str],
    llm: LLMClient | None = None,
    document_elements: list[SlideElement] | None = None,
    enable_fluency: bool = True,
) -> list[dict[str, str]]:
    """返回 [{id, type, original, corrected, reason}, ...].

    elements: 本轮待处理（尚未修正）的元素。
    document_elements: 全文档所有元素，用于构建跨页上下文；缺省时退回 elements。
    enable_fluency: 是否同时做去 AI 腔润色。
    """
    if not elements:
        return []

    llm = llm or LLMClient()
    if not llm.available:
        return _rule_based_corrections(elements)

    doc_context = _build_document_context(document_elements or elements)

    user_payload = {
        "targets": [
            {"id": e.id, "text": e.text, "type": e.type.value, "page": e.page_no}
            for e in elements
        ],
        "document": doc_context,
        "protected_terms": protected_terms,
        "enable_fluency": enable_fluency,
    }
    try:
        result = llm.chat_json(CONTRIBUTOR_SYSTEM, json.dumps(user_payload, ensure_ascii=False))
        corrections = result.get("corrections", [])
        # 规范 type 字段，缺省按 ocr_fix
        for c in corrections:
            t = str(c.get("type", "")).lower()
            c["type"] = (
                CorrectionType.FLUENCY.value
                if t == CorrectionType.FLUENCY.value
                else CorrectionType.OCR_FIX.value
            )
        if not enable_fluency:
            corrections = [c for c in corrections if c["type"] == CorrectionType.OCR_FIX.value]
        return corrections
    except Exception:
        return _rule_based_corrections(elements)


def _rule_based_corrections(elements: list[SlideElement]) -> list[dict[str, str]]:
    """无 API 时的轻量规则纠错（常见 OCR 混淆）."""
    common_fixes = {
        "学刁": "学习",
        "深渡": "深度",
        "神精网络": "神经网络",
        "机器学刁": "机器学习",
        "数椐": "数据",
        "模形": "模型",
        "算发": "算法",
        "优华": "优化",
        "训炼": "训练",
        "推里": "推理",
    }
    corrections = []
    for elem in elements:
        corrected = elem.text
        reasons = []
        for wrong, right in common_fixes.items():
            if wrong in corrected:
                corrected = corrected.replace(wrong, right)
                reasons.append(f"{wrong}→{right}")
        if corrected != elem.text:
            corrections.append({
                "id": elem.id,
                "type": CorrectionType.OCR_FIX.value,
                "original": elem.text,
                "corrected": corrected,
                "reason": "; ".join(reasons),
            })
    return corrections
