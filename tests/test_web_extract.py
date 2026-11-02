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


def test_custom_font_gibberish_is_not_usable_text():
    assert not usable_text('7RQ F QJ W YL W E QJ WL QJ 9L W 1 7 71 CE 2 ' * 4)


def test_rotated_page_word_boxes_align_with_display(tmp_path):
    p=pdf(tmp_path,['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789'])
    with fitz.open(p) as doc:
        doc[0].set_rotation(90); doc.save(tmp_path/'rotated.pdf')
    d=extract(tmp_path/'rotated.pdf','gpkd')
    assert d['pages'][0]['width']>d['pages'][0]['height']
    with fitz.open(tmp_path/'rotated.pdf') as doc:
        expected=doc[0].search_for('0123456789')[0]*doc[0].rotation_matrix
        region=d['fields']['tax_id']['regions'][0]['box']
        assert abs(region[0]-expected.x0/doc[0].rect.width)<.002
        assert abs(region[1]-expected.y0/doc[0].rect.height)<.002


def test_custom_encoding_control_characters_force_ocr():
    assert not usable_text(('Ten doanh nghiep CONG TY ALPHA \x01\x02\x03\x04'*10))


def test_encoding_check_uses_full_text_not_tokenized_words(tmp_path,monkeypatch):
    p=pdf(tmp_path,['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789'])
    original=fitz.Page.get_text
    def broken(self, option='text', *args, **kwargs):
        if option=='text': return ('TEN MA SO CONG TY \x01\x02\x03\x04'*30)
        return original(self,option,*args,**kwargs)
    monkeypatch.setattr(fitz.Page,'get_text',broken)
    monkeypatch.setattr('app.web_extract.ocr_lines',lambda *a,**k: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(ValueError,match='OCR'): extract(p,'gpkd')


def test_owner_full_name_label_variants(tmp_path):
    d=extract(pdf(tmp_path,['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\n4. Thong tin ve chu so huu\nHo, chu dem va ten: NGUYEN VAN A\n5. Nguoi dai dien theo phap luat\nHo, chu dem va ten: TRAN THI B']), 'gpkd')
    assert d['fields']['owner']['value']=='NGUYEN VAN A'
    assert d['fields']['legal_rep']['value']=='TRAN THI B'


def test_signature_ink_candidates_are_suspicions_not_proof():
    import numpy as np, cv2
    from app.web_extract import signature_ink_regions
    rgb=np.full((800,600,3),255,dtype=np.uint8)
    cv2.polylines(rgb,[np.array([[360,540],[410,480],[370,530],[460,515],[420,550]])],False,(20,30,180),3)
    rows=[{'text':'DAI DIEN DOANH NGHIEP','page':1,'region':{'page':1,'box':[.5,.5,.85,.53]},'words':[]}]
    result=signature_ink_regions(rgb,rows)
    assert result and all(0<=v<=1 for v in result[0])
    assert not signature_ink_regions(np.full_like(rgb,255),rows)


def test_wrapped_company_name_and_repeated_sources(tmp_path):
    d=extract(pdf(tmp_path,['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nTen cong ty viet bang tieng nuoc ngoai: ALPHA COMPANY\nLIMITED\nMa so doanh nghiep: 0123456789', 'Ma so doanh nghiep: 0123456789\nMa so doanh nghiep: 0123456789']), 'gpkd')
    assert d['fields']['company_en']['value']=='ALPHA COMPANY LIMITED'
    assert len(d['fields']['tax_id']['regions'])==3


def test_next_row_company_is_not_duplicated(tmp_path):
    d=extract(pdf(tmp_path,['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nTen cong ty:\nCONG TY ALPHA\nMa so doanh nghiep: 0123456789']), 'gpkd')
    assert d['fields']['company_vi']['value']=='CONG TY ALPHA'


def test_wrapped_low_quality_name_stays_uncertain():
    from app.web_extract import rows_from_words,extract_fields
    words=[{'text':t,'box':[x,.1,x+.03,.12],'confidence':95} for x,t in zip([.1,.14,.18,.22,.26],['Ten','cong','ty:','CONG','TY'])]
    words.append({'text':'ALPHA','box':[.1,.125,.25,.145],'confidence':20})
    rows=rows_from_words(words,1)
    field=extract_fields(rows,'gpkd')['company_vi']
    assert field['value']=='CONG TY ALPHA'
    assert field['status']=='uncertain'


def test_signer_source_is_not_identical_name_in_declaration(tmp_path):
    text='BAN DANG KY SU DUNG EPORT\nDai dien co tham quyen:\nNGUYEN VAN AN\n'+'\n'*20+'DAI DIEN DOANH NGHIEP\n'+'\n'*3+'NGUYEN VAN AN'
    d=extract(pdf(tmp_path,[text]),'eport')
    f=d['fields']['signer']
    assert f['value']=='NGUYEN VAN AN'
    assert f['regions'][0]['box'][1]>.45


def test_faded_seal_is_unknown_not_absence_or_presence(tmp_path):
    import cv2,numpy as np
    rgb=np.full((600,500,3),255,np.uint8)
    cv2.circle(rgb,(350,450),60,(255,246,246),2)
    with fitz.open() as doc:
        page=doc.new_page(width=500,height=600)
        page.insert_image(page.rect,stream=cv2.imencode('.png',cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR))[1].tobytes())
        page.insert_text((30,50),'BAN DANG KY SU DUNG EPORT\nThong tin doanh nghiep: CONG TY ALPHA')
        doc.save(tmp_path/'faded.pdf')
    result=extract(tmp_path/'faded.pdf','eport')
    assert result['fields']['seal']['status']=='missing'
    assert result['fields']['seal']['value']==''
