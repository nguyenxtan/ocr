"""Evidence-based multi-engine seal OCR, conservative about disagreements.

Tesseract remains the baseline. Optional PP-OCRv6 and SealRecognition may add
independent clues, but cannot override a confidently contradictory MST.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

import numpy as np

from app.paddle_contract import OCRLine
from app.paddle_gateway import PaddleUnavailable, post_image, seal_as_rgb
from app.seal_ocr import SealEvidence, NameComparison, compare_name, distinct_tokens, normalize


@dataclass(frozen=True)
class EnsembleEvidence:
    name: NameComparison
    msts: frozenset[str]
    ambiguous: bool = False
    paddle_used: bool = False
    note: str = ""


def _group(lines: list[OCRLine], min_conf: float) -> SealEvidence:
    texts = tuple(x.text for x in lines if x.score >= min_conf)
    return SealEvidence(texts, frozenset())


def _codes(lines: list[OCRLine], validator, min_conf: float) -> set[str]:
    found: set[str] = set()
    for line in lines:
        if line.score < min_conf:
            continue
        for code in re.findall(r"(?<!\d)\d{10}(?!\d)", line.text.replace(" ", "")):
            if validator(code):
                found.add(code)
    return found


def _independent_tokens(company: str, evidence: SealEvidence) -> int:
    """Conservatively count *exact* company tokens seen by Tesseract."""
    observed = set()
    for text in evidence.variants:
        observed.update(normalize(text).split())
    return sum(token in observed for token in set(distinct_tokens(company)))


def strengthen_seal(
    company: str,
    tesseract: SealEvidence,
    mask: np.ndarray,
    validator,
    document_mst: str | None = None,
) -> EnsembleEvidence:
    """Invoke optional models with evidence isolation and no model-name prompts.

    Name fallback may PASS with Tesseract evidence or with corroboration
    between Tesseract and PP-OCRv6. The two Paddle pipelines may use the SAME
    text recognition weights, so their agreement ALONE is not independent
    corroboration and cannot promote REVIEW to PASS.
    """
    baseline = compare_name(company, tesseract)
    result = EnsembleEvidence(baseline, tesseract.high_confidence_msts)
    synthetic = seal_as_rgb(mask)
    try:
        general = post_image(synthetic, "general")
    except PaddleUnavailable:
        return result
    try:
        seal = post_image(synthetic, "seal")
    except PaddleUnavailable:
        seal = []
    general_evidence = _group(general, .85)
    seal_evidence = _group(seal, .85)
    general_match = compare_name(company, general_evidence)
    seal_match = compare_name(company, seal_evidence)

    msts = set(tesseract.high_confidence_msts)
    # Paddle's recognition models can share errors; only *two* corroborating
    # sources may add a new MST. A single-source differing code requires REVIEW.
    gen_codes = _codes(general, validator, .90)
    seal_codes = _codes(seal, validator, .90)
    all_codes = msts | gen_codes | seal_codes
    # Any well-formed but different Paddle reading is not proof of a wrong
    # MST, but it is sufficient to forbid an automatic PASS by company name.
    if document_mst and (gen_codes | seal_codes) - {document_mst}:
        return EnsembleEvidence(baseline, frozenset(all_codes), True, True, "MST OCR bất đồng")
    if len(all_codes) > 1:
        return EnsembleEvidence(baseline, frozenset(all_codes), True, True, "MST OCR bất đồng")
    # PP-OCRv6 general and SealRecognition may share the recognition model.
    # Matching Paddle readings on their own cannot create a verified MST.
    # Preserve trusted Tesseract MST evidence and let Paddle only flag conflict.
    if msts and gen_codes and msts != gen_codes:
        return EnsembleEvidence(baseline, frozenset(all_codes), True, True, "MST OCR bất đồng")

    if baseline.matched:
        return EnsembleEvidence(baseline, frozenset(msts), False, True)
    # Independently implemented OCR engines must corroborate a distinctive
    # part of the same seal. Two Paddle calls may share recognition weights.
    tesseract_partial = _independent_tokens(company, tesseract) >= 2
    corroborated = tesseract_partial and (
        general_match.matched or seal_match.matched
    )
    if corroborated:
        # % is token coverage from better fully independent OCR engine.
        best = max((r for r in (general_match, seal_match) if r.matched),
                   key=lambda r: r.match_pct or 0)
        return EnsembleEvidence(best, frozenset(msts), False, True, "NAME_ENSEMBLE")
    return EnsembleEvidence(baseline, frozenset(msts), False, True)
