"""Smoke test the actual subprocess worker, not just mocks."""
import asyncio
from unittest.mock import patch
import resource

import fitz

from app.runtime import analyze_isolated
from app.worker import restrict_resources


def test_worker_does_not_apply_virtual_memory_limit():
    # OpenCV reserves enormous address space despite low resident RAM usage.
    with patch('resource.setrlimit') as setrlimit:
        restrict_resources()
    assert all(c.args[0] != resource.RLIMIT_AS for c in setrlimit.call_args_list)


def test_real_isolated_worker_accepts_small_pdf(tmp_path):
    filename=tmp_path/'blank.pdf'
    with fitz.open() as document:
        document.new_page()
        document.save(filename)
    outcome=asyncio.run(analyze_isolated(filename,3,'vie+eng',15))
    assert outcome.status=='FAIL'
    assert 'dấu' in outcome.reason
