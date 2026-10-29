"""Ephemeral, opt-in visual proof crops for Telegram PDF checking.

Generate only small JPEGs in the same temporary directory as the PDF. The
caller must delete that directory immediately after collecting image bytes.
These regions are inspection aids, not independent verification of identity.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import pymupdf as fitz
import numpy as np

from app.analysis import Result, detect_stamps, render_page, stamp_fingerprint


# Fixed filenames and captions, never supplied by a Telegram user.
EVIDENCE_FILES = (
    ("proof_seal.jpg", "🔴 Vùng con dấu"),
    ("proof_signer.jpg", "✍️ Khu vực ký (tham khảo)"),
    ("proof_header.jpg", "🏢 Phần đầu chứng từ"),
)


def _clamp_box(
    image: np.ndarray, x0: float, y0: float, x1: float, y1: float
) -> tuple[int, int, int, int] | None:
    height, width = image.shape[:2]
    left = max(0, min(width - 1, round(x0)))
    top = max(0, min(height - 1, round(y0)))
    right = max(left + 1, min(width, round(x1)))
    bottom = max(top + 1, min(height, round(y1)))
    if right - left < 12 or bottom - top < 12:
        return None
    return left, top, right, bottom


def _save_jpeg(image: np.ndarray, destination: Path) -> bool:
    """Small image for a Telegram photo; bounded dimensions and bytes."""
    if image.size == 0:
        return False
    height, width = image.shape[:2]
    max_dimension = 1100
    factor = min(1.0, max_dimension / max(height, width))
    if factor < 1.0:
        image = cv2.resize(
            image, (max(1, round(width * factor)), max(1, round(height * factor))),
            interpolation=cv2.INTER_AREA,
        )
    encoded = cv2.imencode(
        ".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
        [cv2.IMWRITE_JPEG_QUALITY, 77],
    )
    success, jpg = encoded
    if not success or len(jpg) > 550_000:
        return False
    destination.write_bytes(jpg.tobytes())
    return True


def build_evidence(pdf: Path, result: Result, output_dir: Path) -> list[str]:
    """Write at most three best-effort crops, only for an identified stamp page.

    No PDF or screenshot is permanently retained. Detection is re-run only on
    the selected page to locate the corresponding stamp pixel rectangle.
    """
    if result.stamp_page is None:
        return []
    if output_dir.resolve() != pdf.parent.resolve():
        raise ValueError("Proof output must stay next to the temporary PDF")
    written: list[str] = []
    with fitz.open(pdf) as doc:
        if not 1 <= result.stamp_page <= doc.page_count:
            return []
        stamp_page = render_page(doc[result.stamp_page - 1])
        detections = detect_stamps(stamp_page, max_candidates=3, with_boxes=True)
        if not detections:
            return []
        if result.stamp_fingerprint is not None:
            detections = [
                candidate for candidate in detections
                if stamp_fingerprint(candidate[1]) == result.stamp_fingerprint
            ]
            if not detections:
                # Never show an unrelated stamp as proof for a matched one.
                return []
        score, _, rect = detections[0]
        x0, y0, x1, y1 = rect
        margin = max(12, int(max(x1 - x0, y1 - y0) * 0.13))
        box = _clamp_box(stamp_page, x0 - margin, y0 - margin, x1 + margin, y1 + margin)
        if box:
            l, t, r, b = box
            if _save_jpeg(stamp_page[t:b, l:r], output_dir / "proof_seal.jpg"):
                written.append("proof_seal.jpg")

        # Show the signing page when it is different from the stamp page.
        # Otherwise show the nearby signing region and mark the detected seal.
        if (result.signer_page is not None
                and 1 <= result.signer_page <= doc.page_count
                and result.signer_page != result.stamp_page):
            signer_page = render_page(doc[result.signer_page - 1])
            h, w = signer_page.shape[:2]
            signed_region = signer_page[round(h * .45):, :]
            if _save_jpeg(signed_region, output_dir / "proof_signer.jpg"):
                written.append("proof_signer.jpg")
        else:
            height, width = stamp_page.shape[:2]
            center_x, center_y = (x0 + x1) / 2, (y0 + y1) / 2
            near_box = _clamp_box(
                stamp_page,
                center_x - width * .43,
                center_y - height * .23,
                center_x + width * .43,
                center_y + height * .23,
            )
            if near_box:
                left, top, right, bottom = near_box
                nearby = stamp_page[top:bottom, left:right].copy()
                cv2.rectangle(
                    nearby, (max(0, x0 - left), max(0, y0 - top)),
                    (min(right-left-1, x1-left), min(bottom-top-1, y1-top)),
                    (25, 135, 220), 3,
                )
                if _save_jpeg(nearby, output_dir / "proof_signer.jpg"):
                    written.append("proof_signer.jpg")

        # First-page heading often contains the issuing business and/or MST.
        # Caption deliberately says "header", not that those fields were read.
        header_page = stamp_page if result.stamp_page == 1 else render_page(doc[0])
        heading = header_page[:round(header_page.shape[0] * .38), :, :]
        if _save_jpeg(heading, output_dir / "proof_header.jpg"):
            written.append("proof_header.jpg")
    return written
