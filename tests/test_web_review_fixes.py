"""Regression tests for the second independent review of the web flow."""
import unicodedata

import fitz
import pytest
from fastapi.testclient import TestClient

from app.web import create_app
from app.web_compare import compare
from app.web_extract import add_field, empty_field, extract


def f(value, status='read'):
    return {'value': value, 'status': status, 'regions': []}


def documents(company_g='CÔNG TY TNHH HÒA BÌNH', company_e='CÔNG TY TNHH HÒA BÌNH', rep_g='Lê Văn Hùng', rep_e='Lê Văn Hùng'):
    return {'gpkd': {'fields': {'tax_id': f('0123456789'), 'company_vi': f(company_g), 'legal_rep': f(rep_g)}},
            'eport': {'fields': {'tax_id': f('0123456789'), 'registration_id': f('0123456789'), 'company_vi': f(company_e),
                                 'authorized_rep': f(rep_e), 'signer': f(rep_e), 'signature': f('Có', 'manual'),
                                 'seal': f('Có'), 'seal_tax_id': f('0123456789')}}}


def row(report, key):
    return next(r for r in report['rows'] if r['id'] == key)


@pytest.mark.parametrize('a,b', [
    ('CÔNG TY TNHH HÒA BÌNH', 'CÔNG TY TNHH HÓA BÌNH'),            # accent only
    ('CÔNG TY TNHH MTV AN PHÁT LỘC', 'CÔNG TY CỔ PHẦN LỘC PHÁT'),  # legal type, short token, order
    ('CÔNG TY TNHH HÒA BÌNH', 'CÔNG TY CỔ PHẦN HÒA BÌNH'),         # legal type
    ('CÔNG TY TNHH HÒA BÌNH', 'CÔNG TY TNHH BÌNH HÒA'),            # order
    ('CÔNG TY TNHH AN PHÁT', 'CÔNG TY TNHH PHÁT'),                 # short token
    ('CÔNG TY TNHH MTV HÒA BÌNH', 'CÔNG TY TNHH HÒA BÌNH'),        # one-member vs multi-member
])
def test_distinct_company_names_never_pass(a, b):
    r = compare(documents(company_g=a, company_e=b))
    assert row(r, 'company')['status'] != 'PASS'
    assert r['conclusion'] != 'PASS'


@pytest.mark.parametrize('a,b', [('Lê Văn Hùng', 'Lê Văn Hưng'), ('Nguyễn Thị Thu', 'Nguyễn Thị Thư'), ('Trần An', 'Trần Ân')])
def test_distinct_accented_people_never_pass(a, b):
    r = compare(documents(rep_g=a, rep_e=b))
    assert row(r, 'representative')['status'] == 'REVIEW'
    d = documents(rep_e=a); d['eport']['fields']['signer'] = f(b)
    assert row(compare(d), 'signer')['status'] == 'REVIEW'


def test_case_whitespace_punctuation_and_unicode_form_still_pass():
    nfd = unicodedata.normalize('NFD', 'CÔNG TY TNHH HÒA BÌNH')
    r = compare(documents(company_g='Công ty  TNHH Hòa Bình.', company_e=nfd,
                          rep_g='lê văn  hùng', rep_e=unicodedata.normalize('NFD', 'LÊ VĂN HÙNG')))
    assert row(r, 'company')['status'] == 'PASS'
    assert row(r, 'representative')['status'] == 'PASS'


def test_accent_only_or_legal_form_spelling_difference_reviews_not_fails():
    r = compare(documents(company_g='CONG TY TNHH HOA BINH', company_e='CÔNG TY TNHH HÒA BÌNH'))
    assert row(r, 'company')['status'] == 'REVIEW'
    r = compare(documents(company_g='CÔNG TY TNHH HÒA BÌNH', company_e='CÔNG TY TRÁCH NHIỆM HỮU HẠN HÒA BÌNH'))
    assert row(r, 'company')['status'] == 'REVIEW'


