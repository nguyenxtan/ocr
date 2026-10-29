"""Async orchestration; subprocess kill on timeout and bounded concurrency."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from app.analysis import Result


async def analyze_isolated(path: Path, max_pages: int, lang: str,
                           timeout_s: int = 90,
                           evidence_dir: Path | None = None) -> Result:
    """Terminate unresponsive parsers; never strand background OCR threads."""
    arguments = [sys.executable, "-m", "app.worker", str(path), str(max_pages), lang]
    if evidence_dir is not None:
        if evidence_dir.resolve() != path.parent.resolve():
            raise ValueError("Evidence directory must be the PDF temporary directory")
        arguments.append(str(evidence_dir))
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        return Result("REVIEW", "PDF xử lý quá thời gian cho phép.")
    except asyncio.CancelledError:
        # /stop must terminate CPU-heavy OCR, not just cancel the chat handler.
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode != 0 or len(stdout) > 32000:
        return Result("REVIEW", "Không xử lý được PDF an toàn.")
    try:
        # A PDF library can emit a warning to stdout before our JSON.
        # Consume only the explicitly framed worker result, not raw stdout.
        lines = stdout.decode("utf-8", errors="replace").splitlines()
        marker = "OCR_RESULT_JSON:"
        raw = next((line[len(marker):] for line in reversed(lines)
                    if line.startswith(marker)), None)
        if raw is None:
            raise ValueError("Missing worker-result marker")
        payload = json.loads(raw)
        if payload.get("status") not in ("PASS", "FAIL", "REVIEW"):
            raise ValueError("Unexpected status")
        return Result(**payload)
    except (ValueError, TypeError):
        return Result("REVIEW", "Dữ liệu xử lý không hợp lệ.")


async def build_evidence_isolated(path: Path, result: Result, timeout_s: int = 15) -> list[str]:
    """Generate optional proof JPEGs in a distinct killable subprocess.

    The main PDF status has already been computed. Failed/slow image generation
    cannot turn a valid result into REVIEW or strand the OCR worker.
    """
    if result.stamp_page is None:
        return []
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.evidence_worker", str(path),
        str(result.stamp_page), result.stamp_fingerprint or "-",
        str(result.signer_page or 0),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout_s)
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        return []
    except asyncio.CancelledError:
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise
    if process.returncode != 0 or len(stdout) > 1024:
        return []
    try:
        lines = stdout.decode("utf-8", errors="replace").splitlines()
        marker = "OCR_EVIDENCE_JSON:"
        raw = next((line[len(marker):] for line in reversed(lines)
                    if line.startswith(marker)), None)
        if raw is None:
            return []
        names = json.loads(raw)
        allowed = {"proof_seal.jpg", "proof_signer.jpg", "proof_header.jpg"}
        if not isinstance(names, list):
            return []
        return [name for name in names if isinstance(name, str) and name in allowed]
    except (ValueError, UnicodeError):
        return []
