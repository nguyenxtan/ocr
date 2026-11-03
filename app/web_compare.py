"""Conservative comparisons; absence, ambiguity and OCR uncertainty never match."""
import re
from app.web_extract import compact, exact_text, normalize_value

READABLE={'read','manual'}
LABELS={'PASS':'Đạt','REVIEW':'Cần kiểm tra','FAIL':'Không đạt'}
# Spelling of the same legal form. Used only to downgrade a mismatch to REVIEW,
# never to produce PASS: the full accent-preserving name must still be equal.
LEGAL_FORMS=((r'\bTRACH NHIEM HUU HAN\b','TNHH'),(r'\bMOT THANH VIEN\b','MTV'),(r'\bCONG TY CO PHAN\b','CONG TY CP'),(r'\bCTCP\b','CONG TY CP'))


def loose_company(value):
    n=compact(value)
    for pattern,short in LEGAL_FORMS: n=re.sub(pattern,short,n)
    return n


def name_result(av,bv,mode):
    """PASS only for identical full names (NFC/case/space/punctuation only).

    Folding accents or legal-form spelling may explain an OCR difference, so those
    cases go to REVIEW; they can never PASS (HÙNG and HƯNG are different names).
    """
    if exact_text(av)==exact_text(bv): return 'same'
    near=loose_company if mode=='company' else compact
    return 'near' if near(av)==near(bv) else 'different'


def compare(documents):
    g=documents['gpkd']['fields']; e=documents['eport']['fields']; rows=[]
    def field(fields,key):
        return fields.get(key,{'value':'','status':'missing','regions':[]})
    def readable(f):
        return bool(f.get('value')) and f.get('status') in READABLE
    def add(key,label,a,b,mode='text',different='FAIL'):
        status='REVIEW'; reason='Thiếu dữ liệu, chưa đọc rõ hoặc có nhiều giá trị; cần kiểm tra bản gốc.'
        if readable(a) and readable(b):
            av,bv=a['value'],b['value']
            if mode=='id':
                av,bv=normalize_value('tax_id',av),normalize_value('tax_id',bv)
                valid=bool(re.fullmatch(r'(?:[0-9]{10}|[0-9]{13})',av) and re.fullmatch(r'(?:[0-9]{10}|[0-9]{13})',bv))
                same=av==bv
            else:
                valid=True; result=name_result(av,bv,mode); same=result=='same'
            if valid:
                status='PASS' if same else different
                reason='Hai giá trị đọc được khớp sau chuẩn hóa.' if same else ('Hai giá trị khác nhau; yêu cầu kiểm tra giấy ủy quyền, không suy luận thẩm quyền pháp lý.' if different=='REVIEW' else 'Hai giá trị đọc được khác nhau; kiểm tra lại vùng nguồn.')
                if mode!='id' and result=='near':
                    status='REVIEW'; reason='Chỉ khác dấu tiếng Việt hoặc cách viết loại hình doanh nghiệp; không tự xem là khớp, cần đối chiếu bản gốc.'+(' Nếu khác người, yêu cầu kiểm tra giấy ủy quyền.' if different=='REVIEW' else '')
        rows.append({'id':key,'label':label,'status':status,'reason':reason,'left':a,'right':b})
    add('tax_id','Mã số doanh nghiệp / MST',field(g,'tax_id'),field(e,'tax_id'),'id')
    add('registration','Số giấy ĐKKD',field(g,'tax_id'),field(e,'registration_id'),'id')
    add('company','Tên doanh nghiệp',field(g,'company_vi'),field(e,'company_vi'),'company')
    add('representative','Đại diện pháp luật ↔ Đại diện EPORT',field(g,'legal_rep'),field(e,'authorized_rep'),different='REVIEW')
    add('signer','Đại diện EPORT ↔ Tên tại vị trí ký',field(e,'authorized_rep'),field(e,'signer'),different='REVIEW')
    seal_id=field(e,'seal_tax_id')
    if seal_id.get('status')=='ambiguous':
        add('seal_identity','Thông tin doanh nghiệp trên dấu',field(e,'tax_id'),seal_id,'id')
    elif readable(seal_id):
        add('seal_identity','MST trên dấu ↔ MST EPORT',field(e,'tax_id'),seal_id,'id')
    else:
        add('seal_identity','Tên trên dấu (MST chưa đọc rõ)',field(e,'company_vi'),field(e,'seal_company'),'company')
        rows[-1]['reason']='MST trên dấu chưa đọc rõ. '+rows[-1]['reason']
    for key,label,kind,fs,field_key in (('signature','Hiện diện chữ ký EPORT','eport',e,'signature'),('seal','Hiện diện mộc EPORT','eport',e,'seal'),('gpkd_seal','Hiện diện mộc cơ quan cấp trên GPKD','gpkd',g,'seal')):
        b=field(fs,field_key); status='REVIEW'; reason='Chưa xác định chắc hiện diện; cần kiểm tra vùng nguồn trên '+kind.upper()+'.'
        if readable(b):
            if compact(b['value']) in ('CO','PRESENT'):
                status='PASS'; reason='Ghi nhận hiện diện; không xác thực thật–giả hoặc giá trị pháp lý.'
            elif compact(b['value']) in ('KHONG','ABSENT','KHONG CO') and b['status']=='manual':
                status='FAIL'; reason='Người kiểm tra xác nhận không có tại vùng đã chọn.'
        rows.append({'id':key,'label':label,'status':status,'reason':reason,'left':{'value':'Yêu cầu hiện diện trên '+kind.upper(),'regions':[]},'right':b,'left_kind':kind,'right_kind':kind,'type':'presence'})
    conclusion='FAIL' if any(r['status']=='FAIL' for r in rows) else 'REVIEW' if any(r['status']=='REVIEW' for r in rows) else 'PASS'
    return {'conclusion':conclusion,'label':LABELS[conclusion],'rows':rows,
            'counts':{s:sum(r['status']==s for r in rows) for s in LABELS},
            'notice':'Chỉ đối chiếu nội dung và hiện diện. Không xác thực thật–giả hay thẩm quyền pháp lý.'}
