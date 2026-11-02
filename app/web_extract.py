"""Session-local PDF extraction with canonical, normalized source rectangles.

Never imports the bot or changes its extraction behavior. No customer content logs.
"""
from __future__ import annotations

from pathlib import Path
import re
import time
import unicodedata

import fitz
import numpy as np
from app.fields import normalize
from app.analysis import render_page, detect_stamps, tax_code_valid
from app.seal_ocr import read_seal
from app.signatories import ocr_lines, signer_from_lines, OCRLine, OCRWord

LABELS = {
    'company_vi': 'Tên doanh nghiệp (VN)', 'company_en': 'Tên doanh nghiệp (EN)',
    'tax_id': 'Mã số doanh nghiệp / MST', 'owner': 'Chủ sở hữu',
    'legal_rep': 'Người đại diện pháp luật', 'registration_id': 'Số giấy ĐKKD',
    'authorized_rep': 'Đại diện có thẩm quyền', 'signer': 'Tên tại vị trí ký',
    'signature': 'Chữ ký', 'seal': 'Con dấu', 'seal_tax_id': 'MST đọc được trên dấu',
    'seal_company': 'Tên doanh nghiệp đọc trên dấu', 'seal_text': 'Nội dung đọc được trên dấu',
}
GPKD_KEYS = ('company_vi','company_en','tax_id','owner','legal_rep')
EPORT_KEYS = ('company_vi','tax_id','registration_id','authorized_rep','signer','signature','seal','seal_tax_id','seal_company','seal_text')


def fold_map(value):
    result, indices = [], []
    for i, c in enumerate(value):
        part = unicodedata.normalize('NFKD', c.replace('đ','d').replace('Đ','D'))
        for v in part:
            if not unicodedata.combining(v):
                result.append(v.upper()); indices.append(i)
    return ''.join(result), indices


def compact(value):
    return ' '.join(normalize(value).split())


def normalize_value(key, value):
    if key in ('tax_id','registration_id','seal_tax_id'):
        return re.sub(r'[^0-9]', '', value)
    return compact(value)


def classify(text):
    n = compact(text)
    g = bool(re.search(r'GIAY CHUNG NHAN DANG KY (?:DOANH NGHIEP|KINH DOANH)', n))
    e = bool(re.search(r'(?:BAN )?DANG KY SU DUNG.{0,60}E\s*PORT', n))
    return 'gpkd' if g and not e else 'eport' if e and not g else 'unknown'


def usable_text(text):
    if len(text.strip()) < 45:
        return False
    bad = text.count('\ufffd') + len(re.findall(r'\(cid:\d+\)', text)) * 8
    good = sum(c.isalpha() for c in text)
    return bad / max(1,len(text)) < .03 and good / max(1,len(text)) > .35


def region(page, box):
    return {'page': page, 'box': [round(max(0.,min(1.,float(v))),6) for v in box]}


def empty_field(key):
    return {'key':key,'label':LABELS[key], 'raw':'', 'value':'','normalized':'',
            'status':'missing','regions':[], 'candidates':[], 'history':[]}


def source(words, page):
    return region(page,[min(w['box'][0] for w in words), min(w['box'][1] for w in words),
                        max(w['box'][2] for w in words), max(w['box'][3] for w in words)])


def rows_from_words(words, page):
    groups=[]
    for w in sorted(words,key=lambda w:(w['box'][1]+w['box'][3],w['box'][0])):
        center=(w['box'][1]+w['box'][3])/2
        height=w['box'][3]-w['box'][1]
        target=next((g for g in reversed(groups[-4:]) if abs(g['cy']-center) < min(g['height'],height)*.50),None)
        if target is None:
            target={'cy':center,'height':height,'words':[]}; groups.append(target)
        target['words'].append(w)
    result=[]
    for group in groups:
        ws=sorted(group['words'],key=lambda w:w['box'][0]); text=''; spans=[]
        for w in ws:
            if text: text+=' '
            spans.append((len(text),len(text)+len(w['text']),w)); text+=w['text']
        result.append({'text':text,'spans':spans,'words':ws,'page':page,'region':source(ws,page)})
    return result


def read_pages(doc, lang):
    pages=[]; all_rows=[]; images={}
    for number,page in enumerate(doc,1):
        original_rotation=page.rotation
        page.set_rotation(0)
        width,height=page.rect.width,page.rect.height
        if width<=0 or height<=0 or width*height > 24_000_000:
            raise ValueError('Kích thước trang PDF vượt giới hạn.')
        words_raw=page.get_text('words', sort=True)
        text=' '.join(w[4] for w in words_raw)
        if usable_text(text):
            words=[{'text':w[4],'box':[w[0]/width,w[1]/height,w[2]/width,w[3]/height], 'confidence':None} for w in words_raw]
            method='text'
        else:
            rgb=render_page(page); images[number]=rgb
            try:
                lines=ocr_lines(rgb,lang,3)
            except (RuntimeError, Exception) as exc:
                # Do not include OCR stderr (can contain paths or document data).
                raise ValueError('OCR không xử lý được trang. Kiểm tra Tesseract và ngôn ngữ.') from None
            ih,iw=rgb.shape[:2]
            words=[{'text':w.text, 'box':[w.x/iw,w.y/ih,(w.x+w.w)/iw,(w.y+w.h)/ih], 'confidence':w.confidence} for l in lines for w in l.words]
            method='ocr'
        # Discard out-of-crop words, clamp tiny floating point overflow.
        words=[{**w,'box':[max(0,min(1,x)) for x in w['box']]} for w in words if w['box'][2]>0 and w['box'][3]>0 and w['box'][0]<1 and w['box'][1]<1]
        words=[w for w in words if w['box'][0]<w['box'][2] and w['box'][1]<w['box'][3]]
        rows=rows_from_words(words,number); all_rows.extend(rows)
        pages.append({'number':number,'width':width,'height':height,'rotation':original_rotation,'method':method})
    return pages, all_rows, images


