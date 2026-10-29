"""Best-effort isolated proof-image subprocess, independent of OCR decision."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from app.analysis import Result
from app.evidence import build_evidence
from app.worker import restrict_resources


def main() -> None:
    restrict_resources()
    if len(sys.argv) != 5:
        raise SystemExit(2)
    pdf = Path(sys.argv[1])
    stamp_page = int(sys.argv[2])
    fingerprint = None if sys.argv[3] == "-" else sys.argv[3]
    signer_page = int(sys.argv[4]) or None
    result = Result("REVIEW", "Bằng chứng ảnh", stamp_page=stamp_page,
                    stamp_fingerprint=fingerprint, signer_page=signer_page)
    filenames = build_evidence(pdf, result, pdf.parent)
    # Only predefined filenames, never raw image contents or OCR/PDF text.
    sys.stdout.write(json.dumps(filenames))


if __name__ == "__main__":
    main()
