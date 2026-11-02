"""Same-input old Telegram/new web measurements. Outputs metadata only.

Usage: python -m benchmarks.web_compare /private/gpkd.pdf /private/eport.pdf
The old verdict examines a seal on ONE PDF; the new verdict compares a PAIR.
These are different contracts; timing differences are not an accuracy score.
"""
import argparse
import asyncio
import json
from pathlib import Path
import tempfile
import time
from app.runtime import analyze_isolated
from app.web_jobs import Store
from app.web_compare import compare


async def run(paths,repeats):
    measurements=[]
    documents={}
    with tempfile.TemporaryDirectory(prefix='ocr-benchmark-') as tmp:
        store=Store(Path(tmp),timeout=180)
        try:
            for run_number in range(1,repeats+1):
                for kind,path in zip(('gpkd','eport'),paths):
                    start=time.monotonic()
                    old=await analyze_isolated(path,20,'vie+eng',180)
                    old_elapsed=round(time.monotonic()-start,3)
                    start=time.monotonic()
                    new=await store.command('extract',path,Path(tmp)/f'{kind}.json',kind,'vie+eng')
                    new_elapsed=round(time.monotonic()-start,3); documents[kind]=new
                    measurements.append({'run':run_number,'input':kind,'old_seconds':old_elapsed,'old_single_pdf_status':old.status,
                        'new_seconds':new_elapsed,'new_steps':new['timings'],'new_classification':new['detected_kind'],
                        'pages':len(new['pages']),'methods':[p['method'] for p in new['pages']],
                        'field_statuses':{k:v['status'] for k,v in new['fields'].items()}})
        finally: await store.close()
    result=compare(documents)
    return {'measurements':measurements,'new_pair_conclusion':result['conclusion'],
            'new_checks':{r['id']:r['status'] for r in result['rows']},
            'note':'Old: single-PDF seal checks. New: GPKD–EPORT pair and source fields. Not equivalent verdict contracts. No auxiliary images in either timing.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('gpkd',type=Path);parser.add_argument('eport',type=Path);parser.add_argument('--repeats',type=int,default=2)
    args=parser.parse_args();print(json.dumps(asyncio.run(run([args.gpkd,args.eport],args.repeats)),indent=2))
