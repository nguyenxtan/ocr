from copy import deepcopy
import numpy as np
import pytest
from app.web_extract import empty_field,exact_text
from app.web_refine import refine_fields


def field(value='CÔNG TY ALPHA',status='uncertain',regions=None):
    f=empty_field('company_vi')
    rs=regions or [{'page':1,'box':[.1,.1,.7,.14]}]
    f.update(raw=value,value=value,normalized=exact_text(value),status=status,regions=rs,
             candidates=[{'value':value,'status':status,'regions':deepcopy(rs)}])
    return f


def run(monkeypatch,f,reads):
    results=iter(reads)
    monkeypatch.setattr('app.web_refine.recognize_crop',lambda *a,**kw: next(results))
    fs={'company_vi':f}
    summary=refine_fields(fs,{1:np.full((1000,800,3),255,np.uint8)},'vie+eng',exact_text)
    return summary


def test_agreeing_region_recheck_confirms_without_rewriting_raw_or_source(monkeypatch):
    f=field();before=deepcopy(f)
    stats=run(monkeypatch,f,[('CÔNG TY ALPHA',94)])
    assert stats=={'attempted':1,'confirmed':1}
    assert f['status']=='read' and f['candidates'][0]['status']=='read'
    for key in ('value','raw','normalized','regions','history'):assert f[key]==before[key]
    assert f['recheck']['previous_status']=='uncertain'


@pytest.mark.parametrize('reading,confidence',[('CÔNG TY BETA',99),('CONG TY ALPHA',99),('',99),('CÔNG TY ALPHA',84),('CÔNG TY ALPHA',float('nan')),('CÔNG TY ALPHA',float('inf'))])
def test_difference_accents_missing_and_low_score_never_promote(monkeypatch,reading,confidence):
    f=field();before=deepcopy(f)
    assert run(monkeypatch,f,[(reading,confidence)])['confirmed']==0
    assert f==before


def test_whole_multiline_value_must_be_confirmed(monkeypatch):
    rs=[{'page':1,'box':[.1,.1,.7,.14]},{'page':1,'box':[.1,.15,.4,.19]}]
    f=field('ALPHA COMPANY LIMITED',regions=rs)
    assert run(monkeypatch,f,[('ALPHA COMPANY',94),('LIMITED',93)])['confirmed']==1
    f=field('ALPHA COMPANY LIMITED',regions=rs);before=deepcopy(f)
    assert run(monkeypatch,f,[('ALPHA COMPANY',94),('LIMITE',99)])['confirmed']==0
    assert f==before


def test_retry_error_preserves_original_result(monkeypatch):
    def broken(*a,**k):raise RuntimeError('OCR timeout')
    monkeypatch.setattr('app.web_refine.recognize_crop',broken)
    f=field();before=deepcopy(f)
    stats=refine_fields({'company_vi':f},{1:np.full((1000,800,3),255,np.uint8)},'vie+eng',exact_text)
    assert stats=={'attempted':1,'confirmed':0} and f==before


def test_no_rereading_known_manual_ambiguous_missing_or_unrelated_fields(monkeypatch):
    def forbidden(*a,**k):pytest.fail('unnecessary OCR')
    monkeypatch.setattr('app.web_refine.recognize_crop',forbidden)
    for status in ('read','manual','ambiguous','missing'):
        f=field(status=status);before=deepcopy(f)
        assert refine_fields({'company_vi':f},{1:np.zeros((1000,800,3),np.uint8)},'vie+eng',exact_text)['attempted']==0
        assert f==before
    f=field();assert refine_fields({'seal_text':f},{1:np.zeros((1000,800,3),np.uint8)},'vie+eng',exact_text)['attempted']==0


def test_crop_budget_and_page_geometry_cannot_read_other_pages(monkeypatch):
    def forbidden(*a,**k):pytest.fail('invalid or unbounded ROI')
    monkeypatch.setattr('app.web_refine.recognize_crop',forbidden)
    for rs in ([{'page':2,'box':[.1,.1,.7,.14]}],
               [{'page':1,'box':[-.1,.1,.7,.14]}],
               [{'page':1,'box':[0,0,1,1]}],
               [{'page':1,'box':[.1,.1,.7,.14]}]*7):
        f=field(regions=rs)
        assert refine_fields({'company_vi':f},{1:np.zeros((1000,800,3),np.uint8)},'vie+eng',exact_text)['attempted']==0
        assert f['status']=='uncertain'
