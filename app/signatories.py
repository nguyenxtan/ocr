"""Compare a declared representative with independently read printed signer names.

Do not infer legal authority from a title/stamp. A handwritten flourish is not
machine-readable proof of a name; low-confidence OCR must remain UNREADABLE.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from itertools import islice
import os
from dataclasses import dataclass
from typing import Callable
import re
import unicodedata

import numpy as np
import pytesseract
from rapidfuzz import fuzz


@dataclass(frozen=True)
class OCRWord:
    text: str
    x: int
    y: int
    w: int
    h: int
    confidence: float


@dataclass(frozen=True)
class OCRLine:
    words: tuple[OCRWord, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x(self) -> int:
        return min(w.x for w in self.words)

    @property
    def y(self) -> int:
        return min(w.y for w in self.words)

    @property
    def right(self) -> int:
        return max(w.x + w.w for w in self.words)

    @property
    def bottom(self) -> int:
        return max(w.y + w.h for w in self.words)


@dataclass(frozen=True)
class SignerCheck:
    status: str  # MATCH | MISMATCH | UNREADABLE | NOT_DECLARED
    declared: str | None = None
    signed: str | None = None
    page: int | None = None

    @property
    def label(self) -> str:
        labels = {
            "MATCH": "✍️ Người ký: <b>Khớp</b>",
            "MISMATCH": "✍️ Người ký: <b>Không khớp</b>",
            "UNREADABLE": "✍️ Người ký: Chưa đọc rõ để đối chiếu",
            "NOT_DECLARED": "✍️ Người ký: Chưa có tên đại diện để đối chiếu",
        }
        return labels[self.status]


def normalize(value: str) -> str:
    value = value.replace("đ", "d").replace("Đ", "D")
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"[^A-Z0-9 ]", " ", "".join(
        c for c in value if not unicodedata.combining(c)
    ).upper()).strip()


def compact_name(text: str) -> str:
    return re.sub(r"\s+", "", normalize(text))


def ocr_lines(img: np.ndarray, lang: str, psm: int) -> list[OCRLine]:
    data = pytesseract.image_to_data(
        img, lang=lang, config=f"--psm {psm}",
        output_type=pytesseract.Output.DICT, timeout=12,
    )
    grouped: dict[tuple[int, int, int], list[OCRWord]] = {}
    for i, text in enumerate(data["text"]):
        if not str(text).strip():
            continue
        word = OCRWord(
            str(text).strip(), int(data["left"][i]), int(data["top"][i]),
            int(data["width"][i]), int(data["height"][i]),
            float(data["conf"][i]),
        )
        key = (int(data["block_num"][i]), int(data["par_num"][i]),
               int(data["line_num"][i]))
        grouped.setdefault(key, []).append(word)
    return sorted((OCRLine(tuple(sorted(words, key=lambda w: w.x)))
                   for words in grouped.values()), key=lambda line: (line.y, line.x))


REPRESENTATIVE_LABELS = (
    re.compile(r"\bDAI DIEN CO THAM QUY(?:EN)?\b"),
    re.compile(r"\bNGUOI DUOC UY QUYEN\b"),
    re.compile(r"\bHO TEN NGUOI DAI DIEN\b"),
)


def declared_from_lines(lines: list[OCRLine]) -> str | None:
    """Extract only a specifically labeled representative, never a person in body."""
    for line in lines:
        norm = normalize(line.text)
        marker = next((match for pattern in REPRESENTATIVE_LABELS
                       if (match := pattern.search(norm))), None)
        if not marker:
            continue
        tail = norm[marker.end():]
        tail = re.split(r"\b(?:CHUC VU|SO CMND|SO CHUNG MINH|THEO BAN UY QUYEN|NGAY KY)\b", tail)[0]
        tail = re.sub(r"\b(?:K Y|DAI DIEN|\d+)\b", " ", tail).strip()
        words = [w for w in tail.split() if len(w) > 1]
        if 2 <= len(words) <= 5 and sum(map(len, words)) >= 7:
            return " ".join(words)
        if len(words) == 1 and len(words[0]) >= 8 and words[0].isalpha():
            return words[0]
    return None



def merge_visual_rows(lines: list[OCRLine], height: int) -> list[OCRLine]:
    """Join sparse OCR blocks lying on one visual baseline (form label + value)."""
    groups: list[list[OCRWord]] = []
    rows: list[float] = []
    tolerance = max(4, height * 0.008)
    for line in sorted(lines, key=lambda v: (v.y + v.bottom) / 2):
        center = (line.y + line.bottom) / 2
        slot = next((i for i, value in enumerate(rows)
                     if abs(center - value) <= tolerance), None)
        if slot is None:
            groups.append(list(line.words))
            rows.append(center)
        else:
            groups[slot].extend(line.words)
    return [OCRLine(tuple(sorted(group, key=lambda w: w.x))) for group in groups]

SIGNATURE_TITLES = (
    "DAI DIEN KHACH HANG", "DAI DIEN DOANH NGHIEP",
    "NGUOI KY", "GIAM DOC", "GIAM BOC", "TONG GIAM DOC",
    "CHU TICH", "THU TRUONG",
)
EXCLUDED_NAME_WORDS = frozenset({
    "CONG", "TY", "PHAN", "CO", "GIAM", "DOC", "BOC", "THONG", "TIN",
    "THAC", "KHAI", "CANG", "CANH",
    "DUNG", "CHUC", "KY", "GHI", "TEN", "NGAY", "THANG", "NAM",
})
RANK_PREFIXES = frozenset({"THUONG", "TRUNG", "THIEU", "DAI", "TA", "UY", "ONG", "BA"})


def signature_anchors(lines: list[OCRLine]) -> list[OCRLine]:
    """Only distinct signing-block titles, not job titles in the body/form."""
    result = []
    for line in lines:
        norm = normalize(line.text)
        if "DE PHE DUYET" in norm or "DE BAO CAO" in norm:
            continue
        if norm.startswith(("DAI DIEN KHACH HANG", "DAI DIEN DOANH NGHIEP")):
            result.append(line)
            continue
        if norm in ("GIAM DOC", "GIAM BOC", "TONG GIAM DOC", "CHU TICH",
                    "THU TRUONG", "NGUOI KY"):
            result.append(line)
            continue
        if len(norm.split()) <= 3 and max(
            fuzz.ratio(norm, title) for title in ("GIAM DOC", "CHU TICH", "TONG GIAM DOC")
        ) >= 80:
            result.append(line)
    return result


def candidate_from_line(line: OCRLine) -> tuple[str, float] | None:
    """A printed person name immediately beneath a signing title.

    Mixed case and OCR confidence discriminate names from uppercase stamp text.
    """
    words = list(line.words)
    while words and normalize(words[0].text) in RANK_PREFIXES:
        words.pop(0)
    if not 2 <= len(words) <= 4:
        return None
    normalized = [normalize(w.text) for w in words]
    if any(not value.isalpha() or len(value) < 2 for value in normalized):
        return None
    if any(value in (EXCLUDED_NAME_WORDS - {"QUAN"}) for value in normalized):
        return None
    titlecase = sum(word.text[:1].isupper() and any(c.islower() for c in word.text)
                    for word in words)
    uppercase_name = (len(words) >= 3 and
                      all(normalize(w.text) == w.text for w in words) and
                      min(w.confidence for w in words) >= 85)
    if titlecase < min(2, len(words)) and not uppercase_name:
        return None
    return " ".join(w.text for w in words), min(w.confidence for w in words)


def signer_from_lines(lines: list[OCRLine], width: int, height: int) -> tuple[str, float] | None:
    anchors = signature_anchors(lines)
    candidates: list[tuple[float, str, float]] = []
    for anchor in anchors:
        cx = (anchor.x + anchor.right) / 2
        for line in lines:
            if anchor.y < height * .12:
                continue
            if not 0 <= line.y - anchor.bottom <= height * .26:
                continue
            signer_cx = (line.x + line.right) / 2
            if abs(signer_cx - cx) > width * .22:
                continue
            picked = candidate_from_line(line)
            if picked is None:
                continue
            name, confidence = picked
            # Prefer the closest printed name after its signature title.
            gap = (line.y - anchor.bottom) / height
            rank = confidence - gap * 30
            candidates.append((rank, name, confidence))
    if not candidates:
        return None
    _, name, confidence = max(candidates, key=lambda value: value[0])
    return name, confidence


def compare_signer(declared: str | None, signed: str | None,
                   confidence: float | None, page: int | None = None) -> SignerCheck:
    if not declared:
        return SignerCheck("NOT_DECLARED", signed=signed, page=page)
    if not signed or confidence is None or confidence < 85:
        return SignerCheck("UNREADABLE", declared=declared, signed=signed, page=page)
    # High-confidence independent OCR only. OCR artifacts must not become FAIL.
    if compact_name(declared) == compact_name(signed):
        return SignerCheck("MATCH", declared=declared, signed=signed, page=page)
    if confidence < 95:
        return SignerCheck("UNREADABLE", declared=declared, signed=signed, page=page)
    return SignerCheck("MISMATCH", declared=declared, signed=signed, page=page)


def inspect_signatures(doc, render_page: Callable,
                      lang: str = "vie+eng") -> SignerCheck:
    """Run identical page OCR in batches of at most two independent subprocesses.

    PyMuPDF rendering stays on the caller thread. Results are consumed in page
    order, with the same extraction rules/thresholds as sequential processing.
    The bounded batches avoid retaining all rendered pages in memory.
    """
    workers = int(os.getenv("SIGNER_OCR_WORKERS", "2"))
    if workers not in (1, 2):
        raise ValueError("SIGNER_OCR_WORKERS must be 1 or 2")
    declared = None
    candidates = []
    pages = enumerate(doc, start=1)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while True:
            batch = []
            for page_number, page in islice(pages, workers):
                image = render_page(page)
                future = executor.submit(ocr_lines, image, lang, 11)
                batch.append((page_number, image.shape, future))
            if not batch:
                break
            for page_number, shape, future in batch:
                sparse = future.result()
                if not declared:
                    declared = declared_from_lines(merge_visual_rows(sparse, shape[0]))
                signed = signer_from_lines(sparse, shape[1], shape[0])
                if signed:
                    candidates.append((signed[1], signed[0], page_number))
    if not candidates:
        return compare_signer(declared, None, None)
    confidence, name, page = max(candidates)
    return compare_signer(declared, name, confidence, page)
