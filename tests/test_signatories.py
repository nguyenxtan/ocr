"""Prevent signer inference from the declaration and unsafe name comparisons."""
from app.signatories import (
    OCRWord, OCRLine, SignerCheck, compare_signer, declared_from_lines,
    candidate_from_line, signature_anchors, signer_from_lines, merge_visual_rows,
)
from app.analysis import Result


def row(words, y=300):
    x = 10
    result = []
    for text, conf in words:
        result.append(OCRWord(text, x, y, len(text) * 10, 15, conf))
        x += len(text) * 10 + 8
    return OCRLine(tuple(result))


def test_extracts_only_explicit_representative_field():
    lines = [row([(w, 95) for w in "Đại diện có thẩm quyền QUAN TÙNG ANH Chức vụ TP KHAI THÁC".split()])]
    assert declared_from_lines(lines) == "QUAN TUNG ANH"
    assert declared_from_lines([row([(w, 95) for w in "Giám đốc Nguyễn Sơn Hải".split()])]) is None


def test_merge_split_ocr_label_and_value():
    label = row([(w, 95) for w in "Đại diện có thẩm quy".split()], y=300)
    value = OCRLine((OCRWord("QUAN", 500, 301, 44, 15, 92),
                     OCRWord("TÙNG", 551, 301, 50, 15, 95),
                     OCRWord("ANH", 607, 301, 40, 15, 91)))
    merged = merge_visual_rows([label, value], 1684)
    assert declared_from_lines(merged) == "QUAN TUNG ANH"


def test_printed_name_in_signature_area_requires_anchor():
    header = row([("ĐẠI", 96), ("DIỆN", 95), ("KHÁCH", 93), ("HÀNG", 96)], y=250)
    printed = row([("Quan", 95), ("Tùng", 95), ("Anh", 95)], y=330)
    assert signature_anchors([header])
    assert signer_from_lines([header, printed], 1100, 1600) == ("Quan Tùng Anh", 95)
    assert signer_from_lines([printed], 1100, 1600) is None


def test_rejects_stamp_words_as_person_name():
    assert candidate_from_line(row([("CÔNG", 90), ("TY", 90), ("CỔ", 90), ("PHẦN", 90)])) is None


def test_weak_handwritten_ocr_is_not_pass_or_fail():
    result = compare_signer("QUAN TUNG ANH", "Quan Bing enh", 48, 1)
    assert result.status == "UNREADABLE"


def test_high_confidence_exact_match_after_accents_and_whitespace():
    result = compare_signer("QUANTUNGANH", "Quan Tùng Anh", 95, 1)
    assert result.status == "MATCH"


def test_high_confidence_mismatch():
    result = compare_signer("QUAN TUNG ANH", "Trần Văn Bình", 97, 1)
    assert result.status == "MISMATCH"


def test_no_declared_representative():
    result = compare_signer(None, "Nguyễn Sơn Hải", 95, 2)
    assert result.status == "NOT_DECLARED"


def test_output_signer_status():
    for code, expected in [
        ("MATCH", "Khớp"), ("MISMATCH", "Không khớp"),
        ("UNREADABLE", "Chưa đọc rõ"),
    ]:
        html = Result("REVIEW", "test", "NAME_FALLBACK", 1,
                      name_match_pct=100, mst_status="UNREADABLE",
                      signer_status=code).telegram_html()
        assert expected in html
    html = Result("PASS", "test", "NAME_FALLBACK", 2,
                  name_match_pct=86, mst_status="NO_DOC",
                  signer_status="NOT_DECLARED", signer_name="Nguyen Sơn Hai").telegram_html()
    assert "Nguyen Sơn Hai" in html


def test_name_check_is_not_disguised_as_legal_authority():
    result = compare_signer("QUAN TUNG ANH", "Quan Tùng Anh", 99)
    assert result.status == "MATCH"  # Only the printed names match.


def test_telegram_shows_actual_signer_name_when_matched():
    html = Result("PASS", "stamp ok", "NAME_FALLBACK", 1,
                  name_match_pct=100, mst_status="UNREADABLE",
                  signer_status="MATCH", signer_name="Quan Tùng Anh").telegram_html()
    assert "Quan Tùng Anh" in html and "<b>Khớp</b>" in html
