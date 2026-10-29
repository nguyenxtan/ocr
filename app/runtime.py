"""Async orchestration; subprocess kill on timeout and bounded concurrency."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys

from app.analysis import Result


async def analyze_isolated(path: Path, max_pages: int, lang: str,
                           timeout_s: int = 90) -> Result:
    """Terminate unresponsive parsers; never strand background OCR threads."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.worker", str(path), str(max_pages), lang,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "OMP_THREAD_LIMIT": "1"},
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        return Result("REVIEW", "PDF xử lý quá thời gian cho phép.")
    if process.returncode != 0 or len(stdout) > 32000:
        return Result("REVIEW", "Không xử lý được PDF an toàn.")
    try:
        payload = json.loads(stdout.decode("utf-8"))
        if payload.get("status") not in ("PASS", "FAIL", "REVIEW"):
            raise ValueError("Unexpected status")
        return Result(**payload)
    except (ValueError, TypeError):
        return Result("REVIEW", "Dữ liệu xử lý không hợp lệ.")
