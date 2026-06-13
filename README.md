# PPT Enhance

PPT Enhance 是一个面向 NotebookLM 等 AI 工具导出幻灯片 PDF 的
PDF-to-PPTX 重建工具。它可以解析 PDF 页面内容，进行受控文本纠错，重建可编辑
PowerPoint 文件，评估转换质量，并基于 OpenAI 兼容模型 API 生成逐页 Speaker Notes。

## 核心功能

- **多解析通路**：支持 Docling、Qwen-OCR 和 MinerU JSON。矢量 PDF 优先使用
  Docling，纯图片 PDF 可使用 Qwen-OCR，已有 MinerU 结果时可直接导入 JSON。
- **坐标锚定重建**：按原 PDF 页面坐标把文本、图片和背景放回 PPTX，尽量保持源文件版面。
- **受控智能纠错**：Contributor 提议、Reviewer 审查，避免模型过度改写原文。
- **专有名词保护**：自动抽取英文术语、缩写、版本号、模型名等，也支持用户手动补充保护词。
- **数字保护**：检测纠错前后数字、百分比、年份等是否发生异常变化。
- **Speaker Notes 生成**：结合每页 PPT 内容和用户补充资料，生成逐页演讲稿，写入 PPTX 备注区，并导出 JSON/Markdown。
- **质量评价指标**：支持 SSIM、PSNR、CER、Token Error Rate、可编辑率、文本改动率、专有名词缺失、数字变化、文本溢出、元素重叠和版面 IoU。
- **中文字体修复**：按平台自动选择中文字体，并写入 PowerPoint 东亚字体槽，减少中文乱码和 LibreOffice 字体 fallback。
- **分阶段 Streamlit UI**：先解析并校对中间结果，再逐页预览、单页重生成，最后导出整份 PPTX，避免每次都重跑完整流程。

## 快速开始

Windows PowerShell 示例：

```powershell
cd D:\projects\projects\ppt-enhance
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

启动 Web 界面：

```powershell
.\.venv\Scripts\streamlit.exe run ppt_enhance\ui\app.py
```

如果默认端口被占用：

```powershell
.\.venv\Scripts\streamlit.exe run ppt_enhance\ui\app.py --server.port 8503
```

## API 配置

项目使用 OpenAI 兼容的 Chat Completions 接口。配置 API 后，智能纠错和 Speaker Notes 会调用模型；没有 API Key 时，会回退到本地规则或简化生成。

复制 `.env.example` 为 `.env` 后配置：

```env
OPENAI_API_KEY=你的_api_key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_MODEL=deepseek-ai/DeepSeek-V3
```

常见配置示例：

```env
# 硅基流动
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_MODEL=deepseek-ai/DeepSeek-V3

# DeepSeek
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

# 通义千问 OpenAI 兼容接口
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus

# OpenAI 官方
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

如果使用 `--parser qwen-ocr`，`OPENAI_API_KEY` 需要填 DashScope API Key，因为该解析器调用的是 DashScope 多模态 OCR SDK。

LibreOffice 是可选依赖，但建议安装。它用于把 PPTX 渲染成图片/PDF，从而计算更可靠的视觉评价指标。如果程序没有自动识别到 LibreOffice，可以在 `.env` 中设置：

```env
SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
LIBREOFFICE_PATH=C:\Program Files\LibreOffice
```

## Streamlit 使用流程

新版 UI 采用分阶段流程，主要目的是减少等待时间，并允许人工检查中间结果。

1. 上传 PDF，点击 **解析并进入人工校对**。
2. 在 **逐页预览与校对** 中查看原始页面、文本元素和单页风险指标。
3. 手动修改 OCR 文本或纠错结果，然后点击 **应用本页编辑**。
4. 点击 **快速重生成当前页预览**，只重建并渲染当前页。
5. 在 **生成与评估** 中点击 **生成 / 重新生成整份 PPTX**。
6. 如需 SSIM、PSNR、版面 IoU 等完整评价，再开启侧边栏的 **生成后完整质量评估**。

