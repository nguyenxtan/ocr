"""Conservative PDF stamp presence and content matching (POC)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from hashlib import blake2b
from pathlib import Path
import re
import unicodedata
import os

import cv2
import pymupdf as fitz
import numpy as np
import pytesseract
from rapidfuzz import fuzz
from app.document_reader import read_document_identity
from app.seal_ocr import read_seal, compare_name, strict_name_match
from app.signatories import SignerCheck, inspect_signatures
from app.digital_signatures import inspect_digital_signatures
from app.ensemble import strengthen_seal
from app.paddle_gateway import PaddleUnavailable, post_image, endpoint_from_env


@dataclass(frozen=True)
class Result:
    status: str  # PASS | FAIL | REVIEW
    reason: str
    method: str | None = None
    stamp_page: int | None = None
    name_match_pct: int | None = None
    mst_status: str | None = None  # MATCH | MISMATCH | NO_DOC | UNREADABLE | CONFLICT
    signer_status: str | None = None
    signer_name: str | None = None
    signer_page: int | None = None
    stamp_fingerprint: str | None = None
    digital_signature: str | None = None
    digital_trusted: bool | None = None

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
            if self.digital_signature in ("VALID_CRYPTO", "UNVERIFIED", "INVALID"):
                lines.append("🔏 Chữ ký số: Có · Không thay thế dấu đỏ")
            return "\n".join(lines)

        if self.method in ("NAME_FALLBACK", "NAME_ENSEMBLE"):
            ratio = (
                f" {self.name_match_pct}%" if self.name_match_pct is not None else ""
            )
            lines.append(f"🏢 Tên doanh nghiệp: <b>Khớp{ratio}</b>")
        # An inconclusive result MUST explain itself, even without a stamp page.
        # This was why timeout/errors previously rendered only "CẦN KIỂM TRA".
        if self.status in ("REVIEW", "FAIL"):
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
        signer_labels = {
            "MATCH": "✍️ Người ký: <b>Khớp</b> tên đại diện",
            "MISMATCH": "✍️ Người ký: <b>Không khớp</b> tên đại diện",
            "UNREADABLE": "✍️ Người ký: Chưa đọc rõ để đối chiếu",
            "NOT_DECLARED": "✍️ Người ký: Chưa có đại diện để đối chiếu",
        }
        if self.signer_status == "NOT_DECLARED" and self.signer_name:
            lines.append(f"✍️ Người ký: {escape(self.signer_name)} · Chưa đối chiếu")
        elif self.signer_status in ("MATCH", "MISMATCH") and self.signer_name:
            result = "Khớp" if self.signer_status == "MATCH" else "Không khớp"
            lines.append(f"✍️ Người ký: {escape(self.signer_name)} · <b>{result}</b>")
        elif self.signer_status in signer_labels:
            lines.append(signer_labels[self.signer_status])
        if self.digital_signature in ("VALID_CRYPTO", "UNVERIFIED", "INVALID"):
            if self.digital_signature == "INVALID":
                lines.append("🔏 Chữ ký số: Có · Không toàn vẹn")
            elif self.digital_signature == "VALID_CRYPTO" and self.digital_trusted is True:
                lines.append("🔏 Chữ ký số: Toàn vẹn · Chứng thư tin cậy")
            elif self.digital_signature == "VALID_CRYPTO":
                lines.append("🔏 Chữ ký số: Toàn vẹn · Chưa xác thực chứng thư")
            else:
                lines.append("🔏 Chữ ký số: Có · Chưa xác minh")
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


LEGAL_WORDS = {
    "CONG", "TY", "CO", "PHAN", "COPHAN", "TNHH", "MTV", "TRACH",
    "NHIEM", "HUU", "HAN", "DOANH", "NGHIEP", "CTCP", "CP",
}


def name_matches(company: str, stamp_text: str) -> bool:
    """Strict direct comparison; OCR evidence matching is in app.seal_ocr."""
    return strict_name_match(company, stamp_text)


def red_mask(rgb):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    # Ink on scanned paper frequently looks faded pink or brown rather than saturated red.
    return cv2.bitwise_or(
        cv2.inRange(hsv, (0, 30, 40), (24, 255, 255)),
        cv2.inRange(hsv, (164, 30, 40), (180, 255, 255)),
    )

def ring_coverage(mask, x, y, radius, offsets=(-8,-4,0,4,8)):
    height, width = mask.shape
    matched = 0
    for theta in np.linspace(0, 2*np.pi, 72, endpoint=False):
        for offset in offsets:
            xx = round(x+(radius+offset)*np.cos(theta))
            yy = round(y+(radius+offset)*np.sin(theta))
            if 0<=xx<width and 0<=yy<height and mask[yy,xx]:
                matched += 1
                break
    return matched / 72

def detect_ellipse_circles(mask: np.ndarray) -> list[tuple[float, np.ndarray, int, int, int, tuple[int, int, int, int]]]:
    """Fallback for distorted scanned circular seals that appear elliptical."""
    height, width = mask.shape
    min_radius = max(30, int(min(height, width) * .035))
    max_radius = max(25, int(min(height, width) * .22))
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    scored = []
    for contour in contours:
        if len(contour) < 50:
            continue
        (x, y), (diameter1, diameter2), angle = cv2.fitEllipse(contour)
        major, minor = max(diameter1, diameter2), min(diameter1, diameter2)
        if minor <= 0 or major / minor > 2.0:
            continue
        radius = (major + minor) / 4
        if not min_radius <= radius <= max_radius:
            continue
        # Contours must resemble a ring, not a compact red text glyph.
        contour_length = cv2.arcLength(contour, True)
        if contour_length < 3.0 * (major + minor) / 2:
            continue
        theta = np.linspace(0, 2 * np.pi, 72, endpoint=False)
        alpha = np.deg2rad(angle)
        def coverage(factor: float) -> float:
            count = 0
            for t in theta:
                dx = (diameter1 / 2) * factor * np.cos(t)
                dy = (diameter2 / 2) * factor * np.sin(t)
                xx = round(x + dx * np.cos(alpha) - dy * np.sin(alpha))
                yy = round(y + dx * np.sin(alpha) + dy * np.cos(alpha))
                y0, y1 = max(0, yy - 4), min(height, yy + 5)
                x0, x1 = max(0, xx - 4), min(width, xx + 5)
                if x0 < x1 and y0 < y1 and np.any(mask[y0:y1, x0:x1]):
                    count += 1
            return count / len(theta)
        outer = coverage(1)
        inner = max(coverage(f) for f in (.72, .78, .84))
        score = .65 * outer + .35 * inner
        if score < .55:
            continue
        extent = round(max(diameter1, diameter2) * .58)
        x0, x1 = max(0, round(x) - extent), min(width, round(x) + extent)
        y0, y1 = max(0, round(y) - extent), min(height, round(y) + extent)
        crop = mask[y0:y1, x0:x1]
        if crop.size == 0 or cv2.countNonZero(crop) / crop.size > .55:
            continue
        scored.append((score, crop, round(x), round(y), round(radius), (x0, y0, x1, y1)))
    return scored


def detect_stamps(rgb: np.ndarray, max_candidates: int = 3, *, with_boxes: bool = False) -> list[tuple]:
    """Return multiple candidate circular seals, ordered by geometry evidence.

    Geometric ratios are relative to the page dimensions so both portrait and
    landscape PDFs work without knowing page size or scan resolution.
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
    scored = []
    if circles is None:
        circles = np.empty((1, 0, 3), dtype=np.float32)
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
        scored.append((score, mask[y0:y1, x0:x1], x, y, radius, (x0, y0, x1, y1)))
    # Try elliptical rings only if the ordinary circular detector is uncertain.
    if not scored or max(item[0] for item in scored) < .68:
        scored.extend(detect_ellipse_circles(mask))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = []
    for score, crop, x, y, radius, box in scored:
        # Skip duplicate Hough rings around the very same physical seal.
        if any((x - px) ** 2 + (y - py) ** 2 < max(radius, pr) ** 2 * 0.5
               for _, _, px, py, pr, _ in selected):
            continue
        selected.append((score, crop, x, y, radius, box))
        if len(selected) >= max_candidates:
            break
    if with_boxes:
        return [(score, crop, box) for score, crop, _, _, _, box in selected]
    return [(score, crop) for score, crop, _, _, _, _ in selected]


