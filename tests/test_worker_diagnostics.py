"""Reproduce real CLI-worker behavior and print diagnostics only for a dummy PDF."""
import json
import subprocess
import sys

import fitz

from app.analysis import analyze_pdf


def test_worker_real_dummy_pdf_diagnostics(tmp_path):
    sample = tmp_path / "blank.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(sample)

    direct = analyze_pdf(sample)
    assert direct.status == "FAIL", f"Direct blank-PDF status: {direct.status} {direct.reason}"

    child = subprocess.run(
        [sys.executable, "-m", "app.worker", str(sample), "3", "vie+eng"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert child.returncode == 0, (
        f"Worker failed exit={child.returncode}\n"
        f"stdout={child.stdout[-1200:]}\nstderr={child.stderr[-3000:]}"
    )
    lines = child.stdout.splitlines()
    framed = [line[len("OCR_RESULT_JSON:"):] for line in lines
              if line.startswith("OCR_RESULT_JSON:")]
    assert framed, f"No framed result in {child.stdout[:200]!r}"
    result = json.loads(framed[-1])
    assert result["status"] == "FAIL", result


def test_worker_stdout_noise_does_not_change_verdict(monkeypatch, tmp_path):
    import asyncio
    from app.runtime import analyze_isolated

    class FakeProcess:
        returncode = 0
        async def communicate(self):
            return (b"warning: unrelated PDF library output\\n"
                    b'OCR_RESULT_JSON:{"status":"FAIL","reason":"Khong thay dau"}\\n', b"")
        def kill(self): pass

    async def spawn(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr("app.runtime.asyncio.create_subprocess_exec", spawn)
    result = asyncio.run(analyze_isolated(tmp_path / "not-used.pdf", 2, "vie+eng", 5))
    assert result.status == "FAIL"
    assert "Khong thay dau" in result.reason
