"""Before/after on identical original and simulated photocopy PDFs; metadata only."""
import argparse
import json
from pathlib import Path
import re
from statistics import median
import subprocess
from tempfile import TemporaryDirectory
import time
from types import ModuleType

import fitz
from app.web_extract import extract


def run(baseline_ref, paths, repeats=3):
    if not re.fullmatch(r'[0-9a-f]{40}', baseline_ref):
        raise ValueError('Use a full trusted baseline commit SHA')
    module = ModuleType('baseline_web_extract')
    source = subprocess.check_output(['git','show',baseline_ref+':app/web_extract.py'], text=True)
    exec(compile(source, 'baseline_web_extract.py', 'exec'), module.__dict__)
    measurements = []
    with TemporaryDirectory(prefix='ocr-photocopy-bench-') as temporary:
        for kind, path in zip(('gpkd','eport'), paths):
            gray_path = Path(temporary)/(kind+'.pdf')
            with fitz.open(path) as original, fitz.open() as gray:
                for p in original:
                    pix = p.get_pixmap(matrix=fitz.Matrix(1.5,1.5), colorspace=fitz.csGRAY)
                    page = gray.new_page(width=p.rect.width, height=p.rect.height)
                    page.insert_image(page.rect, stream=pix.tobytes('png'))
                gray.save(gray_path)
            for version, pdf in (('original',path),('grayscale_scan',gray_path)):
                runs = []
                for repeat in range(repeats):
                    readers = [('before', module.extract), ('after', extract)]
                    if repeat%2: readers.reverse()
                    records = {}
                    for stage, reader in readers:
                        start = time.monotonic()
                        result = reader(pdf, kind)
                        records[stage] = (result, round(time.monotonic()-start,3))
                    before, bt = records['before']; after, at = records['after']
                    assert before['detected_kind'] == after['detected_kind'] == kind
                    for key, field in before['fields'].items():
                        if key=='seal' or key.startswith('seal_'): continue
                        assert all(field[p]==after['fields'][key][p] for p in ('raw','value','normalized','regions')), key
                    runs.append({'run':repeat+1, 'before_seconds':bt, 'after_seconds':at,
                        'before_steps':before['timings'], 'after_steps':after['timings'],
                        'before_seal_status':before['fields']['seal']['status'],
                        'after_seal_status':after['fields']['seal']['status'],
                        'before_regions':len(before['fields']['seal']['regions']),
                        'after_regions':len(after['fields']['seal']['regions']),
                        'other_values_and_sources_unchanged':True})
                measurements.append({'input':kind, 'version':version, 'runs':runs,
                    'median_seconds':{stage:median(r[stage+'_seconds'] for r in runs) for stage in ('before','after')}})
    return {'baseline_ref':baseline_ref, 'measurements':measurements}


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--baseline-ref',required=True)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('gpkd',type=Path); p.add_argument('eport',type=Path); a=p.parse_args()
    print(json.dumps(run(a.baseline_ref,[a.gpkd,a.eport],a.repeats),indent=2))