def test_accent_distinct_candidates_are_not_merged():
    field = empty_field('legal_rep'); fields = {'legal_rep': field}
    add_field(fields, 'legal_rep', {'value': 'Lê Văn Hùng', 'regions': [{'page': 1, 'box': [0, 0, .1, .1]}], 'status': 'read'})
    add_field(fields, 'legal_rep', {'value': 'Lê Văn Hưng', 'regions': [{'page': 1, 'box': [0, .2, .1, .3]}], 'status': 'read'})
    assert field['status'] == 'ambiguous' and len(field['candidates']) == 2


# --- Rotated text-layer PDFs: parse in layout space, publish display boxes -------------

WRAPPED = ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP', 'Ten cong ty viet bang tieng Viet: CONG TY TNHH ALPHA BETA GAMMA',
           'DELTA OMEGA', 'Ma so doanh nghiep: 0312345678', 'Nguoi dai dien theo phap luat', 'Ho va ten: TRAN VAN MINH  Gioi tinh: Nam']
NEXT_LINE = ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP', '1. Ten cong ty viet bang tieng Viet:', 'CONG TY TNHH ALPHA BETA GAMMA',
             'Ma so doanh nghiep: 0312345678', 'Nguoi dai dien theo phap luat', 'Ho va ten: TRAN VAN MINH  Gioi tinh: Nam']


def rotated_pdf(path, lines, rotation):
    with fitz.open() as doc:
        page = doc.new_page(width=595, height=842); y = 80
        for text in lines:
            page.insert_text((60, y), text, fontsize=11); y += 16
        page.set_rotation(rotation); doc.save(path)
    return path


def expected_box(path, text):
    with fitz.open(path) as doc:
        page = doc[0]; rect = page.search_for(text)[0] * page.rotation_matrix
        return [rect.x0 / page.rect.width, rect.y0 / page.rect.height, rect.x1 / page.rect.width, rect.y1 / page.rect.height]


def close(a, b, tol=.004):
    return all(abs(x - y) < tol for x, y in zip(a, b))


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_rotated_text_wrapped_company_and_display_sources(tmp_path, rotation):
    p = rotated_pdf(tmp_path / f'w{rotation}.pdf', WRAPPED, rotation)
    d = extract(p, 'gpkd', marks=False)
    assert d['pages'][0]['method'] == 'text' and d['pages'][0]['rotation'] == rotation
    fields = d['fields']
    assert fields['company_vi']['value'] == 'CONG TY TNHH ALPHA BETA GAMMA DELTA OMEGA'
    assert fields['company_vi']['status'] == 'read'
    assert fields['tax_id']['value'] == '0312345678'
    assert fields['legal_rep']['value'] == 'TRAN VAN MINH'
    first, second = fields['company_vi']['regions']
    assert close(first['box'], expected_box(p, 'CONG TY TNHH ALPHA BETA GAMMA'))
    assert close(second['box'], expected_box(p, 'DELTA OMEGA'))
    assert close(fields['tax_id']['regions'][0]['box'], expected_box(p, '0312345678'))
    for field in fields.values():
        assert all(set(r) == {'page', 'box'} for r in field['regions'])
        for c in field['candidates']:
            assert set(c) == {'value', 'regions', 'status'}


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_rotated_text_label_then_next_line_value(tmp_path, rotation):
    p = rotated_pdf(tmp_path / f'n{rotation}.pdf', NEXT_LINE, rotation)
    fields = extract(p, 'gpkd', marks=False)['fields']
    assert fields['company_vi']['value'] == 'CONG TY TNHH ALPHA BETA GAMMA'
    assert close(fields['company_vi']['regions'][0]['box'], expected_box(p, 'CONG TY TNHH ALPHA BETA GAMMA'))


# --- Session creation is not available to cross-site requests ---------------------------

@pytest.mark.parametrize('headers', [{'sec-fetch-site': 'cross-site'}, {'sec-fetch-site': 'same-site'},
                                     {'origin': 'https://evil.example'}, {'origin': 'null'}])
