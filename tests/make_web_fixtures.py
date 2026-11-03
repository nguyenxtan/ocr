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
                 'Xac nhan thong tin doanh nghiep dang ky su dung EPORT\n\nDAI DIEN DOANH NGHIEP\nKy va ghi ro ho ten'],
        # Two conflicting labeled IDs: manual correction must pick one source.
        'gpkd-ambiguous': ['GIAY CHUNG NHAN DANG KY DOANH NGHIEP\nMa so doanh nghiep: 0123456789\nTen cong ty viet bang tieng Viet: CONG TY ALPHA\nMa so doanh nghiep: 9876543210'],
    }
    for kind,pages in contents.items():
        with fitz.open() as doc:
            for number,text in enumerate(pages,1):
                p=doc.new_page();p.insert_text((45,65),text,fontsize=11)
                if kind=='gpkd' and number==2:
                    for radius in (50,42):
                        p.draw_circle((450,650),radius,color=(.8,0,0),width=2.5)
                if kind=='eport' and number==2:
                    # Two separate synthetic pen strokes: several suspect signature locations.
                    for x0 in (55,165):
                        p.draw_bezier((x0,140),(x0+20,100),(x0+40,180),(x0+70,130),color=(0,0,.6),width=1.6)
                        p.draw_bezier((x0+5,155),(x0+25,125),(x0+45,170),(x0+65,148),color=(0,0,.6),width=1.6)
            doc.save(directory/(kind+'.pdf'))


if __name__=='__main__':make(sys.argv[1])
