"""Extract issuing organizations from varied letterhead positions in PDFs."""

from __future__ import annotations

import re
import unicodedata


COMPANY_MARKER = re.compile(
    r"\b(?:TONG CONG TY|TAP DOAN|DOANH NGHIEP TU NHAN|CHI NHANH|CONG TY|CTCP|CTY)\b"
)

STOP_WORDS = re.compile(
    r"^(?:SO\b|CONG HOA\b|DOC LAP\b|KE HOACH\b|THONG BAO\b|"
    r"QUYET DINH\b|KINH GUI\b|CAN CU\b|PHONG\b|NGAY\b|TCT\b|UBND\b)"
)


def normalize(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^A-Z0-9 ]+", " ", "".join(
        c for c in text if not unicodedata.combining(c)
    ).upper()).strip()


def extract_letterhead_company(header_text: str) -> str | None:
    """Find the issuing company, not the parent unit on the line above.

    The caller MUST supply only the upper-left letterhead crop, not the full
    document where a separate company's name may occur in the body.
    """
    lines = [normalize(line) for line in header_text.splitlines()]
    lines = [line for line in lines if line]
    for i, line in enumerate(lines[:9]):
        start = COMPANY_MARKER.search(line)
        if not start:
            continue
        segments = [line[start.start():]]
        for next_line in lines[i + 1:i + 5]:
            if STOP_WORDS.search(next_line) or COMPANY_MARKER.search(next_line) or re.search(r"\d", next_line):
                break
            if len(next_line.split()) < 2:
                break
            segments.append(next_line)
        candidate = " ".join(segments)
        if len(candidate.split()) >= 4:
            return candidate
    return None