def test_cross_site_session_requests_cannot_consume_sessions(tmp_path, headers):
    with TestClient(create_app(tmp_path, timeout=20)) as c:
        store = c.app.state.store
        for _ in range(store.max_sessions + 2):
            c.cookies.clear()
            assert c.get('/api/session', headers=headers).status_code == 403
        assert store.sessions == {}
        c.cookies.clear()
        assert c.get('/api/session', headers={'sec-fetch-site': 'same-origin'}).status_code == 200
        c.cookies.clear()
        assert c.get('/api/session', headers={'origin': 'http://testserver', 'sec-fetch-site': 'same-origin'}).status_code == 200
        c.cookies.clear()
        assert c.get('/api/session').status_code == 200   # non-browser local client
        assert len(store.sessions) == 3


def test_cross_site_page_image_and_report_reads_are_blocked(tmp_path):
    with TestClient(create_app(tmp_path, timeout=20)) as c:
        c.get('/api/session')
        assert c.get('/api/report', headers={'sec-fetch-site': 'cross-site'}).status_code == 403
        assert c.get('/', headers={'sec-fetch-site': 'cross-site'}).status_code == 200  # top-level page itself is harmless


# --- Manual correction of an ambiguous field must not keep every candidate's evidence ---

def ambiguous_doc(c):
    with fitz.open() as doc:
        p = doc.new_page(); p.insert_text((40, 50), 'GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789\nMa so doanh nghiep: 9876543210')
        content = doc.tobytes()
    assert c.put('/api/documents/gpkd', content=content, headers={'content-type': 'application/pdf'}).status_code == 202
    import time
    for _ in range(200):
        s = c.get('/api/session').json()
        if s['documents']['gpkd']['state'] not in ('queued', 'running'): return s['documents']['gpkd']
        time.sleep(.05)
    pytest.fail('job timeout')


def test_ambiguous_edit_requires_single_candidate_or_new_region(tmp_path):
    with TestClient(create_app(tmp_path, timeout=20)) as c:
        c.get('/api/session')
        d = ambiguous_doc(c); field = d['fields']['tax_id']
        assert field['status'] == 'ambiguous' and len(field['candidates']) == 2
        body = {'value': '0123456789', 'regions': field['regions'], 'revision': d['revision'], 'document_id': d['id'], 'reason': 'chọn nguồn'}
        r = c.patch('/api/fields/gpkd/tax_id', json=body)
        assert r.status_code == 422 and 'ứng viên' in r.json()['detail']
        body['regions'] = field['candidates'][0]['regions']
        r = c.patch('/api/fields/gpkd/tax_id', json=body)
        assert r.status_code == 200
        saved = r.json()
        assert saved['regions'] == field['candidates'][0]['regions']
        assert saved['candidates'] == field['candidates'] and saved['raw'] == field['raw']
        assert saved['history'][0]['before']['regions'] == field['regions']
        body.update(revision=d['revision'] + 1, regions=[{'page': 1, 'box': [.1, .1, .3, .2]}], value='9876543210')
        assert c.patch('/api/fields/gpkd/tax_id', json=body).status_code == 200


# --- Hidden / non-visible text layers are not evidence ---------------------------------

TITLE = 'GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nTen cong ty viet bang tieng Viet: CONG TY ALPHA'
HIDDEN_ID = 'Ma so doanh nghiep: 0123456789'


def white_png():
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False); pix.set_rect(pix.irect, (255, 255, 255))
    return pix.tobytes('png')


def hidden_pdf(path, how):
    with fitz.open() as doc:
        page = doc.new_page()
        page.draw_rect(fitz.Rect(20, 20, 400, 200), color=None, fill=(.93, .93, 1))   # background drawn first: fine
        page.insert_text((40, 50), TITLE, fontsize=11)
        kwargs = {'render_mode': 3} if how == 'invisible' else {'color': (1, 1, 1)} if how == 'white' else {'fill_opacity': 0} if how == 'transparent' else {}
        page.insert_text((40, 120), HIDDEN_ID, fontsize=11, **kwargs)
        if how == 'covered-rect':
            page.draw_rect(fitz.Rect(35, 105, 260, 125), color=None, fill=(.93, .93, 1))
        if how == 'covered-image':
            page.insert_image(fitz.Rect(35, 105, 260, 125), stream=white_png())
        doc.save(path)
    return path


