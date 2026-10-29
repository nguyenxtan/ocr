"""Broad deterministic examples; real scanned-PDF accuracy is tested separately."""
import pytest
from app.seal_ocr import SealEvidence, compare_name


@pytest.mark.parametrize('business',[
    'CONG TY CO PHAN TAN CANG CYPRESS',
    'CONG TY CO PHAN MINH PHUC THUONG MAI',
    'CONG TY CO PHAN GIAI PHAP CONG NGHE THONG TIN TAN CANG',
    'CONG TY TNHH VAN TAI DONG NAM ANH',
    'CONG TY CO PHAN DICH VU HANG HAI BIEN DONG',
    'CONG TY TNHH SAN XUAT KINH DOANH SONG DA',
    'CONG TY CO PHAN DAU TU THUONG MAI MINH DUC',
    'CONG TY TNHH HOA CHAT VINH PHAT PHAT TRIEN',
    'CONG TY CO PHAN TAI CHINH PHUONG NAM',
    'CONG TY CO PHAN XAY DUNG CONG TRINH THIEN HA',
])
def test_clearly_mismatched_company_must_not_autopass(business):
    # A red seal of an unrelated company must not become a false positive.
    unrelated = SealEvidence(('CONG TY CO PHAN NGOI SAO PHUONG BAC',),frozenset())
    assert not compare_name(business,unrelated).matched


@pytest.mark.parametrize('business',[
    'CONG TY CO PHAN TAN CANG CYPRESS',
    'CONG TY CO PHAN MINH PHUC THUONG MAI',
    'CONG TY CO PHAN GIAI PHAP CONG NGHE THONG TIN TAN CANG',
    'CONG TY TNHH VAN TAI DONG NAM ANH',
    'CONG TY CO PHAN DICH VU HANG HAI BIEN DONG',
    'CONG TY TNHH SAN XUAT KINH DOANH SONG DA',
    'CONG TY CO PHAN DAU TU THUONG MAI MINH DUC',
    'CONG TY TNHH HOA CHAT VINH PHAT PHAT TRIEN',
    'CONG TY CO PHAN TAI CHINH PHUONG NAM',
    'CONG TY CO PHAN XAY DUNG CONG TRINH THIEN HA',
])
def test_readable_same_company_is_match(business):
    assert compare_name(business,SealEvidence((business,),frozenset())).matched
