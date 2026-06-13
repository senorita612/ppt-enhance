from ppt_enhance.nlp.protected_terms import (
    extract_protected_terms,
    merge_protected_terms,
    split_protected_terms,
)


def test_extract_protected_terms_for_mixed_technical_names():
    texts = [
        "Transformer 架构使用 Self-Attention 机制。",
        "GPT-4o、Qwen-OCR 和 NotebookLM 都需要保持原样。",
        "本页讨论深度学习模型、自注意力机制和向量检索系统。",
        "Transformer 在后续页面再次出现。",
    ]

    terms = extract_protected_terms(texts)

    assert "Transformer" in terms
    assert "Self-Attention" in terms
    assert "GPT-4o" in terms
    assert "Qwen-OCR" in terms
    assert "NotebookLM" in terms
    assert "深度学习模型" in terms
    assert "自注意力机制" in terms


def test_extract_protected_terms_filters_common_words():
    terms = extract_protected_terms(["这是一个系统，可以生成页面内容。"])

    assert "系统" not in terms
    assert "页面" not in terms


def test_user_protected_terms_split_and_merge():
    raw = "NotebookLM, 张三、北京大学\n项目X"

    assert split_protected_terms(raw) == ["NotebookLM", "张三", "北京大学", "项目X"]
    assert merge_protected_terms(["Transformer", "NotebookLM"], raw) == [
        "Transformer",
        "NotebookLM",
        "张三",
        "北京大学",
        "项目X",
    ]
