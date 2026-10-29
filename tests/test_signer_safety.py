from app.signatories import OCRLine, OCRWord, signature_anchors, candidate_from_line, compare_signer


def line(content, y=800, confidence=94):
    x=100
    words=[]
    for value in content.split():
        words.append(OCRWord(value,x,y,len(value)*12,18,confidence))
        x+=len(value)*12+9
    return OCRLine(tuple(words))


def test_uppercase_printed_name_supported():
    assert candidate_from_line(line('QUAN TUNG ANH', confidence=99))[0] == 'QUAN TUNG ANH'


def test_no_signature_anchor_from_job_field():
    assert not signature_anchors([line('Chức vụ TP KHAI THÁC')])


def test_no_signature_anchor_from_body_heading():
    assert not signature_anchors([line('Chúng tôi đại diện doanh nghiệp đăng ký')])


def test_mild_mismatch_from_ocr_is_review_not_fail():
    assert compare_signer('Quan Tung Anh','Quan Bing enh',90).status == 'UNREADABLE'


def test_clear_different_name_is_mismatch():
    assert compare_signer('Quan Tung Anh','Trần Văn Bình',99).status == 'MISMATCH'


def test_no_reading_not_declared_is_not_positive_match():
    assert compare_signer(None,None,None).status == 'NOT_DECLARED'
