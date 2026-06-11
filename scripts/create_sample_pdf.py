"""生成测试用样例 PDF（模拟 NotebookLM 风格幻灯片）.

关键：必须用支持中文字形的字体（PyMuPDF 内置 "china-s" 简体中文），
否则默认 helv 字体无 CJK 字形，中文会渲染成占位方块/点，
导致整条链路（纠错、版面 IoU、SSIM）都拿不到真实文本。

样例内容刻意混入两类文本，用于演示"受控纠错"这一招牌能力：
  1. OCR 错别字（应被纠正）：学刁→学习、深渡→深度、数椐→数据 等
  2. 专有名词/数字/公式（不应被改动）：Transformer、Q,K,V、GPT-4、95.3%
这样才能展示双智能体"只改错字、不动专名"的过纠正控制。
"""

from __future__ import annotations

from pathlib import Path

import fitz

CJK_FONT = "china-s"  # PyMuPDF 内置简体中文字体

# (标题, 正文行列表)；正文按行排版，避免依赖 \n 的字体度量
PAGES_CONTENT = [
    (
        "深度学习基础",
        [
            "神经网络与机器学刁入门",          # 学刁 → 学习
            "• 监督学习与无监督学刁",          # 学刁 → 学习
            "• 深渡神经网络的兴起",            # 深渡 → 深度
            "• 强化学习与决策优化",            # 正确，不应改
        ],
    ),
    (
        "Transformer 架构",
        [
            "自注意力机制 Self-Attention",     # 专名，不应改
            "核心公式: Attention(Q,K,V)",       # 公式，不应改
            "由 Google 在 2017 年提出",         # 数字/专名，不应改
            "极大提升了序列建模的效率",         # 正确
        ],
    ),
    (
        "应用案例",
        [
            "大语言模型 LLM 正在改变各行各业",   # 专名，不应改
            "数椐驱动的智能决策系统",            # 数椐 → 数据
            "GPT-4 在多项基准上达到 95.3%",      # 数字/专名，不应改
            "推里速度较上一代提升 3 倍",         # 推里 → 推理
        ],
    ),
]


def create_sample_pdf(output_path: str | Path) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open()
    for title, body_lines in PAGES_CONTENT:
        page = doc.new_page(width=960, height=540)
        page.insert_text(
            (60, 90), title, fontsize=36, fontname=CJK_FONT, color=(0.1, 0.1, 0.4)
        )
        y = 170
        for line in body_lines:
            page.insert_text(
                (60, y), line, fontsize=22, fontname=CJK_FONT, color=(0.2, 0.2, 0.2)
            )
            y += 50
        page.insert_text(
            (820, 520), "NotebookLM", fontsize=10, fontname=CJK_FONT, color=(0.8, 0.8, 0.8)
        )

    doc.save(str(output_path))
    doc.close()
    return output_path


if __name__ == "__main__":
    path = create_sample_pdf(Path(__file__).parent.parent / "data/samples/sample_slides.pdf")
    print(f"Created: {path}")
