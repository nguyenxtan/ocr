"""OCR improvements must preserve fields/sources and conservative decisions."""
import threading
import fitz
import numpy as np
from app.signatories import OCRLine, OCRWord
from app.web_extract import read_pages


def test_scan_pages_ocr_in_parallel_but_publish_in_page_order(monkeypatch):
    gate=threading.Barrier(2,timeout=2)
    render_threads=[]; ocr_threads=[]
    def render(page):
        render_threads.append(threading.get_ident())
        return np.full((100,100,3),page.number,dtype=np.uint8)
    def recognize(image,lang,psm):
        ocr_threads.append(threading.get_ident())
        gate.wait()
        return [OCRLine((OCRWord('PAGE'+str(int(image[0,0,0])+1),10,10,50,10,95),))]
    monkeypatch.setattr('app.web_extract.render_page',render)
    monkeypatch.setattr('app.web_extract.ocr_lines',recognize)
    with fitz.open() as doc:
        doc.new_page();doc.new_page()
        pages,rows,images=read_pages(doc,'vie+eng')
    assert [r['text'] for r in rows]==['PAGE1','PAGE2']
    assert [r['page'] for r in rows]==[1,2]
    assert len(set(render_threads))==1  # PDF rendering never enters OCR threads.
    assert len(set(ocr_threads))==2 and set(render_threads).isdisjoint(ocr_threads)
    assert list(images)==[1,2]
    assert [p['method'] for p in pages]==['ocr','ocr']
