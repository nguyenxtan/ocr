"""Conservative PDF stamp presence and content matching (POC)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

import cv2
import fitz
import numpy as np
import pytesseract
from rapidfuzz import fuzz
from app.fields import extract_letterhead_company


@dataclass(frozen=True)
class Result:
    status: str  # PASS | FAIL | REVIEW
    reason: str
    method: str | None = None

    def telegram_text(self) -> str:
        symbol = {"PASS": "✅", "FAIL": "❌", "REVIEW": "⚠️"}[self.status]
        return f"{symbol} {self.status}\n{self.reason}"


def fold(text: str) -> str:
    """Uppercase, drop Vietnamese accents and punctuation for matching only."""
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^A-Z0-9 ]+", " ", "".join(c for c in text if not unicodedata.combining(c)).upper())


def tax_code_valid(value: str) -> bool:
    """VN ten-digit MST checksum. Branch suffixes are outside the POC."""
    if not re.fullmatch(r"\d{10}", value):
        return False
    weights = (31, 29, 23, 19, 17, 13, 7, 5, 3)
    check = 10 - (sum(int(x) * w for x, w in zip(value[:9], weights)) % 11)
    return check == int(value[-1]) and check < 10


def extract_document_fields(text: str) -> tuple[str | None, str | None]:
    """Read labeled fields, not a random phone number or a number on a seal."""
    company = None
    mst = None
    lines = [fold(line).strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        if company is None:
            match = re.search(r"(?:TEN DOANH NGHIEP|TEN CONG TY)\s+(.+)", line)
            if match:
                candidate = match.group(1).strip()
                if len(candidate) >= 8:
                    company = candidate
            elif line in ("TEN DOANH NGHIEP", "TEN CONG TY") and index + 1 < len(lines):
                company = lines[index + 1]
        if mst is None and ("MST DOANH NGHIEP" in line or "MA SO THUE" in line):
            match = re.search(r"\b\d{10}\b", line)
            if match and tax_code_valid(match.group(0)):
                mst = match.group(0)
    return company, mst


LEGAL_WORDS = {
    "CONG", "TY", "CO", "PHAN", "COPHAN", "TNHH", "MTV", "TRACH",
    "NHIEM", "HUU", "HAN", "DOANH", "NGHIEP", "CTCP", "CP",
}


def name_matches(company: str, stamp_text: str) -> bool:
    """Conservative token coverage; a vague shared legal form is not enough."""
    expected = [x for x in fold(company).split() if x not in LEGAL_WORDS and len(x) >= 3]
    observed = [x for x in fold(stamp_text).split() if x not in LEGAL_WORDS and len(x) >= 3]
    if not expected or not observed:
        return False
    hits = [x for x in expected if max(fuzz.ratio(x, y) for y in observed) >= 88]
    # Need a distinctive, relatively long token and enough different tokens.
    has_distinctive = any(len(x) >= 5 for x in hits)
    if len(expected) == 1:
        return len(hits) == 1 and len(expected[0]) >= 5
    return has_distinctive and len(hits) >= 2 and len(hits) / len(expected) >= 0.8


def red_mask(rgb: np.ndarray) -> np.ndarray:
    """Capture faded red/brown stamp ink, not only saturated bright red.

    Scan compression and printer ink often lower saturation considerably.
    Geometry checks below distinguish circular seals from ordinary red text.
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    return cv2.bitwise_or(
        cv2.inRange(hsv, (0, 30, 40), (24, 255, 255)),
        cv2.inRange(hsv, (164, 30, 40), (180, 255, 255)),
    )


def ring_coverage(
    mask: np.ndarray,
    x: int,
    y: int,
    radius: int,
    offsets: tuple[int, ...] = (-8, -4, 0, 4, 8),
) -> float:
    """Fraction of angular sectors supported by red/brown pixels on the rim."""
    height, width = mask.shape
    matched = 0
    for theta in np.linspace(0, 2 * np.pi, 72, endpoint=False):
        for offset in offsets:
            xx = round(x + (radius + offset) * np.cos(theta))
            yy = round(y + (radius + offset) * np.sin(theta))
            if 0 <= xx < width and 0 <= yy < height and mask[yy, xx]:
                matched += 1
                break
    return matched / 72


