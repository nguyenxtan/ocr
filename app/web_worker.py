"""Private subprocess protocol. JSON goes to private files, never stdout/logs."""
import json
import sys
from pathlib import Path
import fitz
from app.worker import restrict_resources


def main():
    restrict_resources()
    mode,path,output,*args=sys.argv[1:]
    path,output=Path(path),Path(output)
    try:
        if mode=='validate':
            with fitz.open(path) as doc:
                if not doc.is_pdf or doc.needs_pass or not 1<=len(doc)<=int(args[0]):
                    raise ValueError('PDF không hợp lệ, có mật khẩu hoặc số trang vượt giới hạn.')
                for p in doc:
                    if p.rect.width<=0 or p.rect.height<=0 or p.rect.width*p.rect.height>24_000_000:
                        raise ValueError('Kích thước trang PDF vượt giới hạn.')
            result={'ok':True}
        elif mode=='extract':
            from app.web_extract import extract
            result=extract(path,args[0],args[1])
        elif mode=='page':
            from app.analysis import render_page
            from PIL import Image
            with fitz.open(path) as doc:
                page=doc[int(args[0])-1]
                Image.fromarray(render_page(page)).save(output,'PNG')
            return
        else:
            raise ValueError('Tác vụ không hợp lệ.')
        output.write_text(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        message=str(exc) if isinstance(exc,ValueError) else 'Không xử lý được PDF hoặc OCR. Vui lòng kiểm tra lại tệp.'
        output.write_text(json.dumps({'error':message},ensure_ascii=False))
        sys.exit(1)


if __name__=='__main__': main()
