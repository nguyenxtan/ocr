"""Inspect embedded PDF signatures without confusing their appearance with ink seals.

pdfsig (Poppler) performs signature integrity checks. Trust-chain and revocation
verification are kept separate. Never call a scanned image a digital signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


@dataclass(frozen=True)
class DigitalSignatureCheck:
    status: str  # NONE | VALID_CRYPTO | INVALID | UNVERIFIED | ERROR
    count: int = 0
    trusted: bool | None = None
    signer: str | None = None
    reason: str | None = None


def parse_pdfsig(output: str) -> DigitalSignatureCheck:
    if "does not contain any signatures" in output:
        return DigitalSignatureCheck("NONE")
    signatures = list(re.finditer(r"(?m)^Signature #\d+:\s*$", output))
    if not signatures:
        return DigitalSignatureCheck("UNVERIFIED", reason="Không có bằng chứng chữ ký số đủ rõ")
    validations = re.findall(r"(?m)^\s*- Signature Validation:\s*(.*?)\s*$", output)
    certs = re.findall(r"(?m)^\s*- Certificate Validation:\s*(.*?)\s*$", output)
    names = re.findall(r"(?m)^\s*- Signer Certificate Common Name:\s*(.*?)\s*$", output)
    if len(validations) != len(signatures):
        return DigitalSignatureCheck("UNVERIFIED", len(signatures), signer=names[0] if names else None)
    # Do not declare success if *any* embedded signature is invalid.
    invalid = any("invalid" in value.lower() for value in validations)
    good = (all("signature is valid" in value.lower() for value in validations)
            and "Total document signed" in output)
    trusted = None
    if certs:
        if any("isn't trusted" in x.lower() or "is not trusted" in x.lower() for x in certs):
            trusted = False
        elif all("trusted" in x.lower() and "not" not in x.lower() for x in certs):
            trusted = True
    status = "INVALID" if invalid else "VALID_CRYPTO" if good else "UNVERIFIED"
    return DigitalSignatureCheck(status, len(signatures), trusted, names[0] if names else None)


def inspect_digital_signatures(path: str | Path, timeout_s: int = 10) -> DigitalSignatureCheck:
    try:
        completed = subprocess.run(["pdfsig", str(path)], capture_output=True,
                                   text=True, errors="replace", timeout=timeout_s, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return DigitalSignatureCheck("ERROR", reason="Không chạy được bộ kiểm tra chữ ký số")
    if completed.returncode not in (0, 1) and not completed.stdout.strip():
        return DigitalSignatureCheck("ERROR", reason="Không kiểm tra được cấu trúc chữ ký số")
    return parse_pdfsig(completed.stdout)