@pytest.mark.parametrize('how', ['invisible', 'white', 'transparent', 'covered-rect', 'covered-image'])
def test_hidden_text_layer_is_not_published_as_read_evidence(tmp_path, monkeypatch, how):
    calls = []
    monkeypatch.setattr('app.web_extract.ocr_lines', lambda rgb, *a, **k: calls.append(rgb.shape) or [])
    d = extract(hidden_pdf(tmp_path / f'{how}.pdf', how), 'gpkd', marks=False)
    assert d['pages'][0]['method'] == 'ocr' and calls
    assert d['fields']['tax_id']['status'] == 'missing' and d['fields']['tax_id']['regions'] == []


def test_visible_text_layer_still_uses_text_without_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr('app.web_extract.ocr_lines', lambda *a, **k: pytest.fail('normal text PDF must not be OCRed'))
    p = hidden_pdf(tmp_path / 'visible.pdf', 'visible')
    d = extract(p, 'gpkd', marks=False)
    assert d['pages'][0]['method'] == 'text'
    assert d['fields']['tax_id']['status'] == 'read'
    assert close(d['fields']['tax_id']['regions'][0]['box'], expected_box(p, '0123456789'))


# --- Manual presence confirmation names one location --------------------------------------

def test_presence_confirmation_requires_one_location_but_wrapped_names_keep_lines(tmp_path):
    with TestClient(create_app(tmp_path, timeout=20)) as c:
        c.get('/api/session')
        d = ambiguous_doc(c)
        stored = c.app.state.store.sessions[c.cookies.get('ocr_session')]['documents']['gpkd']
        a, b = {'page': 1, 'box': [.1, .5, .2, .55]}, {'page': 1, 'box': [.4, .5, .5, .55]}
        # Inject a suspect presence field with one value and two locations (as OCR produces).
        stored['fields']['signature'] = {'key': 'signature', 'label': 'Chữ ký', 'raw': 'Nghi có', 'value': 'Nghi có', 'normalized': 'NGHI CÓ',
                                         'status': 'uncertain', 'regions': [a, b], 'history': [],
                                         'candidates': [{'value': 'Nghi có', 'regions': [a, b], 'status': 'uncertain'}]}
        body = {'value': 'Có', 'regions': [a, b], 'revision': d['revision'], 'document_id': d['id'], 'reason': 'xác nhận'}
        r = c.patch('/api/fields/gpkd/signature', json=body)
        assert r.status_code == 422 and 'một vùng' in r.json()['detail']
        body['regions'] = [b]
        saved = c.patch('/api/fields/gpkd/signature', json=body).json()
        assert saved['regions'] == [b] and saved['candidates'][0]['regions'] == [a, b]
        # A wrapped company name legitimately spans two line regions.
        two_lines = [{'page': 1, 'box': [.1, .1, .5, .12]}, {'page': 1, 'box': [.1, .125, .3, .145]}]
        body.update(value='CONG TY ALPHA BETA', regions=two_lines, revision=d['revision'] + 1)
        assert c.patch('/api/fields/gpkd/company_vi', json=body).status_code == 200


def test_conflicting_values_at_one_physical_source_can_be_manually_resolved(tmp_path):
    with TestClient(create_app(tmp_path,timeout=20)) as c:
        c.get('/api/session');d=ambiguous_doc(c)
        stored=c.app.state.store.sessions[c.cookies.get('ocr_session')]['documents']['gpkd']
        field=stored['fields']['tax_id'];one=field['candidates'][0]['regions']
        field['candidates'][1]['regions']=one
        field['regions']=one
        response=c.patch('/api/fields/gpkd/tax_id',json={'value':'0123456789','regions':one,'revision':d['revision'],'document_id':d['id'],'reason':'Một vùng, hai cách đọc OCR'})
        assert response.status_code==200
        assert response.json()['regions']==one