def detect_stamp(rgb):
    """Compatibility wrapper for the strongest candidate on a page."""
    results = detect_stamps(rgb, max_candidates=1)
    return results[0] if results else (0.0, None)


def stamp_fingerprint(mask: np.ndarray) -> str:
    """Stable fingerprint of the exact red-ink pixels used for comparison."""
    return blake2b(mask.tobytes(), digest_size=8).hexdigest()


def render_page(page: fitz.Page) -> np.ndarray:
    max_pixels = 6_000_000
    width, height = page.rect.width, page.rect.height
    if width <= 0 or height <= 0 or width * height > max_pixels * 4:
        raise ValueError("PDF page geometry exceeds safe rendering limits")
    scale = min(2.0, (max_pixels / (width * height)) ** 0.5)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()


def check_signer_for_pass(result: Result, doc, ocr_lang: str) -> Result:
    """Apply signer comparison when a declared authorized representative exists.

    For documents with no such field, retain stamp result but report the missing
    cross-reference. Never silently mark an unreadable signer as matching.
    """
    signature = inspect_signatures(doc, render_page, ocr_lang)
    updated = replace(result, signer_status=signature.status, signer_name=signature.signed,
                      signer_page=signature.page)
    if signature.status == "MISMATCH":
        return replace(updated, status="FAIL", reason="Người ký không khớp đại diện khai báo.")
    if signature.status == "UNREADABLE":
        return replace(updated, status="REVIEW", reason="Chưa đọc chắc tên người ký.")
    return updated