def detect_stamp(rgb: np.ndarray) -> tuple[float, np.ndarray | None]:
    """Detect faded circular stamps using both the outer and inner ring.

    Scores are heuristic, not calibrated probabilities. A borderline result
    should be reviewed rather than declared definitely stamp-free.
    """
    mask = red_mask(rgb)
    height, width = mask.shape
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(mask, (9, 9), 0),
        cv2.HOUGH_GRADIENT,
        dp=1.4,
        minDist=max(65, int(width * 0.07)),
        param1=80,
        param2=30,
        minRadius=max(30, int(width * 0.035)),
        maxRadius=int(width * 0.14),
    )
    if circles is None:
        return 0.0, None
    best_score, best_crop = 0.0, None
    for x, y, radius in np.rint(circles[0]).astype(int):
        outer = ring_coverage(mask, x, y, radius)
        if outer < 0.30:
            continue
        inner = max(
            ring_coverage(
                mask, x, y, round(radius * factor), offsets=(-3, 0, 3)
            )
            for factor in (0.72, 0.78, 0.84)
        )
        score = 0.65 * outer + 0.35 * inner
        if score <= best_score:
            continue
        extent = int(radius * 1.12)
        x0, x1 = max(0, x - extent), min(width, x + extent)
        y0, y1 = max(0, y - extent), min(height, y + extent)
        best_score = score
        best_crop = mask[y0:y1, x0:x1]
    return best_score, best_crop


def render_page(page: fitz.Page) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()


def analyze_pdf(path: Path, max_pages: int = 10, ocr_lang: str = "vie+eng") -> Result:
    try:
        with fitz.open(path) as doc:
            if not doc.is_pdf:
                return Result("REVIEW", "Tệp không phải PDF hợp lệ.")
            if doc.needs_pass:
                return Result("REVIEW", "PDF có mật khẩu.")
            if doc.page_count == 0 or doc.page_count > max_pages:
                return Result("REVIEW", "Số trang PDF không hợp lệ hoặc vượt giới hạn.")
            best_score, best_mask, best_page = 0.0, None, None
            first_page = None
            for index, page in enumerate(doc):
                rgb = render_page(page)
                if index == 0:
                    first_page = rgb
                score, crop = detect_stamp(rgb)
                if score > best_score:
                    best_score, best_mask, best_page = score, crop, index + 1
            if best_score < 0.45 or best_mask is None:
                return Result("FAIL", "Không phát hiện dấu tròn đỏ.")
            if best_score < 0.68:
                return Result("REVIEW", f"Vùng nghi có dấu ở trang {best_page}, cần kiểm tra.")
            assert first_page is not None
            page_text = pytesseract.image_to_string(first_page, lang=ocr_lang, config="--psm 3")
            company, doc_mst = extract_document_fields(page_text)
            if not company:
                # Official letters often show the company in a multi-line
                # upper-left letterhead, without a labeled company-name field.
                # Crop the issuing entity area so the right-side national
                # header and unrelated companies in the body cannot interfere.
                header = first_page[
                    :int(first_page.shape[0] * 0.18),
                    :int(first_page.shape[1] * 0.48),
                ]
                header_text = pytesseract.image_to_string(
                    header, lang=ocr_lang, config="--psm 6"
                )
                company = extract_letterhead_company(header_text)
            if not company:
                return Result(
                    "REVIEW",
                    f"Có dấu ở trang {best_page}, nhưng chưa đọc được tên doanh nghiệp trên chứng từ.",
                )
            # OCR only red pixels of the seal, avoiding black text underneath.
            only_red = cv2.resize(255 - best_mask, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            stamp_data = pytesseract.image_to_data(
                only_red, lang=ocr_lang, config="--psm 11", output_type=pytesseract.Output.DICT
            )
            words = [(word.strip(), float(conf)) for word, conf in zip(
                stamp_data["text"], stamp_data["conf"]
            ) if word.strip()]
            stamp_text = " ".join(word for word, _ in words)
            strong_codes = set()
            for word, confidence in words:
                digits = re.sub(r"\D", "", word)
                if confidence >= 80 and tax_code_valid(digits):
                    strong_codes.add(digits)
            if doc_mst and len(strong_codes) == 1:
                stamp_mst = next(iter(strong_codes))
                if stamp_mst == doc_mst:
                    return Result("PASS", "MST trên dấu khớp chứng từ.", "MST_MATCH")
                return Result("FAIL", "MST trên dấu không khớp chứng từ.")
            if len(strong_codes) > 1:
                return Result("REVIEW", "Có nhiều MST trên dấu; cần kiểm tra.")
            if name_matches(company, stamp_text):
                return Result("PASS", "Tên doanh nghiệp trên dấu khớp chứng từ.", "NAME_FALLBACK")
            return Result("REVIEW", "Có dấu và tên doanh nghiệp, nhưng chưa đọc chắc thông tin trên dấu.")
    except (fitz.FileDataError, fitz.EmptyFileError, ValueError):
        return Result("REVIEW", "Không đọc được cấu trúc PDF.")
