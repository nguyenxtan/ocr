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
    result = json.loads(child.stdout)
    assert result["status"] == "FAIL", result
