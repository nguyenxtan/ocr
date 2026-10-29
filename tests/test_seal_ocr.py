from app.analysis import Result
from app.seal_ocr import SealEvidence, corroborated_name_match, strict_name_match


def test_tc_is_name_from_partial_straightened_text():
    evidence = SealEvidence((
        'CONG TYCO GIA} Pạy NGHỆ AN CẢNG',
        'GIÁI Phản NGHE TONG TAN CẢNG',
        'GIÁI Phản NGHE THone Wy An CẢNG',
    ), frozenset(), frozenset({'GIAI', 'NGHE'}))
    assert corroborated_name_match(
        'CÔNG TY CỔ PHẦN GIẢI PHÁP CÔNG NGHỆ THÔNG TIN TÂN CẢNG', evidence
    )


def test_cypress_name_matches():
    evidence = SealEvidence(('CONG TY CỔ PHẨN TÂN CANG CYPRESS',), frozenset())
    assert corroborated_name_match('CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS', evidence)


def test_no_pass_from_only_shared_parent_name():
    evidence = SealEvidence(('CÔNG TY CỔ PHẦN DỊCH VỤ TÂN CẢNG',), frozenset())
    assert not corroborated_name_match(
        'CÔNG TY CỔ PHẦN GIẢI PHÁP CÔNG NGHỆ THÔNG TIN TÂN CẢNG', evidence
    )


def test_clear_extra_name_word_requires_review():
    expected = 'CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS'
    evidence = SealEvidence(('TAN CANG CYPRESS KHAC',), frozenset(), frozenset({'CYPRESS', 'KHAC'}))
    assert not corroborated_name_match(expected, evidence)
    assert not strict_name_match(expected, 'CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS KHÁC')


def test_telegram_html_compact_pass():
    msg = Result('PASS', 'Tên doanh nghiệp trên dấu khớp chứng từ.', 'NAME_FALLBACK', 2).telegram_html()
    assert '<b>HỒ SƠ ĐẠT</b>' in msg
    assert 'Trang 2' in msg
    assert 'Dự phòng' not in msg
    assert msg.count('\n') == 2


def test_telegram_html_escapes_reason():
    msg = Result('REVIEW', '<script>', stamp_page=2).telegram_html()
    assert '&lt;script&gt;' in msg and '<script>' not in msg


def test_telegram_html_mst_pass():
    msg = Result('PASS', 'MST khớp', 'MST_MATCH', 1).telegram_html()
    assert 'MST' in msg and 'Trang 1' in msg
