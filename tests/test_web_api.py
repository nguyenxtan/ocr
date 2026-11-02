import time
import fitz
import pytest
from fastapi.testclient import TestClient
from app.web import create_app


def make_pdf(text='GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789', password=None):
    with fitz.open() as doc:
        p=doc.new_page(); p.insert_text((40,50), text)
        if password:
            return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw=password, user_pw=password)
        return doc.tobytes()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, timeout=20)) as c:
        c.get('/api/session')
        yield c


def upload(c, kind='gpkd', content=None):
    return c.put('/api/documents/'+kind, content=content or make_pdf(), headers={'content-type':'application/pdf','x-file-name':'sample.pdf'})


def wait(c):
    for _ in range(200):
        s=c.get('/api/session').json()
        if not any(d['state'] in ('queued','running') for d in s['documents'].values()):
            return s
        time.sleep(.05)
    pytest.fail('job timeout')


def test_rejects_non_pdf_and_password(client):
    assert upload(client,content=b'not PDF').status_code==422
    assert upload(client,content=make_pdf(password='secret')).status_code==422
    assert client.get('/api/session').json()['documents']=={}


def test_isolated_sessions_and_valid_sources(client):
    assert upload(client).status_code==202
    s=wait(client); assert s['documents']['gpkd']['detected_kind']=='gpkd'
    url=s['documents']['gpkd']['page_url']
    assert client.get(url).status_code==200
    with TestClient(client.app) as other:
        other.get('/api/session')
        assert other.get(url).status_code==404
        assert other.get('/api/session').json()['documents']=={}


def test_wrong_type_cannot_compare_and_delete_clears(client):
    assert upload(client,'eport').status_code==202
    s=wait(client)
    assert s['documents']['eport']['detected_kind']=='gpkd'
    assert client.get('/api/report').status_code==409
    assert client.delete('/api/documents/eport').status_code==200
    assert client.get('/api/session').json()['documents']=={}


def test_edits_history_validation_and_revision(client):
    upload(client); s=wait(client)
    d=s['documents']['gpkd']; rev=d['revision']
    field=d['fields']['tax_id']; region=field['regions'][0]
    patch={'value':'9876543210','regions':[region], 'revision':rev, 'reason':'Đối chiếu bản gốc'}
    r=client.patch('/api/fields/gpkd/tax_id',json=patch)
    assert r.status_code==200
    field=r.json()
    assert field['raw']!='9876543210'
    assert field['value']=='9876543210'
    assert len(field['history'])==1
    assert client.patch('/api/fields/gpkd/tax_id',json=patch).status_code==409
    patch['revision']=rev+1; patch['regions']=[{'page':1,'box':[-1,0,1,1]}]
    assert client.patch('/api/fields/gpkd/tax_id',json=patch).status_code==422


def test_replacement_invalidates_old_pages(client):
    upload(client); old=wait(client)['documents']['gpkd']['page_url']
    upload(client,content=make_pdf('GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 9876543210'))
    assert client.get(old).status_code==404
    assert wait(client)['documents']['gpkd']['fields']['tax_id']['value']=='9876543210'


def test_csrf_origin_blocked(client):
    assert client.delete('/api/documents/gpkd', headers={'origin':'https://evil.example'}).status_code==403


def test_invalid_field_and_kind(client):
    assert upload(client,'bad').status_code==404
    assert client.patch('/api/fields/gpkd/anything',json={}).status_code in (404,422)
