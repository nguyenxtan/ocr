"""Verify that Telegram output distinguishes unreadable and mismatched MST."""

from unittest.mock import patch
import numpy as np
from app.analysis import Result, analyze_pdf
from app.seal_ocr import SealEvidence, compare_name


def test_name_percent_from_stamp_words():
    result = compare_name("CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS",
                          SealEvidence(("TAN CANG CYPRESS",), frozenset()))
    assert result.matched and result.match_pct == 100


def test_partial_stamp_words_have_computed_ratio():
    result = compare_name(
        "CÔNG TY CỔ PHẦN GIẢI PHÁP CÔNG NGHỆ THÔNG TIN TÂN CẢNG",
        SealEvidence(("GIAI PHAP NGHE THONG TIN TAN",), frozenset()),
    )
    assert result.matched and result.match_pct == 86


def test_no_text_does_not_generate_fake_ratio():
    result = compare_name("CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS",
                          SealEvidence((), frozenset()))
    assert not result.matched and result.match_pct is None


def test_pass_message_is_four_lines_without_fallback_word():
    message = Result("PASS", "Tên khớp", "NAME_FALLBACK", 2,
                     name_match_pct=86, mst_status="NO_DOC").telegram_html()
    assert "Khớp 86%" in message
    assert "Chưa thấy trên chứng từ" in message
    assert "Dự phòng" not in message
    assert len(message.splitlines()) == 4


def test_mst_unreadable_never_says_mismatch():
    message = Result("PASS", "Tên khớp", "NAME_FALLBACK", 1,
                     name_match_pct=100, mst_status="UNREADABLE").telegram_html()
    assert "Chưa đọc rõ trên dấu" in message
    assert "Không khớp" not in message


def test_mst_mismatch_is_explicit():
    message = Result("FAIL", "MST khác", stamp_page=1,
                     mst_status="MISMATCH").telegram_html()
    assert "MST: <b>Không khớp</b>" in message


def test_mst_match_does_not_invent_name_percentage():
    message = Result("PASS", "MST khớp", "MST_MATCH", 1,
                     mst_status="MATCH").telegram_html()
    assert "MST: <b>Khớp</b>" in message and "%" not in message


def test_conflicting_mst_prevents_name_pass():
    class PDF:
        is_pdf = True
        needs_pass = False
        page_count = 1
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def __iter__(self): return iter([object()])
    with (
        patch("app.analysis.fitz.open", return_value=PDF()),
        patch("app.analysis.render_page", return_value=np.zeros((20,20,3), np.uint8)),
        patch("app.analysis.detect_stamps", return_value=[(.9, np.zeros((10,10), np.uint8))]),
        patch("app.analysis.read_document_identity") as reader,
        patch("app.analysis.read_seal", return_value=SealEvidence(
            ("TAN CANG CYPRESS",), frozenset({"3501556139", "3501556146"}))),
    ):
        from app.document_reader import DocumentIdentity
        reader.return_value = DocumentIdentity("CONG TY CO PHAN TAN CANG CYPRESS", "3501556139")
        result = analyze_pdf("mock.pdf")
    assert result.status == "REVIEW" and result.mst_status == "CONFLICT"
