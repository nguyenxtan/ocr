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
    patch={'value':'9876543210','regions':[region], 'revision':rev, 'document_id':d['id'], 'reason':'Đối chiếu bản gốc'}
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


def test_oversize_header_and_invalid_page(client):
    assert client.put('/api/documents/gpkd',content=b'bad',headers={'content-type':'application/pdf','content-length':str(21*1024*1024)}).status_code==413
    upload(client); d=wait(client)['documents']['gpkd']
    assert client.get(d['page_url'].rsplit('/',1)[0]+'/999').status_code==404


def test_cancellation_does_not_publish_late_result(client,monkeypatch):
    import asyncio
    from app.web_jobs import Store
    old=Store.command
    async def slow(self,mode,*a,**kw):
        if mode=='extract': await asyncio.sleep(10)
        return await old(self,mode,*a,**kw)
    monkeypatch.setattr(Store,'command',slow)
    upload(client)
    assert client.post('/api/jobs/gpkd/cancel').status_code==200
    assert client.get('/api/session').json()['documents']['gpkd']['state']=='cancelled'
    assert client.get('/api/report').status_code==409


def test_queue_is_bounded(client,monkeypatch):
    import asyncio
    from app.web_jobs import Store
    old=Store.command
    async def slow(self,mode,*a,**kw):
        if mode=='extract': await asyncio.sleep(10)
        return await old(self,mode,*a,**kw)
    monkeypatch.setattr(Store,'command',slow)
    for _ in range(4):
        client.cookies.clear(); client.get('/api/session'); assert upload(client).status_code==202
    client.cookies.clear(); client.get('/api/session')
    assert upload(client).status_code==429


def test_expired_session_is_purged(client):
    upload(client); d=wait(client)['documents']['gpkd']; path=next(iter(client.app.state.store.sessions.values()))['path']
    for s in client.app.state.store.sessions.values(): s['expires']=0
    assert client.get(d['page_url']).status_code==401
    assert client.get('/api/session').json()['documents']=={}
    assert not path.exists()


def test_report_stays_unavailable_on_worker_failure(client,monkeypatch):
    from app.web_jobs import Store
    old=Store.command
    async def bad(self,mode,*a,**kw):
        if mode=='extract': raise ValueError('OCR failure')
        return await old(self,mode,*a,**kw)
    monkeypatch.setattr(Store,'command',bad)
    upload(client)
    assert wait(client)['documents']['gpkd']['state']=='error'
    assert client.get('/api/report').status_code==409


def test_failed_replacement_invalidates_prior_document(client):
    upload(client); old=wait(client)['documents']['gpkd']['page_url']
    assert upload(client,content=b'not PDF').status_code==422
    assert client.get('/api/session').json()['documents']=={}
    assert client.get(old).status_code==404


def test_stale_edit_from_replaced_document_is_rejected(client):
    upload(client); d=wait(client)['documents']['gpkd']; region=d['fields']['tax_id']['regions'][0]
    upload(client); wait(client)
    r=client.patch('/api/fields/gpkd/tax_id',json={'value':'9876543210','regions':[region],'revision':d['revision'],'document_id':d['id'],'reason':'Old document'})
    assert r.status_code==409


def test_delete_during_validation_cannot_resurrect_upload(tmp_path,monkeypatch):
    import asyncio,httpx
    from app.web_jobs import Store
    async def scenario():
        app=create_app(tmp_path); old=Store.command
        entered=asyncio.Event();release=asyncio.Event()
        async def delayed(self,mode,*a,**kw):
            if mode=='validate': entered.set();await release.wait()
            return await old(self,mode,*a,**kw)
        monkeypatch.setattr(Store,'command',delayed)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as c:
                await c.get('/api/session')
                pending=asyncio.create_task(c.put('/api/documents/gpkd',content=make_pdf(),headers={'content-type':'application/pdf'}))
                await entered.wait(); assert (await c.delete('/api/documents/gpkd')).status_code==200
                release.set(); response=await pending
                assert response.status_code==409
                assert (await c.get('/api/session')).json()['documents']=={}
    asyncio.run(scenario())


def test_preview_cache_is_bounded(tmp_path):
    import asyncio
    from app.web_jobs import Store
    store=Store(tmp_path)
    paths=[]
    for i in range(3):
        p=store.root/'session'/str(i)/'page-1.png';p.parent.mkdir(parents=True);p.write_bytes(b'x'*10);paths.append(p)
    store.trim_cache(paths[-1],limit=15)
    assert paths[-1].exists()
    assert sum(p.stat().st_size for p in paths if p.exists())<=15
    asyncio.run(store.close())


def test_too_many_pages_rejected(client):
    with fitz.open() as doc:
        for _ in range(21): doc.new_page()
        data=doc.tobytes()
    assert upload(client,content=data).status_code==422


def test_stale_temp_roots_cleaned_after_crash(tmp_path):
    import asyncio,os
    from app.web_jobs import Store
    old=tmp_path/'ocr-pair-web-old';old.mkdir();(old/'.ocr-web-root').write_text('v1');os.utime(old,(0,0))
    unrelated=tmp_path/'ocr-pair-web-unrelated';unrelated.mkdir();os.utime(unrelated,(0,0))
    store=Store(tmp_path,ttl=10)
    assert not old.exists()
    assert unrelated.exists()
    asyncio.run(store.close())


def test_failed_preview_does_not_cache_error_as_image(client,monkeypatch):
    from app.web_jobs import Store
    upload(client); d=wait(client)['documents']['gpkd'];old=Store.command
    async def fail_page(self,mode,path,output,*args,**kw):
        if mode=='page':
            output.write_text('{"error":"render failed"}');raise ValueError('render failed')
        return await old(self,mode,path,output,*args,**kw)
    monkeypatch.setattr(Store,'command',fail_page)
    assert client.get(d['page_url']).status_code==422
    monkeypatch.setattr(Store,'command',old)
    response=client.get(d['page_url'])
    assert response.status_code==200
    assert response.content.startswith(b'\x89PNG')
