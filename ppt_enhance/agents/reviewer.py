"""Reviewer Agent: 审查修正，防止过度纠正.

按修正类别施加不同阈值（这是关键）：
- OCR_FIX：短文本用"绝对字符差"阈值，长文本才用比例阈值。否则"特股→特质波动率"
  这类 2→4 字的正确修正会被比例阈值（200% >> 15%）误杀。
- FLUENCY：去 AI 腔本质是改写，放宽比例阈值，但仍守住"专名/数字不变"的底线。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ppt_enhance.agents.llm_client import LLMClient
from ppt_enhance.config import settings
from ppt_enhance.schemas.slide_ir import CorrectionType

REVIEWER_SYSTEM = """你是文本修正审查员。审查 Contributor 的修正是否应采纳。

修正分两类，标准不同：
- type=ocr_fix（OCR 纠错）：只接受"修正错字/形近误识/标点"的改动；若改变了原意、
  专有名词、人名、数字、公式，则拒绝。
- type=fluency（去 AI 腔润色）：接受"让中文更自然简练"的改写，但若改变了事实、
  数字、专名，或改得更差/更啰嗦，则拒绝。

输出 JSON：
{
  "reviews": [
    {"id": "元素ID", "accept": true, "reason": "说明"}
  ]
}
"""


@dataclass
class ReviewResult:
    accepted: dict[str, str]
    rejected: list[dict]


def _edit_ratio(original: str, corrected: str) -> float:
    if not original:
        return 1.0 if corrected else 0.0
    m, n = len(original), len(corrected)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if original[i - 1] == corrected[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n] / m


def _edit_distance(original: str, corrected: str) -> int:
    """字符级编辑距离（绝对值）."""
    m, n = len(original), len(corrected)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if original[i - 1] == corrected[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def _violates_protected(corrected: str, protected_terms: list[str], original: str) -> bool:
    for term in protected_terms:
        if term in original and term not in corrected:
            return True
    return False


# OCR 短文本：长度 ≤ 该阈值时，改用绝对字符差判定
_SHORT_TEXT_LEN = 8
_SHORT_TEXT_MAX_EDITS = 4
# FLUENCY 润色：允许更大改写幅度
_FLUENCY_MAX_RATIO = 0.6


def _rule_review(
    proposals: list[dict],
    protected_terms: list[str],
    max_edit_ratio: float,
) -> ReviewResult:
    accepted: dict[str, str] = {}
    rejected: list[dict] = []

    for p in proposals:
        elem_id = p["id"]
        original = p.get("original", "")
        corrected = p.get("corrected", "")
        ctype = str(p.get("type", CorrectionType.OCR_FIX.value)).lower()

        if original == corrected:
            rejected.append({**p, "reject_reason": "无变化"})
            continue

        # 专名/数字底线：两类修正都要守
        if _violates_protected(corrected, protected_terms, original):
            rejected.append({**p, "reject_reason": "触及受保护专有名词"})
            continue
        if re.search(r"\d", original) and not re.search(r"\d", corrected):
            rejected.append({**p, "reject_reason": "数字被删除"})
            continue

        if ctype == CorrectionType.FLUENCY.value:
            # 润色：用更宽松的比例阈值
            if _edit_ratio(original, corrected) > _FLUENCY_MAX_RATIO:
                rejected.append({**p, "reject_reason": f"润色幅度超过 {_FLUENCY_MAX_RATIO:.0%}"})
                continue
            accepted[elem_id] = corrected
            continue

        # OCR_FIX：短文本用绝对字符差，长文本用比例
        if len(original) <= _SHORT_TEXT_LEN:
            if _edit_distance(original, corrected) > _SHORT_TEXT_MAX_EDITS:
                rejected.append(
                    {**p, "reject_reason": f"短文本改动超过 {_SHORT_TEXT_MAX_EDITS} 字"}
                )
                continue
        elif _edit_ratio(original, corrected) > max_edit_ratio:
            rejected.append({**p, "reject_reason": f"修改幅度超过 {max_edit_ratio:.0%}"})
            continue
        accepted[elem_id] = corrected

    return ReviewResult(accepted=accepted, rejected=rejected)


def review_corrections(
    proposals: list[dict],
    protected_terms: list[str],
    llm: LLMClient | None = None,
    max_edit_ratio: float | None = None,
) -> ReviewResult:
    max_edit_ratio = max_edit_ratio or settings.max_edit_ratio
    llm = llm or LLMClient()

    rule_result = _rule_review(proposals, protected_terms, max_edit_ratio)

    if not llm.available or not rule_result.accepted:
        return rule_result

    pending = [p for p in proposals if p["id"] in rule_result.accepted]
    try:
        llm_result = llm.chat_json(
            REVIEWER_SYSTEM,
            json.dumps({"proposals": pending, "protected_terms": protected_terms}, ensure_ascii=False),
        )
        llm_reviews = {r["id"]: r for r in llm_result.get("reviews", [])}
    except Exception:
        return rule_result

    accepted: dict[str, str] = {}
    rejected = list(rule_result.rejected)

    for p in pending:
        review = llm_reviews.get(p["id"], {})
        if review.get("accept", True):
            accepted[p["id"]] = p["corrected"]
        else:
            rejected.append({**p, "reject_reason": review.get("reason", "LLM 拒绝")})

    return ReviewResult(accepted=accepted, rejected=rejected)
