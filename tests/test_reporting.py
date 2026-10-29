"""Keep Telegram text short without confusing unknown and mismatched MST."""
from unittest.mock import patch

import numpy as np

from app.analysis import Result, analyze_pdf
from app.seal_ocr import SealEvidence, compare_name


def test_name_match_percent_is_evidence_coverage_not_model_confidence():
    evidence = SealEvidence(("TAN CANG CYPRESS",), frozenset())
    result = compare_name("CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS", evidence)
    assert result.matched and result.match_pct == 100


def test_partial_name_evidence_reports_proportion():
    evidence = SealEvidence(("GIAI PHAP NGHE THONG TIN TAN",), frozenset())
    result = compare_name(
        "CÔNG TY CỔ PHẦN GIẢI PHÁP CÔNG NGHỆ THÔNG TIN TÂN CẢNG", evidence
    )
    assert result.matched
    assert result.match_pct == 86  # 6 out of 7 distinctive business-name words


def test_no_evidence_does_not_manufacture_percentage():
    result = compare_name("CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS", SealEvidence((), frozenset()))
    assert not result.matched and result.match_pct is None


def test_name_pass_displays_exact_mst_reason_without_fallback_word():
    result = Result("PASS", "Tên khớp", "NAME_FALLBACK", 2, name_match_pct=86, mst_status="NO_DOC")
    text = result.telegram_html()
    assert "Khớp 86%" in text
    assert "MST: Chưa thấy trên chứng từ" in text
    assert "Dự phòng" not in text
    assert len(text.splitlines()) == 4


def test_ocr_unreadable_mst_is_not_a_mismatch():
    result = Result("PASS", "Tên khớp", "NAME_FALLBACK", 1, name_match_pct=100, mst_status="UNREADABLE")
    text = result.telegram_html()
    assert "MST: Chưa đọc rõ trên dấu" in text
    assert "Không khớp" not in text


def test_mst_mismatch_is_explicit_not_a_name_pass():
    result = Result("FAIL", "MST khác", stamp_page=1, mst_status="MISMATCH")
    assert "MST: <b>Không khớp</b>" in result.telegram_html()
    assert "🏢" not in result.telegram_html()


def test_mst_match_shows_no_fake_name_percentage():
    result = Result("PASS", "MST khớp", "MST_MATCH", 1, mst_status="MATCH")
    assert "MST: <b>Khớp</b>" in result.telegram_html()
    assert "%" not in result.telegram_html()


def test_conflicting_stamp_codes_do_not_pass_via_name():
    class PDF:
        is_pdf = True
        needs_pass = False
        page_count = 1
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def __iter__(self): return iter([object()])

    with (
        patch("app.analysis.fitz.open", return_value=PDF()),
        patch("app.analysis.render_page", return_value=np.zeros((20, 20, 3), np.uint8)),
        patch("app.analysis.detect_stamps", return_value=[(.9, np.zeros((10, 10), np.uint8))]),
        patch("app.analysis.read_document_identity") as get_id,
        patch("app.analysis.read_seal", return_value=SealEvidence(("TAN CANG CYPRESS",), frozenset({"3501556139", "3501556146"}))),
    ):
        from app.document_reader import DocumentIdentity
        get_id.return_value = DocumentIdentity("CONG TY CO PHAN TAN CANG CYPRESS", "3501556139")
        result = analyze_pdf("mock.pdf")
    assert result.status == "REVIEW"
    assert result.mst_status == "CONFLICT"
