"""Regression tests for untrusted PDFs, limits and subprocess timeout."""
import asyncio
import io
from unittest.mock import patch
from pathlib import Path
import pytest
from app.runtime import analyze_isolated
from app.analysis import render_page


class OversizedPage:
    class rect:
        width = 6000
        height = 6000


def test_page_geometry_guard():
    with pytest.raises(ValueError):
        render_page(OversizedPage())


class FakeProcess:
    returncode = 0
    killed = False

    async def communicate(self):
        if not self.killed:
            await asyncio.sleep(1)
        return b'', b''

    def kill(self):
        self.killed = True


async def fake_create(*args, **kwargs):
    assert 'OMP_THREAD_LIMIT' in kwargs['env']
    return FakeProcess()


def test_timeout_kills_worker_and_returns_review(tmp_path):
    path = tmp_path / 'dummy.pdf'
    path.write_bytes(b'%PDF-test')
    with patch('app.runtime.asyncio.create_subprocess_exec', side_effect=fake_create):
        result = asyncio.run(analyze_isolated(path, 2, 'vie+eng', timeout_s=0.01))
    assert result.status == 'REVIEW'
    assert 'thời gian' in result.reason


def test_error_payload_returns_review(tmp_path):
    class BrokenProcess:
        returncode = 0
        async def communicate(self): return b'{this is not JSON', b''
        def kill(self): pass
    async def broken_create(*args, **kwargs): return BrokenProcess()
    with patch('app.runtime.asyncio.create_subprocess_exec', side_effect=broken_create):
        result = asyncio.run(analyze_isolated(tmp_path/'dummy.pdf', 2, 'vie+eng', 1))
    assert result.status == 'REVIEW'
