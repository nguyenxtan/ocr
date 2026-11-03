"""Session-local PDF extraction with canonical, normalized source rectangles.

Never imports the bot or changes its extraction behavior. No customer content logs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import time
import unicodedata

import fitz
import cv2
import numpy as np
from app.web_refine import refine_fields
from app.fields import normalize
from app.analysis import render_page, detect_stamps, tax_code_valid, red_mask
from app.seal_ocr import read_seal
from app.signatories import ocr_lines, signature_anchors, candidate_from_line, OCRLine, OCRWord

LABELS = {
    'company_vi': 'Tên doanh nghiệp (VN)', 'company_en': 'Tên doanh nghiệp (EN)',
    'tax_id': 'Mã số doanh nghiệp / MST', 'owner': 'Chủ sở hữu',
    'legal_rep': 'Người đại diện pháp luật', 'registration_id': 'Số giấy ĐKKD',
    'authorized_rep': 'Đại diện có thẩm quyền', 'signer': 'Tên tại vị trí ký',
    'signature': 'Chữ ký', 'seal': 'Con dấu', 'seal_tax_id': 'MST đọc được trên dấu',
    'seal_company': 'Tên doanh nghiệp đọc trên dấu', 'seal_text': 'Nội dung đọc được trên dấu',
}
GPKD_KEYS = ('company_vi','company_en','tax_id','owner','legal_rep','seal')
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


def exact_text(value):
    """Accent-preserving key: NFC, upper case, punctuation as space, collapsed spaces.

    Unlike compact(), letters with different Vietnamese marks (HÙNG/HƯNG) stay
    different, and every token, including short tokens and legal type, is kept.
    """
    value=unicodedata.normalize('NFC',str(value or '')).upper()
    value=''.join(' ' if unicodedata.category(c).startswith('P') or c.isspace() else c for c in value)
    return ' '.join(value.split())


def normalize_value(key, value):
    if key in ('tax_id','registration_id','seal_tax_id'):
        return re.sub(r'[\s.\-]', '', value).upper()
    return exact_text(value)


def classify(text):
    n = compact(text)
    g = bool(re.search(r'GIAY CHUNG NHAN DANG KY (?:DOANH NGHIEP|KINH DOANH)', n))
    e = bool(re.search(r'(?:BAN )?DANG KY SU DUNG.{0,60}E\s*PORT', n))
    return 'gpkd' if g and not e else 'eport' if e and not g else 'unknown'


def usable_text(text):
    if len(text.strip()) < 45:
        return False
    bad = text.count('\ufffd') + len(re.findall(r'\(cid:\d+\)', text)) * 8 + sum(ord(c)<32 and not c.isspace() for c in text)
    good = sum(c.isalpha() for c in text)
    known = set(compact(text).split()) & set('TEN MA SO NGUOI CONG TY CHU GIAY DANG KY DOANH NGHIEP CHUNG NHAN HO VA PHAP LUAT EPORT PORT THONG TIN THE COMPANY NAME REGISTRATION CERTIFICATE INVOICE TAX'.split())
    return bad / max(1,len(text)) < .03 and good / max(1,len(text)) > .35 and len(known)>=3


def _luminance(color, components):
    c=[float(v) for v in (color or ())]
    if components==1 and c: return c[0]
    if components==4 and len(c)==4:
        k=c[3]; r,g,b=((1-min(1,v+k)) for v in c[:3])
    elif len(c)>=3: r,g,b=c[:3]
    else: return 0.0
    return .2126*r+.7152*g+.0722*b


def hidden_text_layer(page):
    """True when any text span may not be visible as rendered.

    Distrusted (whole page then goes to OCR of the rendered image): invisible render
    mode, non-opaque or near-white fill, sub-point size, or text whose box is later
    fully covered by a filled path, shading or image. Conservative: white-on-dark
    and searchable scans with an invisible OCR layer are also OCRed. This is a
    visibility check only; it says nothing about authenticity.
    """
    for span in page.get_texttrace():
        if all(chr(ch[0]).isspace() for ch in span['chars']): continue
        if span['type']==3 or span['opacity']<.98 or span['size']<1: return True
        if span['type']==0 and _luminance(span['color'],span['colorspace'])>.9: return True
    texts=[]; covers=[]
    for i,(kind,rect) in enumerate(page.get_bboxlog()):
        if kind.endswith('-text'): texts.append((i,rect))
        elif kind in ('fill-path','fill-image','fill-shade','fill-imgmask'): covers.append((i,*rect))
    if not texts or not covers: return False
    cover=np.array(covers,dtype=float); tol=.75
    for i,(x0,y0,x1,y1) in texts:
        if x1<=x0 or y1<=y0: continue
        later=cover[cover[:,0]>i]
        if not len(later): continue
        if np.any((later[:,1]<=x0+tol)&(later[:,2]<=y0+tol)&(later[:,3]>=x1-tol)&(later[:,4]>=y1-tol)): return True
    return False


def region(page, box):
    return {'page': page, 'box': [round(max(0.,min(1.,float(v))),6) for v in box]}


def empty_field(key):
    return {'key':key,'label':LABELS[key], 'raw':'', 'value':'','normalized':'',
            'status':'missing','regions':[], 'candidates':[], 'history':[]}


def source(words, page):
    return region(page,[min(w['box'][0] for w in words), min(w['box'][1] for w in words),
                        max(w['box'][2] for w in words), max(w['box'][3] for w in words)])


def rows_from_words(words, page):
    """Group words into visual lines using layout (content-space) geometry.

    Each word has 'layout' (unrotated content space, used only for parsing) and
    'box' (displayed page, published as evidence). For unrotated/OCR pages both
    are equal. Rows expose 'layout' for adjacency checks and 'region' for evidence.
    """
    groups=[]
    for w in words: w.setdefault('layout',list(w['box']))
    for w in sorted(words,key=lambda w:(w['layout'][1]+w['layout'][3],w['layout'][0])):
        center=(w['layout'][1]+w['layout'][3])/2
        height=w['layout'][3]-w['layout'][1]
        target=next((g for g in reversed(groups[-4:]) if abs(g['cy']-center) < min(g['height'],height)*.50),None)
        if target is None:
            target={'cy':center,'height':height,'words':[]}; groups.append(target)
        target['words'].append(w)
    result=[]
    for group in groups:
        ws=sorted(group['words'],key=lambda w:w['layout'][0]); text=''; spans=[]
        for w in ws:
            if text: text+=' '
            spans.append((len(text),len(text)+len(w['text']),w)); text+=w['text']
        result.append({'text':text,'spans':spans,'words':ws,'page':page,'region':source(ws,page),'layout':layout_box(ws)})
    return result


def layout_box(words):
    return [min(w['layout'][0] for w in words),min(w['layout'][1] for w in words),max(w['layout'][2] for w in words),max(w['layout'][3] for w in words)]


def read_pages(doc, lang):
    """Render/read PDF on one thread; run at most two Tesseract calls at once.

    No PyMuPDF object enters OCR threads. Futures are consumed in document order,
    preserving page provenance even if the second scan finishes before the first.
    """
    pages=[]; all_rows=[]; images={}; prepared=[]
    pool=ThreadPoolExecutor(max_workers=2,thread_name_prefix='web-page-ocr')
    try:
        for number,page in enumerate(doc,1):
            width,height=page.rect.width,page.rect.height
            if width<=0 or height<=0 or width*height>24_000_000:
                raise ValueError('Kích thước trang PDF vượt giới hạn.')
            info={'number':number,'width':width,'height':height,'rotation':page.rotation}
            text=page.get_text('text')
            if usable_text(text) and not hidden_text_layer(page):
                nw,nh=page.cropbox.width,page.cropbox.height
                words=[{'text':w[4],'box':[w[0]/nw,w[1]/nh,w[2]/nw,w[3]/nh],'confidence':None}
                       for w in page.get_text('words',sort=True)]
                pending=None; method='text'
                matrix=page.rotation_matrix
            else:
                rgb=render_page(page); images[number]=rgb
                pending=pool.submit(ocr_lines,rgb,lang,3)
                words=None; method='ocr'; nw=nh=matrix=None
            info['method']=method
            prepared.append((info,words,pending,nw,nh,matrix))
        for info,words,pending,nw,nh,matrix in prepared:
            number=info['number'];width,height=info['width'],info['height']
            if pending is not None:
                try: lines=pending.result()
                except Exception:
                    for item in prepared:
                        if item[2] is not None: item[2].cancel()
                    raise ValueError('OCR không xử lý được trang. Kiểm tra Tesseract và ngôn ngữ.') from None
                ih,iw=images[number].shape[:2]
                words=[{'text':w.text,'box':[w.x/iw,w.y/ih,(w.x+w.w)/iw,(w.y+w.h)/ih],'confidence':w.confidence}
                       for line in lines for w in line.words]
            words=[{**w,'box':[max(0,min(1,x)) for x in w['box']]} for w in words
                   if w['box'][2]>0 and w['box'][3]>0 and w['box'][0]<1 and w['box'][1]<1]
            words=[w for w in words if w['box'][0]<w['box'][2] and w['box'][1]<w['box'][3]]
            for word in words: word['layout']=list(word['box'])
            if info['method']=='text' and info['rotation']:
                for word in words:
                    box=word['layout']
                    rect=fitz.Rect(box[0]*nw,box[1]*nh,box[2]*nw,box[3]*nh)*matrix
                    word['box']=[max(0,min(1,v)) for v in (rect.x0/width,rect.y0/height,rect.x1/width,rect.y1/height)]
            all_rows.extend(rows_from_words(words,number));pages.append(info)
        return pages,all_rows,images
    finally:
        pool.shutdown(wait=True,cancel_futures=True)


ALIASES={
 'company_vi': [r'TEN CONG TY VIET BANG TIENG VIET\s*[:.]?',r'TEN DOANH NGHIEP\s*[:.]?',r'TEN CONG TY\s*[:.]?'],
 'company_en': [r'TEN CONG TY VIET BANG TIENG NUOC NGOAI\s*[:.]?',r'TEN (?:CONG TY|DOANH NGHIEP)\s*\(\s*(?:EN|TIENG ANH)\s*\)\s*[:.]?'],
 'tax_id':[r'MA SO DOANH NGHIEP\s*[:.]?',r'(?:MA SO THUE|MST DOANH NGHIEP|MST)\s*[:.]?'],
 'registration_id':[r'(?:SO )?GIAY (?:DKKD|DK KINH DOANH|DANG KY KINH DOANH)\s*[:.]?',r'SO DKKD\s*[:.]?'],
 'authorized_rep':[r'DAI DIEN CO THAM QUYEN(?:\s*\(.*?\))?\s*[:.]?',r'HO TEN NGUOI DAI DIEN\s*[:.]?'],
}
STOP = re.compile(r'\b(?:DIEN THOAI|FAX|NGAY CAP|NOI CAP|CHUC VU|CHUC DANH|CHUC(?=\s*[|/])|GIOI TINH|QUOC TICH|NGAY SINH|SO CMND|SO CCCD|SO DINH DANH|NGAY.{0,12}SINH|SO HO CHIEU|DIA CHI|MA SO|TEN VIET TAT|TEN CONG TY|TEN DOANH NGHIEP|MST|EMAIL|DANG KY LAN|THU DIEN TU)\b')


def candidate(row,start,end=None):
    end=len(row['text']) if end is None else end
    text=row['text'][start:end].strip(' :;.-|_')
    if not text: return None
    a=row['text'].find(text,start,end); b=a+len(text)
    words=[w for s,e,w in row['spans'] if e>a and s<b]
    if not words: return None
    confs=[w['confidence'] for w in words if w['confidence'] is not None]
    status='uncertain' if confs and min(confs)<85 else 'read'
    return {'value':text,'regions':[source(words,row['page'])],'status':status,'layout_x0':layout_box(words)[0]}


def add_field(fields,key,c):
    if not c: return
    c={k:v for k,v in c.items() if k!='layout_x0'}  # parsing-only geometry is never published
    f=fields[key]; n=normalize_value(key,c['value'])
    if not n: return
    existing=next((v for v in f['candidates'] if normalize_value(key,v['value'])==n),None)
    if existing:
        for r in c['regions']:
            if r not in existing['regions']: existing['regions'].append(r)
        if c['status']=='uncertain': existing['status']='uncertain'
    else:
        f['candidates'].append(c)
    f['regions']=[r for v in f['candidates'] for r in v['regions']]
    if len(f['candidates'])>1:
        f['status']='ambiguous'
    else:
        picked=f['candidates'][0]
        f.update(raw=picked['value'],value=picked['value'],normalized=n,status=picked['status'])



def extract_fields(rows,kind):
    fields={k:empty_field(k) for k in (GPKD_KEYS if kind=='gpkd' else EPORT_KEYS)}
    if kind=='gpkd':fields['seal']['label']='Mộc cơ quan cấp trên GPKD'
    context=None
    for i,row in enumerate(rows):
        n,indices=fold_map(row['text']); canon=compact(row['text'])
        if kind=='gpkd':
            if re.search(r'^(?:\d+\s*)?(?:THONG TIN VE )?CHU SO HUU\b',canon): context='owner'
            if re.search(r'^(?:\d+\s*)?(?:THONG TIN VE )?NGUOI DAI DIEN (?:THEO )?PHAP LUAT\b',canon): context='legal_rep'
            if context:
                match=re.search(r'(?:HO(?:,?\s*CHU DEM)?\s*(?:VA\s*)?TEN)\s*[:.]?\s*',n)
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
            c=candidate(row,start,end); value_row_index=i
            if key in ('tax_id','registration_id') and c:
                m=re.search(r'(?<!\d)\d[\d .-]{7,17}\d(?!\d)',c['value'])
                if not m: c=None
                else:
                    offset=row['text'].find(c['value'],start); c=candidate(row,offset+m.start(),offset+m.end())
                    if c and len(re.sub(r'\D','',c['value'])) not in (10,13): c=None
            if c is None and i+1<len(rows) and rows[i+1]['page']==row['page']:
                nxt=rows[i+1]
                # Only adjacent visual rows, and never consume another field label.
                gap=nxt['layout'][1]-row['layout'][3]
                if 0<=gap<.025 and not STOP.search(fold_map(nxt['text'])[0]):
                    c=candidate(nxt,0); value_row_index=i+1
            if c and key.startswith('company'):
                # Continue wrapped company names only at the same left margin.
                current=rows[value_row_index]
                for nxt in rows[value_row_index+1:value_row_index+3]:
                    if nxt['page']!=row['page'] or STOP.search(fold_map(nxt['text'])[0]): break
                    box=nxt['layout']; cb=current['layout']
                    if not (0<=box[1]-cb[3]<.018 and min(abs(box[0]-c['layout_x0']),abs(box[0]-row['layout'][0]))<.06): break
                    if not re.fullmatch(r'[A-Z0-9 &.,()\-/]+',fold_map(nxt['text'])[0]): break
                    continuation=candidate(nxt,0)
                    c['value']+=' '+nxt['text']; c['regions'].append(nxt['region']); current=nxt
                    if continuation and continuation['status']=='uncertain': c['status']='uncertain'
            if c and key in ('tax_id','registration_id') and len(normalize_value(key,c['value'])) not in (10,13): c=None
            add_field(fields,key,c)
    return fields


def signature_ink_regions(rgb, rows):
    """Locate unrecognized ink near signing titles; never claims authenticity/presence.

    Printed OCR words, red seal ink, and long form rules are removed. Remaining
    joined strokes are only candidates for human review; blue text/noise may remain.
    """
    ih,iw=rgb.shape[:2]
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    ink=cv2.inRange(gray,0,175)
    ink[red_mask(rgb)>0]=0
    for row in rows:
        for word in row['words']:
            x0,y0,x1,y1=word['box']
            ink[max(0,int(y0*ih)-2):min(ih,int(y1*ih)+3),max(0,int(x0*iw)-2):min(iw,int(x1*iw)+3)]=0
    for kernel in ((max(20,iw//12),1),(1,max(20,ih//12))):
        lines=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones(kernel[::-1],np.uint8))
        ink=cv2.subtract(ink,lines)
    result=[]
    for row in rows:
        n=compact(row['text'])
        if not (n.startswith(('DAI DIEN DOANH NGHIEP','DAI DIEN KHACH HANG','NGUOI KY')) or n in ('GIAM DOC','TONG GIAM DOC','CHU TICH')): continue
        x0,y0,x1,y1=row['region']['box']; cx=(x0+x1)/2
        left=max(0,int((cx-.22)*iw));right=min(iw,int((cx+.22)*iw))
        top=int(y1*ih);bottom=min(ih,int((y1+.22)*ih))
        window=ink[top:bottom,left:right]
        if not window.size: continue
        joined=cv2.morphologyEx(window,cv2.MORPH_CLOSE,np.ones((3,7),np.uint8))
        contours,_=cv2.findContours(joined,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,w,h=cv2.boundingRect(contour)
            count=cv2.countNonZero(window[y:y+h,x:x+w])
            if w>iw*.035 and h>ih*.012 and count>40 and count/(w*h)<.55:
                result.append([(left+x)/iw,(top+y)/ih,(left+x+w)/iw,(top+y+h)/ih])
    return result[:8]


def store_seal_presence(fields,seals):
    if not seals:return
    score=max(s for s,_ in seals)
    add_field(fields,'seal',{'value':'Có' if score>=.68 else 'Nghi có',
              'regions':[r for _,r in seals],'status':'read' if score>=.68 else 'uncertain'})


def inspect_registration_seal(doc,pages,images,fields):
    """Presence of the issuing seal only, never company/MST matching on this seal."""
    seals=[]
    for p in pages:
        number=p['number'];rgb=images.get(number)
        if rgb is None:rgb=render_page(doc[number-1])
        h,w=rgb.shape[:2]
        for score,_,box in detect_stamps(rgb,with_boxes=True):
            if score>=.45:
                seals.append((score,region(number,[box[0]/w,box[1]/h,box[2]/w,box[3]/h])))
    store_seal_presence(fields,seals)


def inspect_marks(doc,pages,rows,images,fields,lang):
    seals=[]; signer_candidates=[]
    for p in pages:
        number=p['number']; width,height=p['width'],p['height']
        if p['method']=='text' and p['rotation']%180: width,height=height,width  # layout space of a rotated text page
        page_rows=[r for r in rows if r['page']==number]
        # Signing-title geometry ("name below title") is evaluated in layout space.
        lines=[OCRLine(tuple(OCRWord(w['text'],round(w['layout'][0]*width),round(w['layout'][1]*height),max(1,round((w['layout'][2]-w['layout'][0])*width)),max(1,round((w['layout'][3]-w['layout'][1])*height)),w['confidence'] if w['confidence'] is not None else 100) for w in r['words'])) for r in page_rows]
        # Preserve the selected row identity, never rematch a repeated name globally.
        anchors=signature_anchors(lines); selected_candidates=[]
        for anchor in anchors:
            cx=(anchor.x+anchor.right)/2
            for line,row in zip(lines,page_rows):
                if anchor.y<height*.12 or not 0<=line.y-anchor.bottom<=height*.26: continue
                if abs((line.x+line.right)/2-cx)>width*.22: continue
                picked=candidate_from_line(line)
                if picked:
                    name,confidence=picked
                    rank=confidence-(line.y-anchor.bottom)/height*30
                    selected_candidates.append((rank,name,confidence,row))
        if selected_candidates:
            _,name,confidence,row=max(selected_candidates,key=lambda item:item[0])
            signer_candidates.append({'value':name,'regions':[row['region']],'status':'read' if confidence>=85 else 'uncertain'})
        rgb=images.get(number)
        if rgb is None: rgb=render_page(doc[number-1])
        ih,iw=rgb.shape[:2]
        for box in signature_ink_regions(rgb,page_rows):
            add_field(fields,'signature',{'value':'Nghi có','regions':[region(number,box)],'status':'uncertain'})
        for score,mask,box in detect_stamps(rgb,with_boxes=True):
            if score<.45: continue
            r=region(number,[box[0]/iw,box[1]/ih,box[2]/iw,box[3]/ih])
            evidence=read_seal(mask,lang,tax_code_valid)
            seals.append((score,r,evidence))
    for c in signer_candidates: add_field(fields,'signer',c)
    # Presence of handwritten strokes cannot safely be proved by printed names.
    # Leave signature missing until human review rather than inventing a verdict.
    store_seal_presence(fields,[(score,r) for score,r,_ in seals])
    for score,r,e in seals:
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
            recheck=refine_fields(fields,images,lang,exact_text) if detected==kind else {'attempted':0,'confirmed':0}
            recheck_done=time.monotonic()
            if detected==kind and marks:
                if kind=='eport':inspect_marks(doc,pages,rows,images,fields,lang)
                else:inspect_registration_seal(doc,pages,images,fields)
            end=time.monotonic()
            return {'detected_kind':detected,'pages':pages,'fields':fields,'ocr_recheck':recheck,
                    'timings':{'read':round(read_done-started,3),'fields':round(field_done-read_done,3), 'recheck':round(recheck_done-field_done,3),'marks':round(end-recheck_done,3),'total':round(end-started,3)},
                    'warnings': ['Chữ ký viết tay cần chọn vùng và xác nhận thủ công; không suy từ tên in.'] if kind=='eport' else []}
    except (fitz.FileDataError,fitz.EmptyFileError):
        raise ValueError('Không đọc được cấu trúc PDF.') from None
