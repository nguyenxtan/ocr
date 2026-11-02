"""Conservative comparisons; absence, ambiguity and OCR uncertainty never match."""
from app.web_extract import compact, normalize_value
from app.seal_ocr import strict_name_match

READABLE={'read','manual'}
LABELS={'PASS':'Đạt','REVIEW':'Cần kiểm tra','FAIL':'Không đạt'}


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
                valid=len(av) in (10,13) and len(bv) in (10,13)
                same=av==bv
            else:
                valid=True; same=compact(av)==compact(bv)
                if mode=='company': same=strict_name_match(av,bv)
            if valid:
                status='PASS' if same else different
                reason='Hai giá trị đọc được khớp sau chuẩn hóa.' if same else ('Hai giá trị khác nhau; yêu cầu kiểm tra giấy ủy quyền, không suy luận thẩm quyền pháp lý.' if different=='REVIEW' else 'Hai giá trị đọc được khác nhau; kiểm tra lại vùng nguồn.')
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
    for key,label in (('signature','Hiện diện chữ ký'),('seal','Hiện diện con dấu')):
        b=field(e,key); status='REVIEW'; reason='Chưa xác định chắc hiện diện; cần kiểm tra vùng ký trên EPORT.'
        if readable(b):
            if compact(b['value']) in ('CO','PRESENT'):
                status='PASS'; reason='Ghi nhận hiện diện; không xác thực thật–giả hoặc giá trị pháp lý.'
            elif compact(b['value']) in ('KHONG','ABSENT','KHONG CO') and b['status']=='manual':
                status='FAIL'; reason='Người kiểm tra xác nhận không có tại vùng đã chọn.'
        rows.append({'id':key,'label':label,'status':status,'reason':reason,'left':{'value':'Không đối chiếu với dấu cơ quan cấp GPKD','regions':[]},'right':b})
    conclusion='FAIL' if any(r['status']=='FAIL' for r in rows) else 'REVIEW' if any(r['status']=='REVIEW' for r in rows) else 'PASS'
    return {'conclusion':conclusion,'label':LABELS[conclusion],'rows':rows,
            'counts':{s:sum(r['status']==s for r in rows) for s in LABELS},
            'notice':'Chỉ đối chiếu nội dung và hiện diện. Không xác thực thật–giả hay thẩm quyền pháp lý.'}
