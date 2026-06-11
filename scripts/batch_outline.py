"""批量逆推 15 页大纲，标出含复杂图形的页，缓存结果。"""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from ppt_enhance.schemas.slide_ir import SlideIR
from ppt_enhance.parser.outline_extractor import extract_outline
from ppt_enhance.agents.llm_client import LLMClient

ir = SlideIR.load("data/samples/real_notebooklm_output/slide_ir_corrected.json")
llm = LLMClient()
out_dir = Path(".ppt_enhance_cache/real_notebooklm/outlines")
out_dir.mkdir(parents=True, exist_ok=True)


def do_page(page):
    elems = [e for e in page.elements if e.is_textual and e.final_text.strip()]
    ol = extract_outline(page.render_path, page.page_no, page.width, page.height, elems, llm=llm)
    f = out_dir / f"outline_p{page.page_no:04d}.json"
    f.write_text(ol.model_dump_json(indent=1))
    return (page.page_no, ol.layout_type.value, len(ol.nodes), len(ol.keep_regions),
            ol.style.card_style, ol.title[:22])


with ThreadPoolExecutor(max_workers=6) as ex:
    results = sorted(ex.map(do_page, ir.pages))

print(f"{'page':>4} {'layout':<14} {'nodes':>5} {'keep':>4} {'card':<11} title")
for pno, lt, nn, kr, cs, title in results:
    flag = "  <-- KEEP" if kr else ""
    print(f"{pno:>4} {lt:<14} {nn:>5} {kr:>4} {cs:<11} {title}{flag}")
