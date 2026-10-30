"""Controlled handler latency experiment, NOT a production OCR benchmark.

Uses real old/new pdf() handler code. Telegram, 50ms OCR and 250ms proof work
are simulated identically. No credentials, customer documents or inference.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import re
from statistics import median
import subprocess
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from app import bot
from app.analysis import Result


async def measure(module):
    times = []
    for _ in range(3):
        delivered = []
        started = time.monotonic()
        async def edit(text, **kwargs):
            if "HỒ SƠ ĐẠT" in text:
                delivered.append(time.monotonic() - started)
        progress = SimpleNamespace(edit_text=edit, edit_reply_markup=AsyncMock())
        class Remote:
            async def download_to_drive(self, custom_path):
                Path(custom_path).write_bytes(b"%PDF-synthetic")
        async def ocr(*args, **kwargs):
            await asyncio.sleep(.05)
            return Result("PASS", "Synthetic match", "NAME_FALLBACK", 1)
        async def proof(*args, **kwargs):
            await asyncio.sleep(.25)
            return []
        document = SimpleNamespace(file_name="synthetic.pdf", file_size=14,
                                   get_file=AsyncMock(return_value=Remote()))
        message = SimpleNamespace(document=document, chat_id=1,
                                  reply_text=AsyncMock(return_value=progress))
        update = SimpleNamespace(effective_message=message,
                                  effective_user=SimpleNamespace(id=1))
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        changes = dict(ACCESS_MODE="PUBLIC", active_jobs={}, last_seen={},
                       COOLDOWN_SEC=0, semaphore=asyncio.Semaphore(1),
                       analyze_isolated=ocr, build_evidence_isolated=proof)
        with ExitStack() as stack:
            for name, value in changes.items():
                stack.enter_context(patch.object(module, name, value))
            stack.enter_context(patch.object(module, "proof_semaphore", asyncio.Semaphore(1), create=True))
            await module.pdf(update, context)
        if len(delivered) != 1:
            raise RuntimeError("Expected exactly one completed verdict")
        times.append(delivered[0])
    return round(median(times), 4)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.baseline_ref):
        raise SystemExit("baseline must be a full commit SHA")
    source = subprocess.check_output(
        ["git", "show", f"{args.baseline_ref}:app/bot.py"], text=True)
    baseline = ModuleType("baseline_bot")
    exec(compile(source, "baseline_bot.py", "exec"), baseline.__dict__)
    before = asyncio.run(measure(baseline))
    after = asyncio.run(measure(bot))
    report = {
        "measurement": "simulated Telegram/OCR; actual old/new handler ordering",
        "ocr_delay_s": .05, "proof_delay_s": .25, "runs_per_revision": 3,
        "before_first_verdict_median_s": before,
        "after_first_verdict_median_s": after,
        "not_a_live_server_or_model_benchmark": True,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
