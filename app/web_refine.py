"""Bounded second reading of uncertain text fields from their existing pixel sources.

Does not guess or replace text. A field becomes readable only if every line is
clear and the full re-read agrees with the original, including Vietnamese marks.
"""
import math
import cv2
import pytesseract

NAME_FIELDS={'company_vi','company_en','owner','legal_rep','authorized_rep'}
MAX_REGIONS=6


def recognize_crop(image,lang):
    data=pytesseract.image_to_data(image,lang=lang,config='--psm 7',
                                   output_type=pytesseract.Output.DICT,timeout=3)
    words=[(str(t).strip(),float(c)) for t,c in zip(data['text'],data['conf']) if str(t).strip()]
    return ' '.join(t for t,_ in words),min((c for _,c in words),default=0)


def _crop(images,r):
    image=images.get(r['page'])
    if image is None:return None
    x0,y0,x1,y1=r['box']
    if not all(math.isfinite(v) for v in r['box']) or not (0<=x0<x1<=1 and 0<=y0<y1<=1):return None
    # The second pass is for text lines, never a large area of another form.
    if y1-y0>.06:return None
    h,w=image.shape[:2]
    left,right=max(0,int(x0*w)-5),min(w,int(x1*w)+6)
    top,bottom=max(0,int(y0*h)-5),min(h,int(y1*h)+6)
    if (right-left)*(bottom-top)>200_000:return None
    piece=image[top:bottom,left:right]
    if not piece.size:return None
    piece=cv2.resize(piece,None,fx=2,fy=2,interpolation=cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(piece,10,10,10,10,cv2.BORDER_CONSTANT,value=(255,255,255))


def refine_fields(fields,images,lang,normalize):
    stats={'attempted':0,'confirmed':0}
    for key,f in fields.items():
        if key not in NAME_FIELDS or f['status']!='uncertain' or not f['value'].strip() or len(f['candidates'])!=1:continue
        rs=f['regions']
        if not rs or len(rs)>MAX_REGIONS-stats['attempted']:continue
        crops=[_crop(images,r) for r in rs]
        if any(c is None for c in crops):continue
        parts=[];clear=True
        for crop in crops:
            stats['attempted']+=1
            try:text,score=recognize_crop(crop,lang)
            except Exception:
                clear=False;break  # The first OCR result still remains usable for review.
            parts.append(text)
            if not text or not math.isfinite(score) or not 85<=score<=100:clear=False
        if clear and normalize(' '.join(parts))==normalize(f['value']):
            f['status']='read';f['candidates'][0]['status']='read'
            f['recheck']={'method':'region_ocr','previous_status':'uncertain'}
            stats['confirmed']+=1
    return stats