UI 会把会话文件缓存到 `.ppt_enhance_cache/ui_sessions/`。切换页面、修改文本、重新导出时，不会重复解析整份 PDF。

## CLI 使用

基础转换：

```powershell
ppt-enhance input.pdf
```

纯图片 PDF 使用 Qwen-OCR：

```powershell
ppt-enhance input.pdf --parser qwen-ocr
```

使用 MinerU JSON：

```powershell
ppt-enhance input.pdf --mineru-json mineru.json
```

生成 Speaker Notes：

```powershell
ppt-enhance input.pdf --speaker-notes --notes-material notes.md --notes-seconds 75
```

补充专有名词保护词：

```powershell
ppt-enhance input.pdf --protected-term "NotebookLM" --protected-term "Self-Attention"
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--parser {docling,qwen-ocr}` | 选择解析器。纯图片 PDF 建议使用 `qwen-ocr`。 |
| `--mineru-json PATH` | 导入 MinerU JSON。 |
| `--no-correction` | 跳过智能纠错。 |
| `--no-eval` | 跳过质量评估，加快转换速度。 |
| `--dpi N` | 渲染 DPI，默认 `150`。 |
| `--no-background` | 关闭整页背景模式。 |
| `--ground-truth PATH` | 提供参考文本，用于计算 CER/Token Error Rate。 |
| `--protected-term TERM` | 添加专有名词保护词，可重复传入。 |
| `--speaker-notes` | 生成 PPTX Speaker Notes。 |
| `--notes-material PATH` | 添加演讲稿补充资料，可重复传入。 |
| `--notes-seconds N` | 每页目标讲稿时长。 |
| `--notes-style TEXT` | 演讲稿风格，例如 `课程讲解`、`商务汇报`。 |

## 输出文件

默认情况下，输入 `deck.pdf` 后会输出到 `deck_output/`：

- `deck_enhanced.pptx`：重建后的可编辑 PowerPoint 文件。
- `slide_ir.json`：解析后的中间表示。
- `slide_ir_corrected.json`：纠错后的中间表示。
- `slide_ir_final.json`：UI 人工校对后的最终中间表示。
- `eval_report.json`：质量评估报告。
- `speaker_notes.json`：结构化演讲稿结果。
- `speaker_notes.md`：演讲稿 Markdown 导出。

## 项目结构

```text
ppt_enhance/
├── agents/       # Contributor / Reviewer 纠错智能体与 LLM 客户端
├── builder/      # PPTX 构建、布局引擎、字体处理、公式渲染
├── eval/         # 视觉、文本和布局评价指标
├── nlp/          # 专有名词抽取与保护
├── notes/        # Speaker Notes 生成与 PPTX 备注写入
├── parser/       # Docling、Qwen-OCR、MinerU、PDF 渲染
├── pipeline/     # 端到端流水线
├── schemas/      # SlideIR 与语义大纲 schema
└── ui/           # Streamlit Web 界面
```

## 当前状态

已实现：

- Docling、Qwen-OCR、MinerU 三条解析通路。
- 坐标锚定 PPTX 重建。
- 多智能体受控纠错。
- 自动和手动专有名词保护。
- 数字变化检测。
- 增强版文本与布局评价指标。
- Windows 常见路径和环境变量下的 LibreOffice 检测。
- 跨平台中文字体选择和东亚字体 XML 写入。
- Speaker Notes 生成、写入 PPTX、导出 JSON 和 Markdown。
- Streamlit 分阶段校对 UI，支持逐页编辑和当前页快速预览。

仍可继续完善：

- 将语义大纲重建路线接入主流水线，并允许用户选择 `anchor` / `outline` 模式。
- 在 UI 中加入模型连接测试、Base URL 和模型选择。
- 增加批量处理和断点续跑。
- 增加商务、教学、答辩等模板/风格预设。
- 在 UI 中支持单页 Speaker Notes 重生成和手动编辑。

## 开发与测试

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

当前测试覆盖纠错保护、专有名词抽取、评价指标、字体 XML 写入，以及 Speaker Notes 生成和 PPTX 备注写入。
