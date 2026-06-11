"""公式处理：把 OCR 读成 LaTeX 的公式，转成 PowerPoint 原生 OMML（可编辑公式）。

背景：NotebookLM 导出的 PDF 是纯图片，公式被 OCR 读成 `$\\gamma \\cdot ...$` 这类
LaTeX 源码。直接当文本会满屏反斜杠。PowerPoint 原生支持 OMML 公式，且公式可与普通
文字同处一个文本框、可编辑——这同时满足「可编辑」与「排版正确」，优于渲染成图片。

链路：LaTeX → pandoc(+tex_math_dollars) → docx(含 OMML) → 抽取 m:oMath 片段。
布局引擎再把该片段注入到 pptx 文本框段落里。
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

# 数学结构标记
_FORMULA_MARK = re.compile(r"\\[a-zA-Z]+|[_^]\{|[_^][a-zA-Z0-9]")
_CJK = re.compile(r"[一-鿿]")

_CMD_TO_UNICODE = {
    r"\gamma": "γ", r"\delta": "δ", r"\alpha": "α", r"\beta": "β",
    r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ",
    r"\rho": "ρ", r"\phi": "φ", r"\epsilon": "ε", r"\tau": "τ",
    r"\cdot": "·", r"\times": "×", r"\leq": "≤", r"\geq": "≥",
    r"\approx": "≈", r"\sum": "Σ", r"\Delta": "Δ", r"\in": "∈",
}

_PANDOC: bool | None = None


def pandoc_available() -> bool:
    global _PANDOC
    if _PANDOC is None:
        _PANDOC = bool(shutil.which("pandoc"))
    return _PANDOC


def cjk_ratio(s: str) -> float:
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if _CJK.match(c)) / len(chars)


def is_formula_line(text: str) -> bool:
    """是否为纯公式行（含数学标记且 CJK 占比低）。"""
    s = text.strip()
    if not s:
        return False
    has_mark = bool(_FORMULA_MARK.search(s)) or "$" in s
    return has_mark and cjk_ratio(s) < 0.25


def clean_inline_latex(text: str) -> str:
    """清洗普通文字行里夹带的 LaTeX 标记（如 \\(\\gamma\\)）为可读 Unicode。"""
    s = text.replace(r"\(", "").replace(r"\)", "")
    s = s.replace(r"\[", "").replace(r"\]", "")
    for cmd, uni in _CMD_TO_UNICODE.items():
        s = s.replace(cmd, uni)
    s = s.replace("$", "")
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    return s.strip()


def _normalize_latex(text: str) -> str:
    """规整 OCR 公式文本为 pandoc 可解析的 $...$ 形式。"""
    s = text.strip()
    s = s.replace(r"\(", "$").replace(r"\)", "$")
    if not s.startswith("$"):
        s = "$" + s
    if not s.endswith("$"):
        s = s + "$"
    # 折叠重复 $$
    s = re.sub(r"\$\$+", "$", s)
    # 数学模式下裸 & 是对齐符，会破坏解析（如 R&D），需转义
    s = re.sub(r"(?<!\\)&", r"\\&", s)
    return s


_OMML_CACHE: dict[str, str] = {}


def latex_to_omml(text: str) -> str | None:
    """LaTeX 公式文本 → OMML 字符串（<m:oMath>...）。失败返回 None。结果缓存。"""
    if not pandoc_available():
        return None
    if text in _OMML_CACHE:
        return _OMML_CACHE[text] or None
    md = _normalize_latex(text)
    try:
        with tempfile.TemporaryDirectory() as d:
            md_path = Path(d) / "f.md"
            docx_path = Path(d) / "f.docx"
            md_path.write_text(md + "\n")
            r = subprocess.run(
                ["pandoc", "-f", "markdown+tex_math_dollars",
                 str(md_path), "-o", str(docx_path)],
                capture_output=True, text=True,
            )
            if not docx_path.exists():
                _OMML_CACHE[text] = ""
                return None
            import zipfile
            doc = zipfile.ZipFile(docx_path).read("word/document.xml").decode()
    except Exception:
        _OMML_CACHE[text] = ""
        return None
    m = re.search(r"<m:oMath\b.*?</m:oMath>", doc, re.S)
    if not m:
        _OMML_CACHE[text] = ""
        return None
    _OMML_CACHE[text] = m.group(0)
    return m.group(0)


def omml_element(omml_str: str):
    """把 OMML 字符串解析成可注入 pptx 的 lxml 元素（补全 m 命名空间）。"""
    wrapped = f'<root xmlns:m="{M_NS}">{omml_str}</root>'
    root = etree.fromstring(wrapped)
    return root[0]


# ---- PNG 渲染（用于 mc:Fallback，使 LibreOffice 等不支持 OMML 的程序也能显示）----

_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_A14_NS = "http://schemas.microsoft.com/office/drawing/2010/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_LATEX: bool | None = None


def latex_available() -> bool:
    global _LATEX
    if _LATEX is None:
        _LATEX = bool(shutil.which("latex") and shutil.which("dvipng"))
    return _LATEX


def _fg_rgb(hex_color: str) -> str:
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        return f"rgb {r:.3f} {g:.3f} {b:.3f}"
    except (ValueError, IndexError):
        return "rgb 1.0 1.0 1.0"


def render_formula_png(text: str, cache_dir: Path, *, fg_hex: str = "#FFFFFF",
                       dpi: int = 240) -> Path | None:
    """LaTeX 公式 → 透明背景 PNG（亮色前景）。失败返回 None。结果按内容缓存。"""
    if not latex_available():
        return None
    import hashlib
    body = text.strip().replace(r"\(", "").replace(r"\)", "").strip()
    if body.startswith("$") and body.endswith("$"):
        body = body[1:-1].strip()
    body = body.replace("$", "").strip()
    body = re.sub(r"(?<!\\)&", r"\\&", body)
    if not body:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"{body}|{fg_hex}|{dpi}".encode()).hexdigest()[:16]
    out_png = (cache_dir / f"formula_{key}.png").resolve()
    if out_png.exists():
        return out_png
    tex = (
        r"\documentclass[12pt]{article}\usepackage{amsmath,amssymb}"
        r"\usepackage[active,tightpage]{preview}\pagestyle{empty}"
        r"\begin{document}\begin{preview}$\displaystyle " + body +
        r"$\end{preview}\end{document}"
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            (dp / "f.tex").write_text(tex)
            subprocess.run(["latex", "-interaction=nonstopmode", "-halt-on-error", "f.tex"],
                           cwd=d, capture_output=True, text=True)
            if not (dp / "f.dvi").exists():
                return None
            subprocess.run(["dvipng", "-D", str(dpi), "-T", "tight", "-bg", "Transparent",
                            "-fg", _fg_rgb(fg_hex), "-o", str(out_png), "f.dvi"],
                           cwd=d, capture_output=True, text=True)
    except Exception:
        return None
    return out_png if out_png.exists() else None


def build_alt_content(omml_str: str, fallback_text: str = ""):
    """构建 PowerPoint 文本框内可编辑公式的标准包裹结构（[MS-PPTX] 规范）：

    mc:AlternateContent
      ├─ mc:Choice(Requires=a14) → a14:m → m:oMathPara → m:oMath  （PowerPoint 可编辑公式）
      └─ mc:Fallback → a:r → a:t                                  （其他程序降级显示文本）

    返回 lxml 元素，供插入 a:p。
    """
    nsmap = {"mc": _MC_NS, "a14": _A14_NS, "m": M_NS, "a": _A_NS}
    alt = etree.Element(f"{{{_MC_NS}}}AlternateContent", nsmap=nsmap)
    choice = etree.SubElement(alt, f"{{{_MC_NS}}}Choice")
    choice.set("Requires", "a14")
    a14m = etree.SubElement(choice, f"{{{_A14_NS}}}m")
    omath_para = etree.SubElement(a14m, f"{{{M_NS}}}oMathPara")
    omath_para.append(omml_element(omml_str))

    fb = etree.SubElement(alt, f"{{{_MC_NS}}}Fallback")
    run = etree.SubElement(fb, f"{{{_A_NS}}}r")
    t = etree.SubElement(run, f"{{{_A_NS}}}t")
    t.text = fallback_text
    return alt
