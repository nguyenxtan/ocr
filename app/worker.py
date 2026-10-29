"""Isolated local subprocess for CPU-heavy PDF/OCR work.

A Telegram user controls PDF bytes, so timeout the *process* rather than merely
cancelling an asyncio thread. The worker prints only one compact JSON object.
"""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from app.analysis import analyze_pdf


def restrict_resources() -> None:
    if sys.platform != "linux":
        return
    import resource
    # RLIMIT_AS is not a safe bound for OpenCV: shared libraries reserve large
    # virtual ranges while using little RAM, triggering false out-of-memory.
    # The Docker cgroup in compose.yaml limits actual RAM to 2 GiB.
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
    result = analyze_pdf(path, pages, languages)
    if len(sys.argv) == 5:
        # Only temporary output next to the input PDF is permitted.
        target = Path(sys.argv[4])
        if target.resolve() != path.parent.resolve() or not target.is_dir():
            raise SystemExit(2)
        try:
            from app.evidence import build_evidence
            build_evidence(path, result, target)
        except Exception as error:
            # Photo generation is best effort: never change the OCR decision.
            sys.stderr.write(f"Optional evidence failed: {type(error).__name__}\n")
    sys.stdout.write("\\nOCR_RESULT_JSON:" + json.dumps(asdict(result), ensure_ascii=False) + "\\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
