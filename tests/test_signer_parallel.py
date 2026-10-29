"""Speed up independent OCR pages without changing text, thresholds or PDF access."""
import threading
import time
import numpy as np
import pytest
from app import signatories as signer


@pytest.mark.parametrize('workers', [1, 2])
def test_signer_ocr_is_bounded_but_parallel_when_enabled(monkeypatch, workers):
    monkeypatch.setenv('SIGNER_OCR_WORKERS',str(workers))
    owner=threading.get_ident(); lock=threading.Lock()
    counts={'active':0,'peak':0,'done':0};renders=[]
    def render(page):
        assert threading.get_ident()==owner, 'PyMuPDF rendering cannot move to worker threads'
        renders.append(page)
        return np.zeros((100,100,3),np.uint8)
    def read(image,lang,psm):
        assert lang=='vie+eng' and psm==11
        with lock:
            counts['active']+=1;counts['peak']=max(counts['peak'],counts['active'])
        time.sleep(.06)
        with lock: counts['active']-=1;counts['done']+=1
        return []
    monkeypatch.setattr(signer,'ocr_lines',read)
    result=signer.inspect_signatures([1,2,3,4],render)
    assert renders==[1,2,3,4] and counts['done']==4
    assert counts['peak']==workers
    assert result.status=='NOT_DECLARED'


def test_multiple_pages_keep_same_winner_and_names_as_sequential(monkeypatch):
    def render(page): return np.full((100,100,3),page,np.uint8)
    def read(image,lang,psm):
        page=int(image[0,0,0]);time.sleep(.02 if page==1 else .005);return [page]
    monkeypatch.setattr(signer,'ocr_lines',read)
    monkeypatch.setattr(signer,'merge_visual_rows',lambda lines,h:lines)
    monkeypatch.setattr(signer,'declared_from_lines',lambda lines:'QUAN TUNG ANH' if lines[0]==1 else None)
    monkeypatch.setattr(signer,'signer_from_lines',lambda lines,w,h:('Quan Tùng Anh',97) if lines[0]==2 else None)
    monkeypatch.setenv('SIGNER_OCR_WORKERS','1')
    sequential=signer.inspect_signatures([1,2,3],render)
    monkeypatch.setenv('SIGNER_OCR_WORKERS','2')
    parallel=signer.inspect_signatures([1,2,3],render)
    assert sequential==parallel
    assert parallel.status=='MATCH' and parallel.page==2
