"""The crop builder exports JPEG evidence, not whole PDF documents."""
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from app.analysis import Result
from app.evidence import build_evidence, EVIDENCE_FILES


class DummyPage:
    pass


class DummyDoc:
    page_count = 2
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def __getitem__(self, number):
        return DummyPage()


def test_builds_exactly_three_small_crops(tmp_path):
    image = np.full((900, 700, 3), 255, np.uint8)
    cv2.circle(image, (450, 600), 90, (180, 30, 30), 3)
    chosen = (330, 470, 570, 730)
    mask = np.zeros((chosen[3]-chosen[1], chosen[2]-chosen[0]), np.uint8)
    pdf = tmp_path / "upload.pdf"
    pdf.write_bytes(b"%PDF-dummy")
    with (
        patch("app.evidence.fitz.open", return_value=DummyDoc()),
        patch("app.evidence.render_page", return_value=image),
        patch("app.evidence.detect_stamps", return_value=[(.9, mask, chosen)]) as detector,
    ):
        written = build_evidence(pdf, Result("PASS", "OK", stamp_page=2), tmp_path)
    assert written == [name for name, _ in EVIDENCE_FILES]
    detector.assert_called_once()
    assert detector.call_args.kwargs["with_boxes"] is True
    for filename in written:
        data = (tmp_path / filename).read_bytes()
        assert data[:2] == bytes((0xFF, 0xD8))
        assert len(data) < 550_000


def test_does_not_write_without_stamp_page(tmp_path):
    assert build_evidence(tmp_path/"dummy.pdf", Result("FAIL", "no stamp"), tmp_path) == []
    assert not list(tmp_path.glob("proof_*"))


def test_rejects_export_to_arbitrary_directory(tmp_path):
    pdf = tmp_path / "upload.pdf"
    other = tmp_path / "export"
    other.mkdir()
    pdf.write_bytes(b"%PDF-dummy")
    with pytest.raises(ValueError):
        build_evidence(pdf, Result("PASS", "OK", stamp_page=1), other)


def test_real_stamp_detection_returns_box_coordinates():
    from app.analysis import detect_stamps
    image = np.full((700, 700, 3), 255, dtype=np.uint8)
    cv2.circle(image, (350, 350), 95, (190, 35, 35), 4)
    cv2.circle(image, (350, 350), 75, (190, 35, 35), 3)
    detected = detect_stamps(image, max_candidates=2, with_boxes=True)
    assert detected
    score, mask, (left, top, right, bottom) = detected[0]
    assert score >= 0.68
    assert left < 350 < right and top < 350 < bottom
    assert mask.shape == (bottom - top, right - left)


def test_evidence_tracks_the_matching_stamp_not_first_circle(tmp_path):
    from app.analysis import stamp_fingerprint
    pdf = tmp_path / "upload.pdf"
    pdf.write_bytes(b"%PDF-dummy")
    img = np.full((900, 700, 3), 255, np.uint8)
    img[140:300, 120:280] = (50, 150, 70)   # Unrelated circular object region
    img[500:660, 400:560] = (180, 45, 50)  # Matched stamp region
    first = np.zeros((160,160), np.uint8)
    second = np.full((160,160), 140, np.uint8)
    token = stamp_fingerprint(second)
    with (
        patch("app.evidence.fitz.open", return_value=DummyDoc()),
        patch("app.evidence.render_page", return_value=img),
        patch("app.evidence.detect_stamps", return_value=[
            (.94, first, (120,140,280,300)),
            (.85, second, (400,500,560,660)),
        ]),
    ):
        files = build_evidence(pdf, Result("PASS", "OK", stamp_page=1,
                                          stamp_fingerprint=token), tmp_path)
    assert "proof_seal.jpg" in files
    proof = cv2.imdecode(np.frombuffer((tmp_path/"proof_seal.jpg").read_bytes(),
                                      np.uint8), cv2.IMREAD_COLOR)
    # The displayed crop is from the red second object, not the green first.
    center_bgr = proof[proof.shape[0]//2, proof.shape[1]//2].tolist()
    assert center_bgr[2] > center_bgr[1]


def test_selected_stamp_not_found_does_not_show_wrong_proof(tmp_path):
    pdf = tmp_path / "upload.pdf"
    pdf.write_bytes(b"%PDF-dummy")
    img = np.full((700, 700, 3), 255, np.uint8)
    with (
        patch("app.evidence.fitz.open", return_value=DummyDoc()),
        patch("app.evidence.render_page", return_value=img),
        patch("app.evidence.detect_stamps", return_value=[
            (.91, np.zeros((100,100), np.uint8), (150,150,250,250))
        ]),
    ):
        files = build_evidence(
            pdf, Result("PASS", "OK", stamp_page=1, stamp_fingerprint="other_stamp"),
            tmp_path
        )
    assert files == []
    assert not list(tmp_path.glob("proof_*.jpg"))
