"""Compare web extraction on identical PDFs; emit metadata only, never values.

The baseline is trusted repository code at an explicit commit. Order alternates
between revisions. Sources and original values must stay identical.
"""
import argparse
import json
from pathlib import Path
import re
from statistics import median
import subprocess
import time
from types import ModuleType
from app.web_extract import extract


def run(baseline_ref,paths,repeats=3):
    if not re.fullmatch(r'[0-9a-f]{40}',baseline_ref):raise ValueError('Use a full baseline commit SHA')
    source=subprocess.check_output(['git','show',baseline_ref+':app/web_extract.py'],text=True)
    module=ModuleType('baseline_web_extract')
    exec(compile(source,'baseline_web_extract.py','exec'),module.__dict__)
    measurements=[]
    for repeat in range(repeats):
        for kind,path in zip(('gpkd','eport'),paths):
            records={}
            order=[('before',module.extract),('after',extract)]
            if repeat%2:order.reverse()
            for name,reader in order:
                start=time.monotonic();d=reader(path,kind)
                records[name]=(d,round(time.monotonic()-start,3))
            before,bt=records['before'];after,at=records['after']
            changed={}
            if before['detected_kind']!=after['detected_kind']:raise AssertionError('classification changed')
            for key,f in before['fields'].items():
                new=after['fields'][key]
                if any(new[p]!=f[p] for p in ('raw','value','normalized','regions')):raise AssertionError('field/source changed: '+key)
                if f['status']!=new['status']:changed[key]={'before':f['status'],'after':new['status']}
            measurements.append({'run':repeat+1,'input':kind,'before_seconds':bt,'after_seconds':at,
                'before_steps':before['timings'],'after_steps':after['timings'],
                'status_changes':changed,'unchanged_values_and_sources':True,'recheck':after['ocr_recheck']})
    return {'baseline_ref':baseline_ref,'runs':measurements,'median_seconds':{kind:{
        stage:median(m[stage+'_seconds'] for m in measurements if m['input']==kind)
        for stage in ('before','after')} for kind in ('gpkd','eport')}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline-ref',required=True);p.add_argument('--repeats',type=int,default=3)
    p.add_argument('gpkd',type=Path);p.add_argument('eport',type=Path);a=p.parse_args()
    print(json.dumps(run(a.baseline_ref,[a.gpkd,a.eport],a.repeats),indent=2))
