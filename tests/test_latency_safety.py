"""Check the proof lifecycle after a completed, already-delivered verdict."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import bot, worker, paddle_gateway
from app.analysis import Result
from app.proof_cache import ProofCache


def test_cancel_during_photos_keeps_pass(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
        monkeypatch.setattr(bot, "active_jobs", {})
        monkeypatch.setattr(bot, "last_seen", {})
        monkeypatch.setattr(bot, "COOLDOWN_SEC", 0)
        monkeypatch.setattr(bot, "semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(bot, "proof_semaphore", asyncio.Semaphore(1))
        started = asyncio.Event()
        class Remote:
            async def download_to_drive(self, custom_path):
                Path(custom_path).write_bytes(b"%PDF-test")
        async def proof(*args):
            started.set()
            await asyncio.Event().wait()
        progress = SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock())
        document = SimpleNamespace(file_name="test.pdf", file_size=9,
                                   get_file=AsyncMock(return_value=Remote()))
        message = SimpleNamespace(chat_id=1, document=document,
                                  reply_text=AsyncMock(return_value=progress))
        update = SimpleNamespace(effective_user=SimpleNamespace(id=1), effective_message=message)
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        monkeypatch.setattr(bot, "analyze_isolated", AsyncMock(return_value=Result(
            "PASS", "Match", "MST_MATCH", 1, mst_status="MATCH")))
        monkeypatch.setattr(bot, "build_evidence_isolated", proof)
        task = asyncio.create_task(bot.pdf(update, context))
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        await asyncio.wait_for(task, 2)
        assert len(progress.edit_text.await_args_list) == 1
        assert "HỒ SƠ ĐẠT" in progress.edit_text.await_args.args[0]
        assert not bot.active_jobs and not bot.semaphore.locked()
        assert not bot.proof_semaphore.locked()
    asyncio.run(scenario())


def test_button_attached_to_delivered_message_after_real_file(monkeypatch, tmp_path):
    async def scenario():
        monkeypatch.setattr(bot, "proof_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(bot, "proof_cache", ProofCache())
        pdf = tmp_path / "upload.pdf"
        pdf.write_bytes(b"%PDF-test")
        async def proof(*args):
            (tmp_path / "proof_seal.jpg").write_bytes(bytes((255, 216, 255, 217)))
            return ["proof_seal.jpg"]
        monkeypatch.setattr(bot, "build_evidence_isolated", proof)
        delivered = SimpleNamespace(edit_reply_markup=AsyncMock(), edit_text=AsyncMock())
        count = await bot._attach_proof(pdf, Result("PASS", "Match", stamp_page=1), delivered, 1, 1)
        assert count == 1
        delivered.edit_reply_markup.assert_awaited_once()
        delivered.edit_text.assert_not_awaited()
        token = delivered.edit_reply_markup.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data[3:]
        assert bot.proof_cache.get(token, 1, 1)
        assert bot.proof_cache.get(token, 2, 1) is None
    asyncio.run(scenario())


def test_worker_scopes_budget_around_real_analysis_call(monkeypatch, tmp_path, capsys):
    pdf = tmp_path / "fake.pdf"
    pdf.write_bytes(b"%PDF-test")
    def analyze(*args):
        assert paddle_gateway._budget.get() is not None
        return Result("FAIL", "No seal")
    monkeypatch.setattr(worker, "analyze_pdf", analyze)
    monkeypatch.setattr(worker, "restrict_resources", lambda: None)
    monkeypatch.setattr(worker.sys, "argv", ["worker", str(pdf), "2", "vie+eng"])
    worker.main()
    assert paddle_gateway._budget.get() is None
    assert "OCR_RESULT_JSON:" in capsys.readouterr().out
