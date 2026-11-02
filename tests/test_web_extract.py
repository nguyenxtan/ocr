import fitz
import pytest
from app.web_extract import classify, extract, usable_text


def pdf(tmp_path, pages):
    p = tmp_path / 'test.pdf'
    with fitz.open() as doc:
        for text in pages:
            page = doc.new_page()
            page.insert_text((40, 50), text, fontsize=11)
        doc.save(p)
    return p


def test_classifies_content_not_filename():
    assert classify('GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep') == 'gpkd'
    assert classify('BAN DANG KY SU DUNG CANG DIEN TU E-PORT\nThong tin doanh nghiep') == 'eport'
    assert classify('EPORT MOC PHAT.pdf') == 'unknown'
    assert classify('GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nBAN DANG KY SU DUNG EPORT') == 'unknown'


def test_encoding_quality():
    assert usable_text('Ten doanh nghiep CONG TY ALPHA ' * 4)
    assert not usable_text('\ufffd' * 100)
    assert not usable_text('(cid:123)' * 30)


def test_sources_and_separate_owner_legal_on_later_page(tmp_path):
    p = pdf(tmp_path, ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789\nTen cong ty viet bang tieng Viet: CONG TY ALPHA',
                        '4. Thong tin ve chu so huu\nHo va ten: NGUYEN VAN A\n5. Nguoi dai dien theo phap luat\nHo va ten: TRAN THI B'])
    d = extract(p, 'gpkd')
    assert d['detected_kind'] == 'gpkd'
    assert d['fields']['owner']['normalized'] == 'NGUYEN VAN A'
    assert d['fields']['legal_rep']['normalized'] == 'TRAN THI B'
    assert d['fields']['legal_rep']['regions'][0]['page'] == 2
    for field in d['fields'].values():
        for r in field['regions']:
            assert 0 <= r['box'][0] < r['box'][2] <= 1
            assert 0 <= r['box'][1] < r['box'][3] <= 1
    assert d['fields']['company_en']['status'] == 'missing'


def test_conflicting_labeled_ids_are_ambiguous(tmp_path):
    d = extract(pdf(tmp_path, ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789\nMa so doanh nghiep: 9876543210']), 'gpkd')
    assert d['fields']['tax_id']['status'] == 'ambiguous'
    assert len(d['fields']['tax_id']['candidates']) == 2


def test_scan_failure_is_not_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr('app.web_extract.ocr_lines', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('ocr')))
    with pytest.raises(ValueError, match='OCR'):
        extract(pdf(tmp_path, ['']), 'gpkd')
