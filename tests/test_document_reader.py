from app.document_reader import choose_company, header_regions, read_document_identity
import numpy as np


def test_company_at_right_or_center_header():
    source = np.zeros((1000, 1000, 3), dtype=np.uint8)
    regions = list(header_regions(source))
    assert len(regions) == 3
    assert all(x.shape[0] == 330 for x in regions)
    assert regions[1].shape[1] == 580


def test_choose_longest_compatible_heading():
    company, ambiguous = choose_company([
        "CÔNG TY CỔ PHẦN GIẢI PHÁP",
        "CÔNG TY CỔ PHẦN GIẢI PHÁP CÔNG NGHỆ THÔNG TIN TÂN CẢNG",
    ])
    assert not ambiguous
    assert company.endswith("THONG TIN TAN CANG")


def test_reject_competing_company_names():
    company, ambiguous = choose_company([
        "CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS",
        "CÔNG TY CỔ PHẦN TÂN CẢNG DỊCH VỤ",
    ])
    assert company is None and ambiguous


class MockPage:
    def __init__(self, text):
        self.text = text

    def get_text(self, _: str):
        return self.text


def test_reads_labeled_fields_on_later_page_without_ocr():
    pages = [
        MockPage("Nội dung tài liệu rất dài, không chứa thông tin đăng ký doanh nghiệp. " * 3),
        MockPage("Thông tin mẫu biểu\nTên doanh nghiệp CÔNG TY TNHH MINH AN\nMST doanh nghiệp: 3501556139\n" * 3),
    ]

    def render(_):
        return np.zeros((100, 100, 3), np.uint8)

    def fields(text):
        if "MINH AN" in text:
            return "CONG TY TNHH MINH AN", "3501556139"
        return None, None

    from unittest.mock import patch
    with patch("app.document_reader.pytesseract.image_to_string", return_value=""):
        identity = read_document_identity(pages, render, fields)
    assert identity.company == "CONG TY TNHH MINH AN"
    assert identity.mst == "3501556139"


def test_allows_unknown_company():
    name, ambiguous = choose_company([])
    assert name is None and not ambiguous


def test_read_right_issuer_on_scanned_second_page():
    class Page:
        def get_text(self, _):
            return ""

    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[:100, 250:] = 255

    def mocked_ocr(region, **_):
        return "CÔNG TY TNHH KỸ THUẬT MINH PHÚC" if region.shape[1] < 400 and region.mean() > 80 else ""

    from unittest.mock import patch
    with patch("app.document_reader.pytesseract.image_to_string", side_effect=mocked_ocr):
        identity = read_document_identity([Page(), Page()], lambda _: img, lambda _: (None, None))
    assert identity.company == "CONG TY TNHH KY THUAT MINH PHUC"
    assert not identity.ambiguous


def test_new_types_of_business_headings():
    from app.fields import extract_letterhead_company
    assert extract_letterhead_company("TẬP ĐOÀN PHÁT TRIỂN CÔNG NGHỆ VIỆT\nSố: 01/KH") == (
        "TAP DOAN PHAT TRIEN CONG NGHE VIET"
    )
