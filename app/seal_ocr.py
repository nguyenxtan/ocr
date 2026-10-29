"""OCR of stamp-only red ink, with cropped variants for difficult curved text."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

import cv2
import numpy as np
import pytesseract
from rapidfuzz import fuzz


GENERIC = {
    "CONG", "TY", "CO", "PHAN", "COPHAN", "TNHH", "MTV", "TRACH",
    "NHIEM", "HUU", "HAN", "DOANH", "NGHIEP", "CTCP", "CP",
}


def normalize(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9 ]", " ", value.upper())


def distinct_tokens(value: str) -> list[str]:
    return [x for x in normalize(value).split() if x not in GENERIC and len(x) >= 3]


def strict_name_match(expected: str, observed: str) -> bool:
    """Conservative name comparison for readable, non-noisy strings."""
    target = distinct_tokens(expected)
    found = distinct_tokens(observed)
    if not target or not found:
        return False
    exact = [x for x in target if x in found]
    return (len(exact) == len(target) and len(found) == len(target)
            and len(set(found)) == len(set(target)))


@dataclass(frozen=True)
class SealEvidence:
    variants: tuple[str, ...]
    high_confidence_msts: frozenset[str]
    strong_central_tokens: frozenset[str] = frozenset()


def read_seal(mask: np.ndarray, lang: str, tax_code_valid) -> SealEvidence:
    """Read red pixels only; center crops reduce circular lettering interference.

    Uses five passes of the existing on-device Tesseract; no external AI and
    never copies the PDF document name into the stamp OCR result.
    """
    side = min(mask.shape[:2])
    mid_y, mid_x = mask.shape[0] // 2, mask.shape[1] // 2
    # Crop fractions refer to the radius of the *selected stamp crop*.
    settings = [(1.00, 11), (0.51, 6), (0.56, 6), (0.72, 6), (0.82, 6)]
    variants: list[str] = []
    codes: set[str] = set()
    central_tokens: set[str] = set()
    for fraction, psm in settings:
        radius = max(1, int(side * 0.5 * fraction))
        piece = mask[max(0, mid_y - radius):mid_y + radius,
                     max(0, mid_x - radius):mid_x + radius]
        black_on_white = cv2.resize(255 - piece, None, fx=3, fy=3,
                                    interpolation=cv2.INTER_CUBIC)
        if fraction == 0.72:
            black_on_white = cv2.dilate(black_on_white, np.ones((2, 2), np.uint8))
        if fraction == 0.82:
            black_on_white = cv2.erode(black_on_white, np.ones((2, 2), np.uint8))
        rows = pytesseract.image_to_data(black_on_white, lang=lang,
                config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
        words = [(str(text).strip(), float(conf))
                 for text, conf in zip(rows["text"], rows["conf"])
                 if str(text).strip()]
        variants.append(" ".join(word for word, _ in words))
        for word, confidence in words:
            if fraction <= 0.56 and confidence >= 80:
                central_tokens.update(
                    token for token in normalize(word).split()
                    if token.isalpha() and len(token) >= 4
                )
            digits = re.sub(r"\D", "", word)
            if confidence >= 80 and tax_code_valid(digits):
                codes.add(digits)
    return SealEvidence(tuple(variants), frozenset(codes), frozenset(central_tokens))


def corroborated_name_match(company: str, evidence: SealEvidence) -> bool:
    """Match substantial distinctive tokens observed on the same seal.

    Fuzzy tolerance only handles OCR glitches (PHAN/PHAP, THONE/THONG).
    Missing substantive parts or only generic legal words never yield PASS.
    """
    expected = distinct_tokens(company)
    if len(expected) < 2:
        return False
    found = set()
    for variant in evidence.variants:
        found.update(x for x in normalize(variant).split() if len(x) >= 3)
    hits = []
    for token in expected:
        threshold = 100 if len(token) <= 3 else 75 if len(token) == 4 else 78
        if any(fuzz.ratio(token, candidate) >= threshold for candidate in found):
            hits.append(token)
    # Do not silently accept a clearly recognized extra company-name word.
    # Restrict this guard to high-confidence *central* OCR, excluding ring
    # addresses and the noisy outer lettering.
    for word in evidence.strong_central_tokens - GENERIC:
        if not any(fuzz.ratio(word, part) >= 88 or word in part for part in expected):
            return False
    coverage = len(hits) / len(expected)
    distinct_long = sum(len(token) >= 4 for token in set(hits))
    return coverage >= 0.8 and distinct_long >= 1 and len(hits) >= min(3, len(expected))
