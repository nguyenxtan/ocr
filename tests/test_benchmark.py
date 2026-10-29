from pathlib import Path
import json
import pytest
from unittest.mock import patch
from app.analysis import Result
from benchmarks.evaluate import evaluate


def test_benchmark_matrix_detects_false_positive(tmp_path):
    folder = tmp_path / 'data'
    folder.mkdir()
    for name in ['a.pdf', 'b.pdf', 'c.pdf']:
        (folder / name).write_bytes(b'%PDF-')
    manifest = tmp_path / 'labels.jsonl'
    manifest.write_text('\n'.join([
        json.dumps({'file':'a.pdf','status':'PASS','signer_status':'MATCH'}),
        json.dumps({'file':'b.pdf','status':'FAIL'}),
        json.dumps({'file':'c.pdf','status':'REVIEW'}),
    ]), encoding='utf-8')
    responses = [Result('PASS','ok',signer_status='MATCH'),Result('PASS','wrong'),Result('REVIEW','uncertain')]
    with patch('benchmarks.evaluate.analyze_pdf', side_effect=responses):
        report=evaluate(manifest,folder)
    assert report['false_pass_count']==1
    assert report['samples']==3
    assert report['status_accuracy']==pytest.approx(2/3,abs=.001)
    assert report['signer_accuracy']==1


def test_benchmark_rejects_traversal(tmp_path):
    manifest=tmp_path/'list.jsonl'
    manifest.write_text('{"file":"../secrets.pdf","status":"PASS"}\n')
    with pytest.raises(ValueError):
        evaluate(manifest,tmp_path)
