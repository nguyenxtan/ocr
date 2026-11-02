"""Single-process session store; bounded jobs, process-group cancellation, TTL."""
from __future__ import annotations
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import sys
import tempfile
import time


class Busy(Exception): pass


class Store:
    def __init__(self, root=None, timeout=180, ttl=1800, max_sessions=8, queue_size=3):
        parent=Path(root or tempfile.gettempdir())
        for stale in parent.glob('ocr-pair-web-*'):
            if not stale.is_symlink() and stale.is_dir() and (stale/'.ocr-web-root').is_file():
                if stale.stat().st_uid==os.getuid() and stale.stat().st_mtime<time.time()-max(ttl,3600):
                    shutil.rmtree(stale,ignore_errors=True)
        self.root=Path(tempfile.mkdtemp(prefix='ocr-pair-web-',dir=parent)); self.root.chmod(0o700)
        (self.root/'.ocr-web-root').write_text('v1')
        self.timeout=timeout; self.ttl=ttl; self.max_sessions=max_sessions; self.queue_size=queue_size
        self.sessions={}; self.tasks={}; self.work=asyncio.Semaphore(1); self.preview=asyncio.Semaphore(1)
        self.active_uploads=set(); self.janitor=None

    def session(self, token):
        s=self.sessions.get(token)
        return s if s and s['expires']>time.time() else None

    def new(self):
        if len(self.sessions)>=self.max_sessions: raise Busy()
        token=secrets.token_urlsafe(32); directory=self.root/token; directory.mkdir(mode=0o700)
        s={'token':token,'path':directory,'expires':time.time()+self.ttl,'documents':{},'generations':{}}
        self.sessions[token]=s; return s

    def public(self,s):
        docs={}
        for kind,d in s['documents'].items():
            docs[kind]={k:v for k,v in d.items() if k not in ('path','task')}
            docs[kind]['page_url']=f"/api/pages/{kind}/{d['id']}/1"
        return {'documents':docs,'expires_at':s['expires'],'limits':{'max_mb':20,'max_pages':20},'queue_capacity':self.queue_size+1}

    async def command(self,mode,path,output,*args,timeout=None):
        proc=await asyncio.create_subprocess_exec(sys.executable,'-m','app.web_worker',mode,str(path),str(output),*[str(a) for a in args],stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,start_new_session=True,env={**os.environ,'OMP_THREAD_LIMIT':'1','WORKER_CPU_SECONDS':str(self.timeout)})
        try:
            await asyncio.wait_for(proc.wait(),timeout or self.timeout)
        except BaseException:
            with contextlib.suppress(ProcessLookupError): os.killpg(proc.pid,signal.SIGKILL)
            await proc.wait(); raise
        if mode=='page' and proc.returncode==0: return None
        try: result=json.loads(output.read_text())
        except (OSError,ValueError): raise ValueError('Tiến trình OCR dừng hoặc vượt giới hạn tài nguyên.') from None
        if proc.returncode or 'error' in result:
            raise ValueError(result.get('error','Không xử lý được PDF.'))
        return result

    async def cancel(self,s,kind,remove=False):
        s['generations'][kind]=s['generations'].get(kind,0)+1
        key=(s['token'],kind); task=self.tasks.get(key)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError): await task
            self.tasks.pop(key,None)
        d=s['documents'].get(kind)
        if d:
            if remove:
                s['documents'].pop(kind,None); shutil.rmtree(d['path'].parent,ignore_errors=True)
            elif d['state'] in ('queued','running'):
                d['state']='cancelled'; d.pop('fields',None)

    async def enqueue(self,s,kind,d):
        if sum(not t.done() for t in self.tasks.values()) >= self.queue_size+1: raise Busy()
        s['documents'][kind]=d
        key=(s['token'],kind)
        async def execute():
            queued=time.monotonic()
            try:
                async with self.work:
                    d['state']='running'; start=time.monotonic()
                    result=await self.command('extract',d['path'],d['path'].parent/'result.json',kind,os.getenv('OCR_LANG','vie+eng'))
                    if s['documents'].get(kind) is not d: return
                    d.update(result); d['timings']['queue']=round(start-queued,3); d['state']='ready'
            except asyncio.CancelledError:
                d['state']='cancelled'; raise
            except (ValueError,TimeoutError):
                d['state']='error'; d['error']='Không hoàn tất OCR: lỗi đọc PDF, OCR hoặc quá thời hạn. Có thể thay tệp và thử lại.'
                d.pop('fields',None)
            finally:
                if self.tasks.get(key) is asyncio.current_task(): self.tasks.pop(key,None)
        self.tasks[key]=asyncio.create_task(execute())

    def trim_cache(self,keep,limit=64*1024*1024):
        files=sorted(self.root.glob('*/*/page-*.png'),key=lambda p:p.stat().st_mtime)
        total=sum(p.stat().st_size for p in files)
        for p in files:
            if total<=limit: break
            if p!=keep:
                total-=p.stat().st_size; p.unlink(missing_ok=True)

    async def cleanup(self):
        for token,s in list(self.sessions.items()):
            if s['expires']<=time.time():
                for kind in list(s['documents']): await self.cancel(s,kind,True)
                shutil.rmtree(s['path'],ignore_errors=True); self.sessions.pop(token,None)

    async def sweep(self):
        while True:
            await asyncio.sleep(10); await self.cleanup()

    async def close(self):
        if self.janitor:
            self.janitor.cancel()
            with contextlib.suppress(asyncio.CancelledError): await self.janitor
        for s in list(self.sessions.values()):
            for kind in list(s['documents']): await self.cancel(s,kind,True)
        shutil.rmtree(self.root,ignore_errors=True)