ALIASES={
 'company_vi': [r'TEN CONG TY VIET BANG TIENG VIET\s*[:.]?',r'TEN DOANH NGHIEP\s*[:.]?',r'TEN CONG TY\s*[:.]?'],
 'company_en': [r'TEN CONG TY VIET BANG TIENG NUOC NGOAI\s*[:.]?',r'TEN (?:CONG TY|DOANH NGHIEP)\s*\(\s*(?:EN|TIENG ANH)\s*\)\s*[:.]?'],
 'tax_id':[r'MA SO DOANH NGHIEP\s*[:.]?',r'(?:MA SO THUE|MST DOANH NGHIEP|MST)\s*[:.]?'],
 'registration_id':[r'(?:SO )?GIAY (?:DKKD|DK KINH DOANH|DANG KY KINH DOANH)\s*[:.]?',r'SO DKKD\s*[:.]?'],
 'authorized_rep':[r'DAI DIEN CO THAM QUYEN(?:\s*\(.*?\))?\s*[:.]?',r'HO TEN NGUOI DAI DIEN\s*[:.]?'],
}
STOP = re.compile(r'\b(?:DIEN THOAI|FAX|NGAY CAP|NOI CAP|CHUC VU|CHUC DANH|GIOI TINH|QUOC TICH|NGAY SINH|SO CMND|SO CCCD|SO DINH DANH|NGAY.{0,12}SINH|SO HO CHIEU|DIA CHI|MA SO|TEN VIET TAT|TEN CONG TY|TEN DOANH NGHIEP|MST|EMAIL|DANG KY LAN|THU DIEN TU)\b')


def candidate(row,start,end=None):
    end=len(row['text']) if end is None else end
    text=row['text'][start:end].strip(' :;.-|')
    if not text: return None
    a=row['text'].find(text,start,end); b=a+len(text)
    words=[w for s,e,w in row['spans'] if e>a and s<b]
    if not words: return None
    confs=[w['confidence'] for w in words if w['confidence'] is not None]
    status='uncertain' if confs and min(confs)<75 else 'read'
    return {'value':text,'regions':[source(words,row['page'])],'status':status}


def add_field(fields,key,c):
    if not c: return
    f=fields[key]; n=normalize_value(key,c['value'])
    if not n: return
    if n not in [normalize_value(key,v['value']) for v in f['candidates']]:
        f['candidates'].append(c)
    elif c['regions'] not in [v['regions'] for v in f['candidates']]:
        f['regions'].extend(c['regions'])
    if len(f['candidates'])>1:
        f['status']='ambiguous'; f['regions']=[r for v in f['candidates'] for r in v['regions']]
    else:
        f.update(raw=c['value'],value=c['value'],normalized=n,status=c['status'],regions=c['regions'])


