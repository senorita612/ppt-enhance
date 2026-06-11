"""多智能体纠错管线."""

from __future__ import annotations

from dataclasses import dataclass, field

from ppt_enhance.agents.contributor import propose_corrections
from ppt_enhance.agents.llm_client import LLMClient
from ppt_enhance.agents.reviewer import review_corrections
from ppt_enhance.config import settings
from ppt_enhance.schemas.slide_ir import SlideIR


@dataclass
class CorrectionRecord:
    element_id: str
    original: str
    corrected: str
    reason: str
    accepted: bool
    correction_type: str = "ocr_fix"
    reject_reason: str = ""


@dataclass
class CorrectionPipeline:
    llm: LLMClient | None = None
    max_rounds: int = settings.max_correction_rounds
    enable_fluency: bool = True
    records: list[CorrectionRecord] = field(default_factory=list)

    def run(self, slide_ir: SlideIR, enable_correction: bool = True) -> SlideIR:
        if not enable_correction:
            return slide_ir

        elements = slide_ir.all_text_elements()
        if not elements:
            return slide_ir

        llm = self.llm or LLMClient()
        all_accepted: dict[str, str] = {}
        # 被拒元素也记下，避免下一轮重复提议、空烧 token
        settled: set[str] = set()

        for _round_no in range(1, self.max_rounds + 1):
            pending = [e for e in elements if e.id not in settled]
            if not pending:
                break

            proposals = propose_corrections(
                pending,
                slide_ir.protected_terms,
                llm,
                document_elements=elements,
                enable_fluency=self.enable_fluency,
            )
            if not proposals:
                break

            review = review_corrections(proposals, slide_ir.protected_terms, llm)

            for p in proposals:
                elem_id = p["id"]
                ctype = p.get("type", "ocr_fix")
                if elem_id in review.accepted:
                    all_accepted[elem_id] = review.accepted[elem_id]
                    settled.add(elem_id)
                    self.records.append(CorrectionRecord(
                        element_id=elem_id,
                        original=p.get("original", ""),
                        corrected=p["corrected"],
                        reason=p.get("reason", ""),
                        accepted=True,
                        correction_type=ctype,
                    ))
                else:
                    reject_reason = next(
                        (r.get("reject_reason", "") for r in review.rejected if r["id"] == elem_id),
                        "未通过审查",
                    )
                    settled.add(elem_id)
                    self.records.append(CorrectionRecord(
                        element_id=elem_id,
                        original=p.get("original", ""),
                        corrected=p.get("corrected", ""),
                        reason=p.get("reason", ""),
                        accepted=False,
                        correction_type=ctype,
                        reject_reason=reject_reason,
                    ))

            if not review.accepted:
                break

        slide_ir.apply_corrections(all_accepted)
        return slide_ir
