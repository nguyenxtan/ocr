"""Run an offline, labeled PDF benchmark without uploading sensitive PDFs.

Usage: python -m benchmarks.evaluate --manifest labels.jsonl --base-dir /private/pdfs
Each JSONL: {"file":"a.pdf","status":"PASS","signer_status":"MATCH"}
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import time

from app.analysis import analyze_pdf


def evaluate(manifest: Path, base_dir: Path, max_pages: int = 10) -> dict:
    records = []
    with manifest.open(encoding="utf-8") as stream:
        for index, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            case = json.loads(raw)
            source = (base_dir / case["file"]).resolve()
            if not source.is_relative_to(base_dir.resolve()) or not source.is_file() or source.suffix.lower() != '.pdf':
                raise ValueError(f"Invalid PDF path at line {index}")
            start = time.perf_counter()
            outcome = analyze_pdf(source, max_pages)
            elapsed = round(time.perf_counter() - start, 3)
            records.append({
                "file": case["file"],
                "expected": case["status"],
                "actual": outcome.status,
                "expected_signer": case.get("signer_status"),
                "actual_signer": outcome.signer_status,
                "seconds": elapsed,
            })
    if not records:
        raise ValueError("Empty manifest")
    confusion = Counter(f'{x["expected"]}->{x["actual"]}' for x in records)
    wrong_pass = sum(x["actual"] == "PASS" and x["expected"] != "PASS" for x in records)
    signer = [x for x in records if x["expected_signer"] is not None]
    durations = sorted(x["seconds"] for x in records)
    return {
        "samples": len(records),
        "status_accuracy": round(sum(x["actual"] == x["expected"] for x in records) / len(records), 3),
        "false_pass_count": wrong_pass,
        "signer_accuracy": round(sum(x["actual_signer"] == x["expected_signer"] for x in signer) / len(signer), 3) if signer else None,
        "p50_seconds": statistics.median(durations),
        "p95_seconds": durations[min(len(durations)-1, int(.95*len(durations)))],
        "confusion": dict(sorted(confusion.items())),
        "details": records,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--base-dir", required=True, type=Path)
    p.add_argument("--max-pages", default=10, type=int)
    p.add_argument("--out", type=Path)
    args = p.parse_args()
    result = evaluate(args.manifest, args.base_dir, args.max_pages)
    report = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(report, encoding='utf-8')
    else:
        print(report)


if __name__ == "__main__":
    main()