def extract_fields(rows,kind):
    fields={k:empty_field(k) for k in (GPKD_KEYS if kind=='gpkd' else EPORT_KEYS)}
    context=None
    for i,row in enumerate(rows):
        n,indices=fold_map(row['text']); canon=compact(row['text'])
        if kind=='gpkd':
            if re.search(r'^(?:\d+\s*)?(?:THONG TIN VE )?CHU SO HUU\b',canon): context='owner'
            if re.search(r'^(?:\d+\s*)?(?:THONG TIN VE )?NGUOI DAI DIEN (?:THEO )?PHAP LUAT\b',canon): context='legal_rep'
            if context:
                match=re.search(r'(?:HO(?:,|\s)*VA TEN|HO TEN)\s*[:.]?\s*',n)
                if match:
                    start=indices[match.end()-1]+1
                    stop=STOP.search(n,match.end()); end=indices[stop.start()] if stop else len(row['text'])
                    add_field(fields,context,candidate(row,start,end))
        for key,patterns in ALIASES.items():
            if key not in fields: continue
            matches=[re.search(p,n) for p in patterns]; match=next((m for m in matches if m),None)
            if not match: continue
            # Do not mistake English/abbreviated name labels for the VN label.
            if key=='company_vi' and any(x in canon for x in ('TIENG NUOC NGOAI','TIENG ANH','TEN VIET TAT','VIET TAT')): continue
            start=indices[match.end()-1]+1
            stop=STOP.search(n,match.end()); end=indices[stop.start()] if stop else len(row['text'])
            c=candidate(row,start,end)
            if key in ('tax_id','registration_id') and c:
                m=re.search(r'(?<!\d)\d[\d .-]{7,17}\d(?!\d)',c['value'])
                if not m: c=None
                else:
                    offset=row['text'].find(c['value'],start); c=candidate(row,offset+m.start(),offset+m.end())
                    if c and len(re.sub(r'\D','',c['value'])) not in (10,13): c=None
            if c is None and i+1<len(rows) and rows[i+1]['page']==row['page']:
                nxt=rows[i+1]
                # Only adjacent visual rows, and never consume another field label.
                gap=nxt['region']['box'][1]-row['region']['box'][3]
                if 0<=gap<.025 and not STOP.search(fold_map(nxt['text'])[0]):
                    c=candidate(nxt,0)
            if c and key.startswith('company'):
                # Continue wrapped company names only at the same left margin.
                current=row
                for nxt in rows[i+1:i+3]:
                    if nxt['page']!=row['page'] or STOP.search(fold_map(nxt['text'])[0]): break
                    box=nxt['region']['box']; cb=current['region']['box']
                    if not (0<=box[1]-cb[3]<.018 and abs(box[0]-c['regions'][0]['box'][0])<.06): break
                    if not re.fullmatch(r'[A-Z0-9 &.,()\-/]+',fold_map(nxt['text'])[0]): break
                    c['value']+=' '+nxt['text']; c['regions'].append(nxt['region']); current=nxt
            add_field(fields,key,c)
    return fields


def inspect_marks(doc,pages,rows,images,fields,lang):
    seals=[]; signer_candidates=[]
    for p in pages:
        number=p['number']; width,height=p['width'],p['height']
        page_rows=[r for r in rows if r['page']==number]
        lines=[OCRLine(tuple(OCRWord(w['text'],round(w['box'][0]*width),round(w['box'][1]*height),max(1,round((w['box'][2]-w['box'][0])*width)),max(1,round((w['box'][3]-w['box'][1])*height)),w['confidence'] if w['confidence'] is not None else 100) for w in r['words'])) for r in page_rows]
        signed=signer_from_lines(lines,round(width),round(height))
        if signed:
            found=[r for r in page_rows if compact(signed[0])==compact(r['text'])]
            if found:
                signer_candidates.append({'value':signed[0],'regions':[found[0]['region']],'status':'read' if signed[1]>=85 else 'uncertain'})
        rgb=images.get(number)
        if rgb is None: rgb=render_page(doc[number-1])
        ih,iw=rgb.shape[:2]
        for score,mask,box in detect_stamps(rgb,with_boxes=True):
            if score<.45: continue
            r=region(number,[box[0]/iw,box[1]/ih,box[2]/iw,box[3]/ih])
            evidence=read_seal(mask,lang,tax_code_valid)
            seals.append((score,r,evidence))
    for c in signer_candidates: add_field(fields,'signer',c)
    # Presence of handwritten strokes cannot safely be proved by printed names.
    # Leave signature missing until human review rather than inventing a verdict.
    for score,r,e in seals:
        add_field(fields,'seal',{'value':'Có' if score>=.68 else 'Nghi có','regions':[r],'status':'read' if score>=.68 else 'uncertain'})
        if e.variants:
            text=' | '.join(dict.fromkeys(t for t in e.variants if t.strip()))
            add_field(fields,'seal_text',{'value':text,'regions':[r],'status':'uncertain'})
        for code in e.high_confidence_msts:
            add_field(fields,'seal_tax_id',{'value':code,'regions':[r],'status':'read'})
        # Keep independent OCR words, not the expected company string.
        if len(e.strong_central_tokens)>=2:
            add_field(fields,'seal_company',{'value':' '.join(sorted(e.strong_central_tokens)), 'regions':[r], 'status':'uncertain'})


def extract(path: Path,kind: str,lang='vie+eng',marks=True):
    started=time.monotonic()
    try:
        with fitz.open(path) as doc:
            if not doc.is_pdf or doc.needs_pass or not 1<=len(doc)<=20:
                raise ValueError('PDF không hợp lệ, có mật khẩu hoặc vượt giới hạn 20 trang.')
            pages,rows,images=read_pages(doc,lang)
            read_done=time.monotonic()
            detected=classify('\n'.join(r['text'] for r in rows))
            fields=extract_fields(rows,kind)
            field_done=time.monotonic()
            if kind=='eport' and detected=='eport' and marks:
                inspect_marks(doc,pages,rows,images,fields,lang)
            end=time.monotonic()
            return {'detected_kind':detected,'pages':pages,'fields':fields,
                    'timings':{'read':round(read_done-started,3),'fields':round(field_done-read_done,3), 'marks':round(end-field_done,3),'total':round(end-started,3)},
                    'warnings': ['Chữ ký viết tay cần chọn vùng và xác nhận thủ công; không suy từ tên in.'] if kind=='eport' else []}
    except (fitz.FileDataError,fitz.EmptyFileError):
        raise ValueError('Không đọc được cấu trúc PDF.') from None
