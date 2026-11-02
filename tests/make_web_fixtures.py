"""Synthetic, non-customer PDF fixtures for CI browser tests."""
from pathlib import Path
import sys
import fitz


def make(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    contents={
        'gpkd': ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789\nTen cong ty viet bang tieng Viet: CONG TY ALPHA\n4. Thong tin ve chu so huu\nHo va ten: NGUYEN VAN AN',
                 '5. Nguoi dai dien theo phap luat\nHo va ten: TRAN THI BINH'],
        'eport':['BAN DANG KY SU DUNG EPORT\nTHONG TIN DOANH NGHIEP\nTen doanh nghiep: CONG TY ALPHA\nMST doanh nghiep: 0123456789\nGiay DK kinh doanh: 0123456789\nDai dien co tham quyen: TRAN THI BINH',
                 'DAI DIEN DOANH NGHIEP\nKy va ghi ro ho ten'],
    }
    for kind,pages in contents.items():
        with fitz.open() as doc:
            for text in pages:
                p=doc.new_page();p.insert_text((45,65),text,fontsize=11)
            doc.save(directory/(kind+'.pdf'))


if __name__=='__main__':make(sys.argv[1])
