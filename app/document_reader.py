"""Template-independent extraction of the issuing company in PDF forms or letters.

No specific business names, fixed page indices or compulsory top-left positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pytesseract

from app.fields import extract_letterhead_company, normalize


@dataclass(frozen=True)
class DocumentIdentity:
    company: str | None
    mst: str | None
    ambiguous: bool = False


def choose_company(candidates: list[str]) -> tuple[str | None, bool]:
    """Select most complete compatible heading, reject incompatible issuers."""
    unique = list(dict.fromkeys(normalize(x) for x in candidates if x))
    if not unique:
        return None, False
    longest = max(unique, key=lambda x: len(x.split()))
    words = longest.split()
    if all(_ordered_subset(item.split(), words) for item in unique):
        return longest, False
    return None, True


def _ordered_subset(short: list[str], long: list[str]) -> bool:
    it = iter(long)
    return all(any(candidate == token for candidate in it) for token in short)


def header_regions(rgb: np.ndarray):
    """Search a proportional top band across columns, not a single corner."""
    height, width = rgb.shape[:2]
    band = rgb[:max(1, round(height * .33)), :]
    for x0, x1 in ((0, .58), (.42, 1), (.18, .82)):
        region = band[:, round(width * x0):round(width * x1)]
        if region.size:
            yield region


def read_document_identity(
    doc,
    render_page: Callable,
    extract_fields: Callable[[str], tuple[str | None, str | None]],
    lang: str = "vie+eng",
) -> DocumentIdentity:
    """Prioritize labeled form fields, then an unambiguous company letterhead.

    Scans all pages for field labels, and searches top header bands on each page
    until the first page with a recognizable issuer; conflicting names on that
    same page require REVIEW. A PDF text layer is preferred when available.
    """
    header_company: str | None = None
    header_ambiguous = False
    mst: str | None = None
    for page in doc:
        rgb = None
        page_text = page.get_text("text") or ""
        if len(page_text.strip()) < 60:
            rgb = render_page(page)
            page_text = pytesseract.image_to_string(rgb, lang=lang, config="--psm 3")
        company, page_mst = extract_fields(page_text)
        if page_mst and not mst:
            mst = page_mst
        if company:
            return DocumentIdentity(company, mst, False)
        # Avoid scanning body text for company names. Only read headings.
        if header_company or header_ambiguous:
            continue
        if rgb is None:
            rgb = render_page(page)
        possibilities = []
        for region in header_regions(rgb):
            lines = pytesseract.image_to_string(region, lang=lang, config="--psm 6")
            name = extract_letterhead_company(lines)
            if name:
                possibilities.append(name)
        header_company, header_ambiguous = choose_company(possibilities)
    return DocumentIdentity(header_company, mst, header_ambiguous)
