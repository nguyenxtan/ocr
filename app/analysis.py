"""Conservative PDF stamp presence and content matching (POC)."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import re
import unicodedata

import cv2
import fitz
import numpy as np
from app.document_reader import read_document_identity
from app.seal_ocr import read_seal, compare_name, strict_name_match


@dataclass(frozen=True)
class Result:
    status: str  # PASS | FAIL | REVIEW
    reason: str
    method: str | None = None
    stamp_page: int | None = None
    name_match_pct: int | None = None
    mst_status: str | None = None

    def telegram_html(self) -> str:
        headings = {
            "PASS": "✅ <b>HỒ SƠ ĐẠT</b>",
            "FAIL": "❌ <b>KHÔNG ĐẠT</b>",
            "REVIEW": "⚠️ <b>CẦN KIỂM TRA</b>",
        }
        lines = [headings[self.status]]
        if self.stamp_page is not None:
            lines.append(f"🔴 Dấu đỏ · Trang {self.stamp_page}")
        elif self.status == "FAIL":
            lines.append(f"🔎 {escape(self.reason)}")
            return "\n".join(lines)
        if self.status == "PASS" and self.method == "NAME_FALLBACK":
            ratio = f" {self.name_match_pct}%" if self.name_match_pct is not None else ""
            lines.append(f"🏢 Tên doanh nghiệp: <b>Khớp{ratio}</b>")
        elif self.status == "REVIEW" and self.stamp_page is not None:
            lines.append(f"🔎 {escape(self.reason)}")
        elif self.status == "FAIL" and self.mst_status != "MISMATCH":
            lines.append(f"🔎 {escape(self.reason)}")
        mst_messages = {
            "MATCH": "🧾 MST: <b>Khớp</b>",
            "MISMATCH": "🧾 MST: <b>Không khớp</b>",
            "NO_DOC": "🧾 MST: Chưa thấy trên chứng từ",
            "UNREADABLE": "🧾 MST: Chưa đọc rõ trên dấu",
            "CONFLICT": "🧾 MST: Có thông tin mâu thuẫn",
        }
        if self.mst_status in mst_messages:
            lines.append(mst_messages[self.mst_status])
        elif self.status == "PASS" and self.method == "MST_MATCH":
            lines.append(mst_messages["MATCH"])
        return "\n".join(lines)

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


def name_matches(company: str, stamp_text: str) -> bool:
    """Strict direct comparison; OCR evidence matching is in app.seal_ocr."""
    return strict_name_match(company, stamp_text)


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


def detect_stamps(rgb: np.ndarray, max_candidates: int = 3) -> list[tuple[float, np.ndarray]]:
    """Return multiple circular-seal candidates using page-relative geometry.

    No fixed page size, fixed stamp location or assumed single seal.
    """
    mask = red_mask(rgb)
    height, width = mask.shape
    short_side = min(height, width)
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(mask, (9, 9), 0),
        cv2.HOUGH_GRADIENT,
        dp=1.4,
        minDist=max(65, int(short_side * 0.07)),
        param1=80,
        param2=30,
        minRadius=max(30, int(short_side * 0.035)),
        maxRadius=max(25, int(short_side * 0.22)),
    )
    if circles is None:
        return []
    scored = []
    for x, y, radius in np.rint(circles[0]).astype(int):
        outer = ring_coverage(mask, x, y, radius)
        if outer < 0.30:
            continue
        inner = max(
            ring_coverage(mask, x, y, round(radius * factor), offsets=(-3, 0, 3))
            for factor in (0.72, 0.78, 0.84)
        )
        score = 0.65 * outer + 0.35 * inner
        if score < 0.35:
            continue
        extent = int(radius * 1.12)
        x0, x1 = max(0, x - extent), min(width, x + extent)
        y0, y1 = max(0, y - extent), min(height, y + extent)
        scored.append((score, mask[y0:y1, x0:x1], x, y, radius))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for score, crop, x, y, radius in scored:
        # Discard duplicate Hough rings around the same physical seal.
        if any((x - px) ** 2 + (y - py) ** 2 < max(radius, pr) ** 2 * 0.5
               for _, _, px, py, pr in selected):
            continue
        selected.append((score, crop, x, y, radius))
        if len(selected) >= max_candidates:
            break
    return [(score, crop) for score, crop, _, _, _ in selected]


def detect_stamp(rgb: np.ndarray) -> tuple[float, np.ndarray | None]:
    """Backward-compatible strongest candidate from one page."""
    candidates = detect_stamps(rgb, max_candidates=1)
    return candidates[0] if candidates else (0.0, None)


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
            candidates: list[tuple[float, np.ndarray, int]] = []
            for index, page in enumerate(doc):
                rgb = render_page(page)
                for score, crop in detect_stamps(rgb, max_candidates=3):
                    candidates.append((score, crop, index + 1))
            candidates.sort(key=lambda item: item[0], reverse=True)
            if not candidates or candidates[0][0] < 0.45:
                return Result("FAIL", "Không phát hiện dấu tròn đỏ.")
            strong = [item for item in candidates if item[0] >= 0.68][:4]
            if not strong:
                return Result("REVIEW", "Vùng nghi có dấu, cần kiểm tra lại.",
                              stamp_page=candidates[0][2])
            best_page = strong[0][2]
            identity = read_document_identity(doc, render_page, extract_document_fields, ocr_lang)
            if identity.ambiguous:
                return Result("REVIEW", "Có nhiều tên doanh nghiệp ở phần đầu chứng từ.",
                              stamp_page=best_page)
            company, doc_mst = identity.company, identity.mst
            if not company:
                return Result("REVIEW", "Chưa đọc được tên doanh nghiệp trên chứng từ.",
                              stamp_page=best_page)
            # Validate EACH likely seal instead of trusting only the strongest circle.
            matched_mst: list[int] = []
            mismatched_mst: list[int] = []
            matched_name: list[tuple[int, int]] = []
            unresolved = False
            for _, seal_mask, stamp_page in strong:
                evidence = read_seal(seal_mask, ocr_lang, tax_code_valid)
                codes = evidence.high_confidence_msts
                if len(codes) > 1:
                    unresolved = True
                    continue
                if doc_mst and len(codes) == 1:
                    seal_mst = next(iter(codes))
                    if seal_mst == doc_mst:
                        matched_mst.append(stamp_page)
                    else:
                        mismatched_mst.append(stamp_page)
                    continue
                name = compare_name(company, evidence)
                if name.matched and name.match_pct is not None:
                    matched_name.append((stamp_page, name.match_pct))
            # Never confuse an unreadable tax code with a mismatched tax code.
            mst_unverified = "UNREADABLE" if doc_mst else "NO_DOC"
            if mismatched_mst and (matched_mst or matched_name or unresolved):
                return Result("REVIEW", "Nhiều dấu có thông tin mâu thuẫn.",
                              stamp_page=mismatched_mst[0], mst_status="CONFLICT")
            if mismatched_mst:
                return Result("FAIL", "MST trên dấu khác MST chứng từ.",
                              stamp_page=mismatched_mst[0], mst_status="MISMATCH")
            if matched_mst:
                return Result("PASS", "MST trên dấu khớp chứng từ.",
                              "MST_MATCH", matched_mst[0], mst_status="MATCH")
            if matched_name and not unresolved:
                page, pct = max(matched_name, key=lambda m: m[1])
                return Result("PASS", "Tên doanh nghiệp trên dấu khớp chứng từ.",
                              "NAME_FALLBACK", page, name_match_pct=pct,
                              mst_status=mst_unverified)
            return Result("REVIEW", "Chưa đối chiếu chắc thông tin trên dấu.",
                          stamp_page=best_page,
                          mst_status="CONFLICT" if unresolved else mst_unverified)
    except (fitz.FileDataError, fitz.EmptyFileError, ValueError):
        return Result("REVIEW", "Không đọc được cấu trúc PDF.")