def analyze_pdf(path: Path, max_pages: int = 10, ocr_lang: str = "vie+eng") -> Result:
    """Match physical seal fields; report digital PDF signature separately."""
    result = _analyze_stamp_pdf(path, max_pages, ocr_lang)
    signature = inspect_digital_signatures(path)
    if signature.status == "INVALID" and result.status == "PASS":
        result = replace(result, status="REVIEW", reason="Chữ ký số nhúng không toàn vẹn.")
    return replace(result, digital_signature=signature.status,
                   digital_trusted=signature.trusted)


def _analyze_stamp_pdf(path: Path, max_pages: int = 10, ocr_lang: str = "vie+eng") -> Result:
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
            engine = os.getenv("OCR_ENGINE", "tesseract").lower()
            enable_paddle = engine == "ensemble" and endpoint_from_env() is not None
            def remote_general(region):
                try:
                    return post_image(region, "general")
                except PaddleUnavailable:
                    return []
            if enable_paddle:
                identity = read_document_identity(doc, render_page, extract_document_fields,
                                                  ocr_lang, remote_general=remote_general)
            else:
                identity = read_document_identity(doc, render_page, extract_document_fields, ocr_lang)
            if identity.ambiguous:
                return Result("REVIEW", "Có nhiều tên doanh nghiệp ở phần đầu chứng từ.", stamp_page=best_page)
            company, doc_mst = identity.company, identity.mst
            if not company:
                return Result("REVIEW", "Chưa đọc được tên doanh nghiệp trên chứng từ.", stamp_page=best_page)
            # Verify each likely seal, rather than assuming the strongest
            # circle is the one identifying the issuing company.
            matched_mst: list[tuple[int, str]] = []
            mismatched_mst: list[tuple[int, str]] = []
            matched_name: list[tuple[int, int, str, str]] = []
            unresolved = False
            for index, (_, seal_mask, stamp_page) in enumerate(strong):
                fingerprint = stamp_fingerprint(seal_mask)
                evidence = read_seal(seal_mask, ocr_lang, tax_code_valid)
                name_method = "NAME_FALLBACK"
                if enable_paddle and index < 2:
                    crosscheck = strengthen_seal(company, evidence, seal_mask, tax_code_valid,
                                                 document_mst=doc_mst)
                    codes = crosscheck.msts
                    match = crosscheck.name
                    if crosscheck.ambiguous:
                        unresolved = True
                        continue
                    if crosscheck.note == "NAME_ENSEMBLE":
                        name_method = "NAME_ENSEMBLE"
                else:
                    codes = evidence.high_confidence_msts
                    match = compare_name(company, evidence)
                if len(codes) > 1:
                    unresolved = True
                    continue
                if doc_mst and len(codes) == 1:
                    seal_mst = next(iter(codes))
                    if seal_mst == doc_mst:
                        matched_mst.append((stamp_page, fingerprint))
                    else:
                        mismatched_mst.append((stamp_page, fingerprint))
                    continue
                if match.matched and match.match_pct is not None:
                    matched_name.append((stamp_page, match.match_pct, name_method, fingerprint))
            # Do not treat an unreadable MST as a mismatch.
            mst_unverified = "UNREADABLE" if doc_mst else "NO_DOC"
            if mismatched_mst and (matched_mst or matched_name or unresolved):
                return Result("REVIEW", "Nhiều dấu có thông tin mâu thuẫn.",
                              stamp_page=mismatched_mst[0][0], mst_status="CONFLICT",
                              stamp_fingerprint=mismatched_mst[0][1])
            if mismatched_mst:
                return Result("FAIL", "MST trên dấu khác MST chứng từ.",
                              stamp_page=mismatched_mst[0][0], mst_status="MISMATCH",
                              stamp_fingerprint=mismatched_mst[0][1])
            if matched_mst:
                page, fingerprint = matched_mst[0]
                result = Result("PASS", "MST trên dấu khớp chứng từ.",
                                "MST_MATCH", page, mst_status="MATCH",
                                stamp_fingerprint=fingerprint)
                return check_signer_for_pass(result, doc, ocr_lang)
            if matched_name and not unresolved:
                page, match_pct, method, fingerprint = max(matched_name, key=lambda m: m[1])
                result = Result("PASS", "Tên doanh nghiệp trên dấu khớp chứng từ.",
                                method, page,
                                name_match_pct=match_pct, mst_status=mst_unverified,
                                stamp_fingerprint=fingerprint)
                return check_signer_for_pass(result, doc, ocr_lang)
            return Result("REVIEW", "Chưa đối chiếu chắc thông tin trên dấu.",
                          stamp_page=best_page,
                          mst_status="CONFLICT" if unresolved else mst_unverified)
    except (fitz.FileDataError, fitz.EmptyFileError, ValueError):
        return Result("REVIEW", "Không đọc được cấu trúc PDF.")
