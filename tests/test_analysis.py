import cv2
import numpy as np

from app.analysis import Result, detect_stamp, extract_document_fields, name_matches, tax_code_valid


def test_mst_checksum():
    assert tax_code_valid("3501556139")
    assert not tax_code_valid("3501556138")
    assert not tax_code_valid("0909988707")


def test_form_fields():
    text = "Tên doanh nghiệp CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS\nMST doanh nghiệp — 3501556139"
    company, mst = extract_document_fields(text)
    assert company == "CONG TY CO PHAN TAN CANG CYPRESS"
    assert mst == "3501556139"


def test_name_fallback():
    company = "CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS"
    assert name_matches(company, "CÔNG TY COPHAN TÂN CẢNG CYPRESS")
    assert not name_matches(company, "CÔNG TY CỔ PHẦN TÂN CẢNG KHÁC")


def test_only_red_letters_is_not_a_stamp():
    img = np.full((700, 700, 3), 255, np.uint8)
    cv2.putText(img, "TEST RED LETTERS", (50, 340), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (220, 0, 0), 3)
    confidence, _ = detect_stamp(img)
    assert confidence < 0.65


def test_red_circular_stamp():
    img = np.full((700, 700, 3), 255, np.uint8)
    cv2.circle(img, (350, 350), 95, (200, 0, 0), 4)
    cv2.circle(img, (350, 350), 70, (200, 0, 0), 3)
    score, crop = detect_stamp(img)
    assert score >= 0.65
    assert crop is not None


def test_short_reply():
    assert Result("PASS", "Tên khớp", "NAME_FALLBACK").telegram_text() == "✅ PASS\nTên khớp"
