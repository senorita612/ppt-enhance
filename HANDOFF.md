# 接力文档 / HANDOFF

> 最后更新：2026-06-11
> 用途：记录项目当前真实进展、已跑通状态、下一步计划，供后续接力无缝衔接。

## 一句话现状

端到端流水线 `PDF → 解析 → 多智能体纠错 → 重建 PPTX → 量化评测` 已跑通，6 个 pytest 全过。
正准备进入「NLP 领域优化」阶段（见下方路线图），尚未动工。

## 如何运行

```bash
cd PPT_enhance
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # 配置 API key（无 key 时走规则兜底）
python scripts/create_sample_pdf.py
ppt-enhance data/samples/sample_slides.pdf          # 矢量 PDF
ppt-enhance input.pdf --parser qwen-ocr             # 纯图片 PDF（NotebookLM 导出）
streamlit run ppt_enhance/ui/app.py                 # Web 界面
pytest                                              # 6 个测试
```

## 已实现（已验证）

- **三条解析通路**：Docling（矢量文本）、Qwen-OCR（纯图片 PDF，绝对像素坐标）、MinerU JSON 导入
- **坐标锚定重建** `builder/pptx_builder.py`：按源坐标注入文本，只改字不改框，已接入主流水线
- **双 Agent 受控纠错** `agents/`：Contributor 提议（OCR 纠错 + 去 AI 腔润色）+ Reviewer 审查；按修正类别施加差异化阈值；跨全文档术语表上下文；无 API key 时规则兜底
- **公式可编辑** `builder/formula_render.py`：LaTeX → pandoc → PowerPoint 原生 OMML
- **评测体系** `eval/`：SSIM / PSNR / 可编辑性 / CER + 往返版面 IoU（PPTX→LibreOffice 渲染回 PDF→独立重提坐标，避免循环论证）
- **渲染可靠性标记**：无 LibreOffice 时回退占位图并标 `visual_reliable=False`，绝不伪造数值
- **Streamlit 界面** `ui/app.py`：上传、配置、下载 PPTX/JSON、查看指标与纠错记录
- **检测框可视化** `eval/bbox_viz.py`：OCR 定位框画回原图，人工核对坐标对齐

## 部分实现 / 实验中

- **大纲逆推重建路线** `parser/outline_extractor.py` + `builder/layout_engine.py`：不逆向像素而逆向到「生成这页时的语义大纲」，再用原生 PPT 元素重画，得到更干净、100% 可编辑的版面。
  当前仅在 `scripts/batch_outline.py`、`scripts/render_full.py` 中跑，**尚未接入主流水线**，未与坐标锚定路线做统一切换。

## 下一步路线图（按优先级）

### 1. NLP 领域优化（已规划，待动工）—— 当前焦点

课程为「文本分析与大语言模型」，NLP 含金量是评分重点。计划做 A+B+C 三项，均在分析/评测层，
风险低、可独立验证、不破坏已跑通的主流水线。计划集中放进新建的 `ppt_enhance/nlp/` 子包。

- **A. 术语保护升级**（补最弱短板）
  现状：`parser/docling_adapter.py::_extract_protected_terms` 是纯正则，只抓大写英文词 +「X模型/算法/系统」固定后缀的紧凑词；人名/地名/机构名全漏检；MinerU 路径直接给空列表 `[]`。漏检的专名 = 纠错时无保护 = 易被误改。
  方案：jieba 词性标注抽 nr/ns/nt/nz + TF-IDF/TextRank 自动建术语表 + 跨页一致性加权（同词反复出现→高置信专名）。纯本地。
  接入点：替换/增强 `_extract_protected_terms`，三条解析路径统一调用（含 MinerU）。

- **B. 去 AI 腔的量化评测**（课程亮点）
  现状：去 AI 腔润色完全没有量化指标，纯靠 LLM 主观判断。
  方案：对润色前后算「AI 味评分」——虚词密度（的/了/地）、四字格机械堆砌、连接词密度、词汇多样性（TTR/MTLD）、平均句长，可选困惑度。把润色从主观变为可量化对比。纯本地统计。
  接入点：新增 `nlp/ai_style.py`，在 `eval/metrics.py` 的 EvalReport 中增加字段，CLI/UI 展示润色前后对比。

- **C. 评测增强**
  现状：仅字符级 CER（`eval/metrics.py::compute_cer`），中文无分词；无语义层评测。
  方案：中文分词后 WER + OCR 错误类型诊断（替换/插入/删除分布、形近字混淆统计）+ 语义相似度（句向量算原文与重建文本语义保真，补 CER 只看字面之不足）。
  **依赖**：语义相似度需 sentence-transformers，首次联网下模型——用户已同意联网下载。注意历史踩坑：Docling 的 OCR 曾因联网下模型卡死，下载逻辑要可控、可跳过、有超时。
  接入点：新增 `nlp/semantic.py`、`nlp/error_diag.py`，结果并入 EvalReport。

实施顺序建议：A → B → C（A 补短板、B 做亮点纯本地、C 含联网项放最后）。
新增依赖：`jieba`、`scikit-learn`、`sentence-transformers`（写入 pyproject.toml）。

### 2. 演讲稿生成（规划中）

结合用户上传补充资料 + 各页 PPT 内容，逐页生成演讲稿写入 PPTX Speaker Notes（`slide.notes_slide.notes_text_frame`）。
当前代码中无任何 notes 相关实现。设计要点：RAG 召回（资料切块按页相关性召回）、逐页生成 Agent（控时长/衔接/保专名）、Streamlit 逐页查看/编辑/重生成、整篇导出 Markdown/Word。

### 3. UI 界面增强（规划中）

现有 Streamlit 基础上扩展：资料上传区、逐页原图 vs 重建对照预览、演讲稿面板（展示/编辑/单页重生成/整篇导出）、场景化参数预设。

### 4. 其它

- 大纲逆推路线接入主流水线（`--mode {anchor,outline}` 统一切换）
- Layout Validator 美学验证器（文本溢出/碰撞检测，对标 AeSlides）
- 编辑动作指令范式（Agent 输出结构化编辑动作，对标 PPTAgent）
- CER 消融实验（量化纠错各环节贡献）

## 关键约定 / 历史踩坑

- **git 仓库范围**：项目目录原先没有独立 `.git`，外层 `/Users/zyx` 有个空的占位仓库——千万别在那里 `git add`（会纳入整个 home 目录含 SSH 私钥）。本项目已初始化为**独立 git 仓库**，所有 git 操作限定在项目内。
- **`.env` 含真实 API key**（阿里云百炼 DashScope），已被 `.gitignore` 忽略，绝不提交。
- **Docling `do_ocr=True` 会联网下 RapidOCR 模型并卡死**，已默认 `enable_ocr=False`（数字原生 PDF 是矢量文本无需 OCR）。
- **视觉评测依赖 LibreOffice** 把 PPTX 渲染成图：`/Applications/LibreOffice.app/Contents/MacOS/soffice`，需在 PATH。无它时 SSIM 会虚高到 0.99 但不可信（已加 `visual_reliable` 标记）。真实渲染下样例 SSIM≈0.9966。
- **大体积产物不进仓库**：`data/samples/*_output/`、`*.pptx`、`real_notebooklm.pdf`(14M) 已在 `.gitignore`。
