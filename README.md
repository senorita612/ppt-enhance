# PPT Enhance

PPT Enhance is a PDF-to-PPTX reconstruction tool for slide decks exported from
NotebookLM and similar AI tools. It extracts slide content, corrects risky OCR
text, rebuilds editable PowerPoint files, evaluates conversion quality, and can
generate Speaker Notes with an OpenAI-compatible model API.

## Features

- **Multiple parsers**: Docling for vector PDFs, Qwen-OCR for image-only PDFs,
  and MinerU JSON import.
- **Coordinate-locked PPTX rebuild**: text and images are placed back using the
  original page coordinates, so the output stays close to the source layout.
- **Controlled text correction**: contributor/reviewer agents correct OCR and
  wording while protecting numbers and domain terms.
- **Protected term extraction**: automatically detects important English terms,
  acronyms, version strings, model names, and user-provided terms.
- **Speaker Notes generation**: creates per-slide presenter scripts from slide
  content and optional reference material, writes them into PPTX notes, and
  exports JSON/Markdown copies.
- **Quality evaluation**: SSIM, PSNR, CER, token error rate, editability ratio,
  text change ratio, protected-term violations, numeric mismatches, text
  overflow risk, overlap risk, and layout IoU when LibreOffice is available.
- **Chinese font handling**: selects a platform-specific CJK font and writes the
  PowerPoint East Asian font slot to reduce Chinese garbling in PowerPoint and
  LibreOffice.
- **Staged Streamlit UI**: parse once, review and edit SlideIR page by page,
  preview a single regenerated page, then export the full PPTX.

## Quick Start

```powershell
cd D:\projects\projects\ppt-enhance
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

Start the Streamlit UI:

```powershell
.\.venv\Scripts\streamlit.exe run ppt_enhance\ui\app.py
```

If the default port is occupied:

```powershell
.\.venv\Scripts\streamlit.exe run ppt_enhance\ui\app.py --server.port 8503
```

## API Configuration

The project uses OpenAI-compatible chat completions for correction and Speaker
Notes. Without an API key, text correction and notes generation fall back to
local rule-based behavior.

Create `.env` from `.env.example` and set:

```env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_MODEL=deepseek-ai/DeepSeek-V3
```

Other common examples:

```env
# DeepSeek
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

# DashScope OpenAI-compatible endpoint
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus

# OpenAI
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

For Qwen-OCR, `OPENAI_API_KEY` should be a DashScope API key because that parser
uses the DashScope multimodal OCR SDK.

LibreOffice is optional but recommended for reliable PPTX rendering and visual
evaluation. If it is not found automatically, set one of:

```env
SOFFICE_PATH=C:\Program Files\LibreOffice\program\soffice.exe
LIBREOFFICE_PATH=C:\Program Files\LibreOffice
```

## Streamlit Workflow

The UI is split into stages to avoid repeatedly running slow parsing work:

1. Upload a PDF and click **解析并进入人工校对**.
2. In **逐页预览与校对**, inspect the source page, edit extracted text, and view
   per-page risk metrics.
3. Click **快速重生成当前页预览** to rebuild and render only the selected page.
4. In **生成与评估**, export the full PPTX from the current edited SlideIR.
5. Turn on full quality evaluation only when you need SSIM/PSNR/layout IoU,
   because it requires PPTX rendering through LibreOffice.

The UI stores session files under `.ppt_enhance_cache/ui_sessions/`, so page
switching and repeated exports reuse the parsed intermediate data.

## CLI Usage

Basic conversion:

```powershell
ppt-enhance input.pdf
```

Image-only PDF with OCR:

```powershell
ppt-enhance input.pdf --parser qwen-ocr
```

Use MinerU JSON:

```powershell
ppt-enhance input.pdf --mineru-json mineru.json
```

Generate Speaker Notes:

```powershell
ppt-enhance input.pdf --speaker-notes --notes-material notes.md --notes-seconds 75
```

Protect extra domain terms:

```powershell
ppt-enhance input.pdf --protected-term "NotebookLM" --protected-term "Self-Attention"
```

Useful flags:

| Flag | Description |
| --- | --- |
| `--parser {docling,qwen-ocr}` | Choose parser. Use `qwen-ocr` for image-only PDFs. |
| `--mineru-json PATH` | Import MinerU JSON instead of parser output. |
| `--no-correction` | Skip intelligent correction. |
| `--no-eval` | Skip quality evaluation for faster conversion. |
| `--dpi N` | Render DPI, default `150`. |
| `--no-background` | Disable full-page background mode. |
| `--ground-truth PATH` | Provide reference text for CER/token error rate. |
| `--protected-term TERM` | Add protected terms. Can be repeated. |
| `--speaker-notes` | Generate PPTX Speaker Notes. |
| `--notes-material PATH` | Add reference material for notes. Can be repeated. |
| `--notes-seconds N` | Target speaking time per slide. |
| `--notes-style TEXT` | Notes style, such as `课程讲解` or `商务汇报`. |

## Outputs

For an input named `deck.pdf`, the pipeline writes output files under
`deck_output/` by default:

- `deck_enhanced.pptx`: rebuilt editable PowerPoint deck.
- `slide_ir.json`: parsed intermediate representation.
- `slide_ir_corrected.json`: representation after correction.
- `slide_ir_final.json`: final edited representation from the UI.
- `eval_report.json`: quality metrics when evaluation is enabled.
- `speaker_notes.json`: structured Speaker Notes result.
- `speaker_notes.md`: Markdown export of the notes.

## Project Structure

```text
ppt_enhance/
├── agents/       # contributor/reviewer correction agents and LLM client
├── builder/      # PPTX builder, layout engine, fonts, formula rendering
├── eval/         # visual/text/layout quality metrics and render helpers
├── nlp/          # protected term extraction
├── notes/        # Speaker Notes generation and PPTX note writing
├── parser/       # Docling, Qwen-OCR, MinerU, PDF rendering
├── pipeline/     # end-to-end pipeline orchestration
├── schemas/      # SlideIR and semantic outline schemas
└── ui/           # Streamlit app
```

## Current Status

Implemented:

- Docling, Qwen-OCR, and MinerU parsing paths.
- Coordinate-locked PPTX generation.
- Controlled correction with reviewer safeguards.
- Automatic and manual protected-term protection.
- Numeric mismatch detection.
- Enhanced text/layout evaluation metrics.
- LibreOffice detection on Windows and common environment variables.
- Cross-platform CJK font selection and East Asian font XML writing.
- Speaker Notes generation, PPTX injection, JSON export, and Markdown export.
- Streamlit staged review UI with page-level editing and current-page preview.

Still useful next steps:

- Make the semantic outline reconstruction path selectable from the main
  pipeline.
- Add model connection testing and model selection inside the UI.
- Add batch processing and resumable jobs.
- Add stronger template/style presets for business, teaching, and defense decks.
- Add per-slide Speaker Notes regeneration and manual notes editing in the UI.

## Development

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

The current test suite covers correction safeguards, protected terms, metrics,
font XML writing, and Speaker Notes generation/writing.
