"""Latency regressions; external Telegram/OCR work is deliberately simulated."""
import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from app import bot, paddle_gateway as gateway
from app.analysis import Result


def setup_bot(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
    monkeypatch.setattr(bot, "active_jobs", {})
    monkeypatch.setattr(bot, "last_seen", {})
    monkeypatch.setattr(bot, "COOLDOWN_SEC", 0)
    monkeypatch.setattr(bot, "semaphore", asyncio.Semaphore(1))
    monkeypatch.setattr(bot, "proof_semaphore", asyncio.Semaphore(1), raising=False)


def request(user_id=7):
    class Remote:
        async def download_to_drive(self, custom_path):
            Path(custom_path).write_bytes(b"%PDF-test")
    document = SimpleNamespace(file_name="test.pdf", file_size=9,
                               get_file=AsyncMock(return_value=Remote()))
    progress = SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock())
    message = SimpleNamespace(document=document, chat_id=user_id,
                              reply_text=AsyncMock(return_value=progress))
    update = SimpleNamespace(effective_message=message,
                             effective_user=SimpleNamespace(id=user_id))
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
    return update, context, progress


def test_verdict_arrives_before_proof_finishes(monkeypatch):
    async def scenario():
        setup_bot(monkeypatch)
        update, context, progress = request()
        proof_started, release = asyncio.Event(), asyncio.Event()
        async def proof(*args):
            proof_started.set()
            await release.wait()
            return []
        monkeypatch.setattr(bot, "analyze_isolated", AsyncMock(return_value=Result(
            "PASS", "Khớp", "NAME_FALLBACK", 1, name_match_pct=100)))
        monkeypatch.setattr(bot, "build_evidence_isolated", proof)
        task = asyncio.create_task(bot.pdf(update, context))
        try:
            await asyncio.wait_for(proof_started.wait(), 2)
            assert any("HỒ SƠ ĐẠT" in call.args[0]
                       for call in progress.edit_text.await_args_list), "Verdict waits for optional photos"
            assert not bot.semaphore.locked(), "Proof must not hold the OCR slot"
        finally:
            release.set()
            await asyncio.wait_for(task, 2)
    asyncio.run(scenario())


def test_photo_failure_cannot_overwrite_completed_verdict(monkeypatch):
    async def scenario():
        setup_bot(monkeypatch)
        update, context, progress = request()
        monkeypatch.setattr(bot, "analyze_isolated", AsyncMock(return_value=Result(
            "PASS", "Khớp", "MST_MATCH", 1, mst_status="MATCH")))
        monkeypatch.setattr(bot, "build_evidence_isolated", AsyncMock(side_effect=OSError("proof failed")))
        await bot.pdf(update, context)
        texts = [call.args[0] for call in progress.edit_text.await_args_list]
        assert texts and all("HỒ SƠ ĐẠT" in text for text in texts), texts
        assert not bot.active_jobs
        assert not bot.semaphore.locked()
    asyncio.run(scenario())


def test_paddle_timeout_is_not_repeated_within_one_pdf(monkeypatch):
    monkeypatch.setenv("PADDLE_ENDPOINT", "http://paddle:8877")
    calls = []
    def offline(*args, **kwargs):
        calls.append(kwargs["timeout"])
        raise TimeoutError("simulated slow sidecar")
    monkeypatch.setattr(gateway, "urlopen", offline)
    image = np.full((20, 20, 3), 255, np.uint8)
    scope = getattr(gateway, "paddle_request_budget", nullcontext)
    with scope():
        for mode in ("general", "seal", "general"):
            with pytest.raises(gateway.PaddleUnavailable):
                gateway.post_image(image, mode)
    assert len(calls) == 1, f"Offline Paddle contacted {len(calls)} times per PDF"
