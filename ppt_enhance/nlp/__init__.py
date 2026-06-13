"""Local NLP helpers for PPT Enhance."""

from ppt_enhance.nlp.protected_terms import (
    extract_protected_terms,
    merge_protected_terms,
    split_protected_terms,
)

__all__ = ["extract_protected_terms", "merge_protected_terms", "split_protected_terms"]
