"""Signatory extraction must not infer names from the declared field alone."""
from app.signatories import (
    OCRWord, OCRLine, compare_signer, declared_from_lines, candidate_from_line,
    signature_anchors, signer_from_lines, merge_visual_rows,
)
from app.analysis import Result


def row(words, y=300):
    x = 10
    result = []
    for value, confidence in words:
        result.append(OCRWord(value, x, y, len(value) * 10, 15, confidence))
        x += len(value) * 10 + 8
    return OCRLine(tuple(result))


def test_declared_representative_requires_labeled_field():
    line = row([(w, 95) for w in
                "Đại diện có thẩm quyền QUAN TÙNG ANH Chức vụ TP KHAI THÁC".split()])
    assert declared_from_lines([line]) == "QUAN TUNG ANH"
    assert declared_from_lines([row([(w, 95) for w in
                                     "Giám đốc Nguyễn Sơn Hải".split()])]) is None


def test_split_label_and_value_across_ocr_blocks():
    label = row([(w, 95) for w in "Đại diện có thẩm quy".split()])
    name = OCRLine((
        OCRWord("QUAN", 500, 301, 44, 15, 92),
        OCRWord("TÙNG", 551, 301, 50, 15, 95),
        OCRWord("ANH", 607, 301, 40, 15, 91),
    ))
    assert declared_from_lines(merge_visual_rows([label, name], 1684)) == "QUAN TUNG ANH"


def test_printed_name_must_be_in_signature_block():
    anchor = row([(w, 95) for w in "ĐẠI DIỆN KHÁCH HÀNG".split()], y=250)
    name = row([("Quan", 95), ("Tùng", 95), ("Anh", 95)], y=330)
    assert signature_anchors([anchor])
    assert signer_from_lines([anchor, name], 1100, 1600) == ("Quan Tùng Anh", 95)
    assert signer_from_lines([name], 1100, 1600) is None


def test_company_stamp_words_are_not_person_name():
    line = row([("CÔNG", 90), ("TY", 90), ("CỔ", 90), ("PHẦN", 90)])
    assert candidate_from_line(line) is None


def test_unclear_signer_is_not_match_or_mismatch():
    assert compare_signer("QUAN TUNG ANH", "Quan Bing enh", 48).status == "UNREADABLE"


def test_exact_names_match_even_without_accents_spaces():
    assert compare_signer("QUANTUNGANH", "Quan Tùng Anh", 95).status == "MATCH"


def test_confident_different_names_do_not_match():
    assert compare_signer("QUAN TUNG ANH", "Trần Văn Bình", 97).status == "MISMATCH"


def test_unsigned_representative_not_inferred_from_company_document():
    outcome = compare_signer(None, "Nguyễn Sơn Hải", 95)
    assert outcome.status == "NOT_DECLARED"


def test_telegram_prints_match_review_and_difference():
    for value, expected in [
        ("MATCH", "Khớp"),
        ("MISMATCH", "Không khớp"),
        ("UNREADABLE", "Chưa đọc rõ"),
    ]:
        msg = Result("REVIEW", "check", "NAME_FALLBACK", 1,
                     name_match_pct=100, mst_status="UNREADABLE",
                     signer_status=value).telegram_html()
        assert expected in msg


def test_telegram_shows_signer_name_when_no_representative():
    msg = Result("PASS", "stamp ok", "NAME_FALLBACK", 2, name_match_pct=86,
                 mst_status="NO_DOC", signer_status="NOT_DECLARED",
                 signer_name="Nguyen Sơn Hai").telegram_html()
    assert "Nguyen Sơn Hai" in msg and "Chưa đối chiếu" in msg
