from app.fields import extract_letterhead_company


def test_multiline_letterhead_tc_is():
    header = (
        "_ TCT TÂN CẢNG SAI GON\n"
        "_CÔNG TY CO PHAN GIẢI PHAP\n"
        "CONG NGHE THONG TIN TAN CANG\n"
        "Số: 9 /KH-TCIS\n"
    )
    assert extract_letterhead_company(header) == (
        "CONG TY CO PHAN GIAI PHAP CONG NGHE THONG TIN TAN CANG"
    )


def test_parent_tct_is_not_assumed_to_be_the_company():
    assert extract_letterhead_company("TCT TAN CANG SAI GON\nSO 05/KH") is None


def test_stops_at_document_number():
    assert extract_letterhead_company("CONG TY TNHH VINH PHUC\nSO 17/KH\nKE HOACH") == (
        "CONG TY TNHH VINH PHUC"
    )


def test_no_company_from_body():
    assert extract_letterhead_company("SO: 17/KH\nKE HOACH\nTO CHUC HOI NGHI") is None
