"""Protected term extraction for correction safeguards.

The correction agents use these terms as hard constraints: if a proposed edit
removes or rewrites a protected term, the reviewer rejects it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


_LATIN_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z][A-Za-z0-9]*(?:[-_/+.][A-Za-z0-9]+)*"
    r"(?![A-Za-z0-9])"
)
_BRACKET_RE = re.compile(r"[《「『“\"]([^《》「」『』“”\"]{2,40})[》」』”\"]")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9_\-+/]{2,40}")

_TECH_SUFFIXES = (
    "模型",
    "算法",
    "框架",
    "系统",
    "平台",
    "网络",
    "数据集",
    "架构",
    "机制",
    "公式",
    "指标",
    "方法",
    "任务",
    "流程",
    "引擎",
    "工具",
    "模块",
    "智能体",
    "解析器",
    "评测",
    "注意力",
    "语义",
    "向量",
    "矩阵",
    "函数",
    "管线",
    "流水线",
    "讲稿",
    "纠错",
)

_LATIN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}

_CJK_PREFIX_NOISE = (
    "一个",
    "一种",
    "这个",
    "这些",
    "本页",
    "主要",
    "讨论",
    "可以",
    "通过",
    "利用",
    "结合",
    "基于",
    "用于",
    "对于",
    "以及",
    "其中",
    "然后",
    "接着",
    "说明",
    "实现",
    "生成",
)

_CJK_STOPWORDS = {
    "系统",
    "模型",
    "算法",
    "平台",
    "方法",
    "任务",
    "流程",
    "工具",
    "模块",
    "指标",
    "公式",
    "网络",
    "数据",
    "文本",
    "页面",
    "内容",
}

_KNOWN_LATIN_TERMS = {
    "attention",
    "bert",
    "clip",
    "dashscope",
    "docling",
    "gpt",
    "libreoffice",
    "llm",
    "lora",
    "mineru",
    "notebooklm",
    "openai",
    "pandoc",
    "powerpoint",
    "pymupdf",
    "qwen",
    "rag",
    "self-attention",
    "streamlit",
    "transformer",
    "vlm",
}


@dataclass
class _Candidate:
    term: str
    score: float = 0.0
    count: int = 0


def _clean_term(term: str) -> str:
    term = re.sub(r"\s+", " ", term).strip()
    return term.strip(" \t\r\n,.;:!?，。；：！？、()（）[]【】<>《》\"'“”‘’")


def _is_latin_term(term: str, count: int) -> bool:
    lower = term.lower()
    if lower in _LATIN_STOPWORDS:
        return False
    if len(term) < 2:
        return False
    has_digit = bool(re.search(r"\d", term))
    has_separator = bool(re.search(r"[-_/+.]", term))
    has_acronym = bool(re.search(r"[A-Z]{2,}", term))
    has_camel = bool(re.search(r"[a-z][A-Z]", term))
    is_known = lower in _KNOWN_LATIN_TERMS
    is_title_term = term[:1].isupper() and len(term) >= 4 and count >= 2
    return has_digit or has_separator or has_acronym or has_camel or is_known or is_title_term


def _trim_cjk_noise(term: str) -> str:
    changed = True
    while changed:
        changed = False
        for prefix in _CJK_PREFIX_NOISE:
            if term.startswith(prefix) and len(term) > len(prefix) + 2:
                term = term[len(prefix) :]
                changed = True
                break
    return term


def _extract_cjk_suffix_terms(text: str) -> list[str]:
    terms: list[str] = []
    for run_match in _CJK_RUN_RE.finditer(text):
        pieces = re.split(r"(?:以及|并且|或者|和|与|及)", run_match.group(0))
        for run in pieces:
            if len(run) < 2:
                continue
            for suffix in _TECH_SUFFIXES:
                start = 0
                while True:
                    idx = run.find(suffix, start)
                    if idx < 0:
                        break
                    end = idx + len(suffix)
                    prefix_start = max(0, idx - 8)
                    term = _trim_cjk_noise(run[prefix_start:end])
                    term = _clean_term(term)
                    if 2 < len(term) <= 14 and term not in _CJK_STOPWORDS:
                        terms.append(term)
                    start = end
    return terms


def _extract_optional_jieba_terms(texts: Iterable[str]) -> list[str]:
    """Use jieba when installed, but keep the project dependency-free."""
    try:
        import jieba.posseg as pseg
    except Exception:
        return []

    terms: list[str] = []
    for text in texts:
        try:
            for word, flag in pseg.cut(text):
                word = _clean_term(word)
                if flag in {"nr", "ns", "nt", "nz", "eng"} and len(word) >= 2:
                    if word not in _CJK_STOPWORDS and word.lower() not in _LATIN_STOPWORDS:
                        terms.append(word)
        except Exception:
            continue
    return terms


def _add_candidate(candidates: dict[str, _Candidate], term: str, score: float) -> None:
    term = _clean_term(term)
    if not term:
        return
    if len(term) > 40:
        return
    item = candidates.setdefault(term, _Candidate(term=term))
    item.score += score
    item.count += 1


def extract_protected_terms(texts: Iterable[str], max_terms: int = 80) -> list[str]:
    """Extract high-confidence proper nouns and technical terms.

    This intentionally favors precision over recall. Terms are later used as
    hard review constraints, so noisy common words would reject useful edits.
    """
    text_list = [str(text or "") for text in texts if str(text or "").strip()]
    if not text_list:
        return []

    joined = "\n".join(text_list)
    latin_counts = Counter(_clean_term(m.group(0)) for m in _LATIN_TOKEN_RE.finditer(joined))
    candidates: dict[str, _Candidate] = {}

    for term, count in latin_counts.items():
        if _is_latin_term(term, count):
            score = 3.0 + min(count, 4)
            if re.search(r"\d", term):
                score += 1.5
            if re.search(r"[-_/+.]", term):
                score += 1.0
            _add_candidate(candidates, term, score)

    for match in _BRACKET_RE.finditer(joined):
        term = _clean_term(match.group(1))
        if any(suffix in term for suffix in _TECH_SUFFIXES) or re.search(r"[A-Za-z0-9]", term):
            _add_candidate(candidates, term, 4.0)

    for term in _extract_cjk_suffix_terms(joined):
        _add_candidate(candidates, term, 3.0)

    cjk_counts = Counter(_extract_cjk_suffix_terms(joined))
    for term, count in cjk_counts.items():
        if count >= 2:
            _add_candidate(candidates, term, min(4.0, count))

    for term in _extract_optional_jieba_terms(text_list):
        if re.search(r"[A-Za-z0-9]", term):
            _add_candidate(candidates, term, 2.0)
        elif any(term.endswith(suffix) for suffix in _TECH_SUFFIXES):
            _add_candidate(candidates, term, 2.0)

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-item.score, -item.count, len(item.term), item.term.lower()),
    )

    result: list[str] = []
    seen_lower: set[str] = set()
    for item in ranked:
        key = item.term.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        result.append(item.term)
        if len(result) >= max_terms:
            break
    return result


def split_protected_terms(raw_terms: str | Iterable[str] | None) -> list[str]:
    """Parse user-provided protected terms from CLI/UI input."""
    if not raw_terms:
        return []
    if isinstance(raw_terms, str):
        parts = re.split(r"[\n,，;；、]+", raw_terms)
    else:
        parts = []
        for item in raw_terms:
            parts.extend(re.split(r"[\n,，;；、]+", str(item)))

    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        term = _clean_term(part)
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def merge_protected_terms(
    extracted_terms: Iterable[str],
    extra_terms: str | Iterable[str] | None = None,
    max_terms: int = 120,
) -> list[str]:
    """Merge extracted and user-provided protected terms while preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for term in [*extracted_terms, *split_protected_terms(extra_terms)]:
        term = _clean_term(term)
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(term)
        if len(merged) >= max_terms:
            break
    return merged
