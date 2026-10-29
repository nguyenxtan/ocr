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
        assert data.startswith(b"\\xff\\xd8".decode("unicode_escape").encode("latin1"))
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
