from unittest.mock import Mock
import fitz
import numpy as np
from app.web_extract import extract
from app.web_compare import compare
from test_web_compare import documents,row,f


def test_gpkd_seal_is_a_separate_required_check():
    d=documents();d['gpkd']['fields']['seal']=f('','missing')
    r=compare(d)
    assert row(r,'gpkd_seal')['status']=='REVIEW'
    assert row(r,'seal')['status']=='PASS'
    assert r['conclusion']=='REVIEW'


def test_gpkd_manual_confirmation_has_own_source_and_does_not_replace_eport():
    d=documents();proof={'page':2,'box':[.5,.5,.8,.8]}
    d['gpkd']['fields']['seal']={**f('Có','manual'),'regions':[proof]}
    r=compare(d)
    item=row(r,'gpkd_seal')
    assert item['status']=='PASS'
    assert item['right']['regions']==[proof]
    assert item['right_kind']=='gpkd'
    d['gpkd']['fields']['seal']=f('Không có','manual')
    assert row(compare(d),'gpkd_seal')['status']=='FAIL'
    d['gpkd']['fields']['seal']=f('Nghi có','uncertain')
    assert row(compare(d),'gpkd_seal')['status']=='REVIEW'


def test_gpkd_seal_scans_all_pages_without_company_stamp_ocr(tmp_path,monkeypatch):
    path=tmp_path/'registration.pdf'
    with fitz.open() as doc:
        p=doc.new_page();p.insert_text((40,50),'GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789')
        p=doc.new_page();p.insert_text((40,50),'Thong tin nguoi dai dien theo phap luat\nHo va ten: NGUYEN VAN AN')
        doc.save(path)
    def render(page):return np.full((100,100,3),page.number,np.uint8)
    def detect(image,**kw):return [(.9,np.ones((20,20),np.uint8),(50,50,80,80))] if image[0,0,0]==1 else []
    monkeypatch.setattr('app.web_extract.render_page',render)
    detector=Mock(side_effect=detect);monkeypatch.setattr('app.web_extract.detect_stamps',detector)
    reader=Mock(side_effect=AssertionError('Không OCR tên/MST doanh nghiệp trên mộc cơ quan cấp'))
    monkeypatch.setattr('app.web_extract.read_seal',reader)
    result=extract(path,'gpkd')
    assert result['fields']['seal']['value']=='Có'
    assert result['fields']['seal']['regions']==[{'page':2,'box':[.5,.5,.8,.8]}]
    assert detector.call_count==2 and not reader.called


def test_gpkd_without_detected_seal_is_unknown_not_absent(tmp_path,monkeypatch):
    path=tmp_path/'registration.pdf'
    with fitz.open() as doc:
        p=doc.new_page();p.insert_text((40,50),'GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789');doc.save(path)
    monkeypatch.setattr('app.web_extract.detect_stamps',lambda *a,**k:[])
    result=extract(path,'gpkd')
    assert result['fields']['seal']['status']=='missing'
    assert result['fields']['seal']['value']==''
