"""Separate web entry point: uvicorn app.web:app --host 127.0.0.1 --port 8000."""
from __future__ import annotations
from contextlib import asynccontextmanager
from copy import deepcopy
import asyncio
import math
import os
from pathlib import Path
import secrets
import shutil
import time
from urllib.parse import urlsplit, unquote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.web_jobs import Store, Busy
from app.web_extract import normalize_value
from app.web_compare import compare

STATIC=Path(__file__).parent/'static'
COOKIE='ocr_session'


class Region(BaseModel):
    page:int=Field(ge=1,le=20)
    box:list[float]=Field(min_length=4,max_length=4)


class Edit(BaseModel):
    document_id:str=Field(min_length=32,max_length=32)
    value:str=Field(max_length=3000)
    regions:list[Region]=Field(max_length=20)
    revision:int=Field(ge=1)
    reason:str=Field(min_length=1,max_length=300)


def same_region(a,b):
    return a['page']==b['page'] and all(abs(x-y)<1e-6 for x,y in zip(a['box'],b['box']))


def create_app(root=None, timeout=None, ttl=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.store=Store(root,timeout=timeout or int(os.getenv('WEB_JOB_TIMEOUT_SEC','180')),ttl=ttl or int(os.getenv('WEB_SESSION_TTL_SEC','1800')),max_sessions=int(os.getenv('WEB_MAX_SESSIONS','8')),queue_size=int(os.getenv('WEB_QUEUE_SIZE','3')))
        app.state.store.janitor=asyncio.create_task(app.state.store.sweep())
        yield
        await app.state.store.close()
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

    @app.middleware('http')
    async def guard(request,call_next):
        # Every API call, including GET /api/session (which creates a session), must
        # come from this origin. Checked before routing so cross-site requests (e.g. an
        # <img> on another site, or another localhost port) can never consume one of
        # the limited sessions. Clients without browser headers (curl, tests) pass.
        if request.url.path.startswith('/api/') or request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if origin is not None and urlsplit(origin).netloc!=request.headers.get('host'):
                return JSONResponse({'detail':'Nguồn yêu cầu không hợp lệ.'},status_code=403)
            if request.headers.get('sec-fetch-site') not in (None,'same-origin','none'):
                return JSONResponse({'detail':'Nguồn yêu cầu không hợp lệ.'},status_code=403)
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer', 'X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"})
        return response

    def session(request):
        s=request.app.state.store.session(request.cookies.get(COOKIE))
        if not s: raise HTTPException(401,'Phiên đã hết hạn. Tải lại trang và tải hồ sơ mới.')
        return s

    def kind_valid(kind):
        if kind not in ('gpkd','eport'): raise HTTPException(404,'Không tìm thấy loại tài liệu.')

    def document(request,kind):
        kind_valid(kind); s=session(request); d=s['documents'].get(kind)
        if not d: raise HTTPException(404,'Không tìm thấy tài liệu trong phiên.')
        return s,d

    @app.get('/api/session')
    async def get_session(request:Request):
        store=request.app.state.store; await store.cleanup()
        s=store.session(request.cookies.get(COOKIE)); created=s is None
        if created:
            try: s=store.new()
            except Busy: raise HTTPException(503,'Đã đạt giới hạn phiên. Vui lòng thử lại sau.')
        response=JSONResponse(store.public(s))
        if created: response.set_cookie(COOKIE,s['token'],httponly=True,samesite='strict',secure=os.getenv('WEB_SECURE_COOKIE','0')=='1',max_age=store.ttl,path='/')
        return response

    @app.put('/api/documents/{kind}',status_code=202)
    async def upload(kind:str,request:Request):
        kind_valid(kind); s=session(request); store=request.app.state.store
        key=(s['token'],kind)
        if key in store.active_uploads: raise HTTPException(409,'Tệp đang được tải. Vui lòng chờ.')
        if sum(not t.done() for t in store.tasks.values())>=store.queue_size+1:
            raise HTTPException(429,'Hàng đợi đầy. Hãy chờ hoặc hủy tác vụ đang có.')
        store.active_uploads.add(key)
        await store.cancel(s,kind,True)
        generation=s['generations'][kind]
        directory=s['path']/secrets.token_hex(16); directory.mkdir(mode=0o700); path=directory/'input.pdf'
        accepted=False
        try:
            if request.headers.get('content-type','').split(';')[0]!='application/pdf': raise HTTPException(422,'Chỉ nhận file PDF.')
            length=request.headers.get('content-length')
            if length and (not length.isdigit() or int(length)>20*1024*1024): raise HTTPException(413,'PDF vượt giới hạn 20 MB.')
            size=0
            with path.open('wb') as stream:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>20*1024*1024: raise HTTPException(413,'PDF vượt giới hạn 20 MB.')
                    stream.write(chunk)
            path.chmod(0o600)
            with path.open('rb') as stream:
                if not stream.read(1024).lstrip().startswith(b'%PDF-'): raise HTTPException(422,'Nội dung không phải PDF hợp lệ.')
            async with store.preview:
                await store.command('validate',path,directory/'validation.json',20,timeout=15)
            if store.session(s['token']) is not s:
                raise HTTPException(401,'Phiên đã hết hạn trong lúc tải file.')
            if s['generations'].get(kind)!=generation:
                raise HTTPException(409,'Tác vụ tải đã bị hủy hoặc hồ sơ đã thay đổi.')
            d={'id':directory.name,'revision':1,'name':unquote(request.headers.get('x-file-name','document.pdf'))[:200], 'size':size,'state':'queued','detected_kind':'unknown','path':path}
            await store.enqueue(s,kind,d); accepted=True
            return store.public(s)
        except Busy: raise HTTPException(429,'Hàng đợi đầy. Vui lòng thử lại.')
        except (ValueError,TimeoutError) as exc:
            raise HTTPException(422,str(exc) if isinstance(exc,ValueError) else 'Kiểm tra PDF quá thời hạn.') from None
        finally:
            store.active_uploads.discard(key)
            if not accepted: shutil.rmtree(directory,ignore_errors=True)

    @app.delete('/api/documents/{kind}')
    async def delete(kind:str,request:Request):
        kind_valid(kind); s=session(request)
        await request.app.state.store.cancel(s,kind,True)
        return request.app.state.store.public(s)

    @app.post('/api/jobs/{kind}/cancel')
    async def cancel(kind:str,request:Request):
        s,_=document(request,kind); await request.app.state.store.cancel(s,kind)
        return request.app.state.store.public(s)

    @app.get('/api/pages/{kind}/{doc_id}/{page}')
    async def page_image(kind:str,doc_id:str,page:int,request:Request):
        s,d=document(request,kind)
        if d['id']!=doc_id or d['state']!='ready' or not 1<=page<=len(d['pages']): raise HTTPException(404,'Trang không còn trong hồ sơ hiện tại.')
        started=time.monotonic()
        output=d['path'].parent/f'page-{page}.png'
        async with request.app.state.store.preview:
            if not output.exists():
                try: await request.app.state.store.command('page',d['path'],output,page,timeout=20)
                except (ValueError,TimeoutError):
                    output.unlink(missing_ok=True)
                    raise HTTPException(422,'Không tạo được ảnh trang PDF.') from None
            if s['documents'].get(kind) is not d: raise HTTPException(404,'Hồ sơ đã thay đổi.')
            try: data=output.read_bytes()
            except OSError: raise HTTPException(404,'Hồ sơ đã thay đổi.') from None
            request.app.state.store.trim_cache(output)
        return Response(data,media_type='image/png',headers={'Server-Timing':f'render;dur={(time.monotonic()-started)*1000:.1f}'})

    @app.patch('/api/fields/{kind}/{key}')
    async def edit(kind:str,key:str,body:Edit,request:Request):
        s,d=document(request,kind)
        if d['state']!='ready' or key not in d['fields']: raise HTTPException(404,'Không tìm thấy trường dữ liệu.')
        if body.document_id!=d['id'] or body.revision!=d['revision']: raise HTTPException(409,'Hồ sơ đã thay đổi. Tải lại dữ liệu trước khi sửa.')
        if not body.regions: raise HTTPException(422,'Chọn ít nhất một vùng nguồn cho chỉnh sửa.')
        if len(d['fields'][key]['history'])>=100: raise HTTPException(422,'Đã đạt giới hạn 100 chỉnh sửa cho trường này.')
        for r in body.regions:
            x0,y0,x1,y1=r.box
            if r.page>len(d['pages']) or not all(math.isfinite(v) for v in r.box) or not (0<=x0<x1<=1 and 0<=y0<y1<=1):
                raise HTTPException(422,'Trang hoặc tọa độ vùng nguồn không hợp lệ.')
        f=d['fields'][key]
        # Resolving a field with several conflicting candidates must name its source:
        # retained OCR regions may belong to at most one candidate (or be newly drawn).
        submitted=[r.model_dump() for r in body.regions]
        if len(f['candidates'])>1:
            retained=[r for r in submitted if any(same_region(r,x) for c in f['candidates'] for x in c['regions'])]
            consistent=any(all(any(same_region(r,x) for x in c['regions']) for r in retained) for c in f['candidates'])
            if retained and not consistent:
                raise HTTPException(422,'Trường có nhiều ứng viên mâu thuẫn. Chọn vùng nguồn của một ứng viên hoặc vẽ vùng mới trước khi lưu.')
        # Presence is confirmed at one place: pick one suspect location or draw one.
        if key in ('signature','seal') and len(submitted)>1:
            raise HTTPException(422,'Xác nhận hiện diện chữ ký/con dấu chỉ dùng một vùng. Chọn một vùng nghi có hoặc vẽ một vùng mới.')
        before={k:deepcopy(f[k]) for k in ('value','normalized','regions','status')}
        f.update(value=body.value.strip(),normalized=normalize_value(key,body.value),regions=submitted,status='manual' if body.value.strip() else 'missing')
        f['history'].append({'at':time.time(),'before':before,'after':{k:deepcopy(f[k]) for k in before},'reason':body.reason})
        d['revision']+=1
        return f

    @app.get('/api/report')
    async def report(request:Request,download:bool=False):
        s=session(request)
        if not all((d:=s['documents'].get(k)) and d['state']=='ready' and d['detected_kind']==k for k in ('gpkd','eport')):
            raise HTTPException(409,'Cần đủ hai PDF đúng loại và xử lý xong trước khi đối chiếu.')
        result=compare(s['documents'])
        result['documents']={k:{'id':d['id'],'name':d['name'],'revision':d['revision'],'timings':d['timings'],'fields':d['fields']} for k,d in s['documents'].items()}
        headers={'Content-Disposition':'attachment; filename="doi-chieu.json"'} if download else {}
        return JSONResponse(result,headers=headers)

    @app.delete('/api/session')
    async def reset(request:Request):
        s=session(request); s['expires']=0; await request.app.state.store.cleanup()
        r=JSONResponse({'ok':True}); r.delete_cookie(COOKIE); return r

    @app.get('/')
    async def home(): return FileResponse(STATIC/'index.html')
    if STATIC.exists(): app.mount('/static',StaticFiles(directory=STATIC),name='static')
    return app


app=create_app()
