"""Isolated local subprocess for CPU-heavy PDF/OCR work.

A Telegram user controls PDF bytes, so timeout the process rather than merely
cancelling a thread. Stdout carries only an explicitly framed result object.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from app.analysis import analyze_pdf
from app.paddle_gateway import paddle_request_budget


def restrict_resources() -> None:
    if sys.platform != "linux":
        return
    import resource
    # OpenCV reserves large virtual ranges; Compose limits actual RAM instead.
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    max_cpu = int(os.getenv("WORKER_CPU_SECONDS", "90"))
    resource.setrlimit(resource.RLIMIT_CPU, (max_cpu, max_cpu + 5))


def main() -> None:
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    restrict_resources()
    if len(sys.argv) not in (4, 5):
        raise SystemExit(2)
    path = Path(sys.argv[1])
    pages = int(sys.argv[2])
    languages = sys.argv[3]
    with paddle_request_budget():
        result = analyze_pdf(path, pages, languages)
    if len(sys.argv) == 5:
        target = Path(sys.argv[4])
        if target.resolve() != path.parent.resolve() or not target.is_dir():
            raise SystemExit(2)
        try:
            from app.evidence import build_evidence
            build_evidence(path, result, target)
        except Exception as error:
            sys.stderr.write(f"Optional evidence failed: {type(error).__name__}\n")
    sys.stdout.write("\nOCR_RESULT_JSON:" + json.dumps(asdict(result), ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
