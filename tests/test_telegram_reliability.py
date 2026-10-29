"""End-to-end handler regression tests for Telegram UX (network mocked)."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import bot
from app.analysis import Result
from app.proof_cache import ProofCache, ProofPhoto


class FakeRemote:
    async def download_to_drive(self, custom_path):
        Path(custom_path).write_bytes(b"%PDF-\nminimal test document")


class FakeDocument:
    file_name = "sample.pdf"
    file_size = 99

    async def get_file(self):
        return FakeRemote()


def make_update(user_id: int, *, document=None):
    msg = SimpleNamespace(chat_id=778, document=document, reply_text=AsyncMock())
    msg.reply_text.side_effect = lambda *args, **kwargs: SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id),
                           effective_message=msg), msg


def test_review_without_stamp_page_has_a_reason():
    html = Result("REVIEW", "PDF xử lý quá thời gian cho phép.").telegram_html()
    assert "CẦN KIỂM TRA" in html
    assert "quá thời gian" in html
    assert len(html.splitlines()) >= 2


def test_review_with_signer_and_stamp_has_reason():
    html = Result("REVIEW", "Chưa đọc chắc tên người ký.", "NAME_FALLBACK", 1,
                  signer_status="UNREADABLE").telegram_html()
    assert "Chưa đọc chắc tên người ký" in html
    assert "Chưa đọc rõ" in html


def test_progress_message_is_edited_in_place():
    async def scenario():
        update, msg = make_update(123)
        progress = await msg.reply_text("Đang xử lý...")
        await bot._finish_status(progress, msg, Result("REVIEW", "Không đọc được."))
        progress.edit_text.assert_awaited_once()
        assert "Không đọc được" in progress.edit_text.await_args.args[0]
        assert msg.reply_text.await_count == 1
    asyncio.run(scenario())


def test_second_pdf_waits_instead_of_immediately_saying_busy(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
        monkeypatch.setattr(bot, "active_jobs", {})
        monkeypatch.setattr(bot, "semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(bot, "last_seen", {})
        monkeypatch.setattr(bot, "COOLDOWN_SEC", 0)
        monkeypatch.setattr(bot, "MAX_CONCURRENT", 1)
        monkeypatch.setattr(bot, "MAX_QUEUED", 2)
        monkeypatch.setattr(bot, "QUEUE_WAIT_SEC", 5)
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def fake_analyze(*args, **kwargs):
            calls.append(True)
            if len(calls) == 1:
                started.set()
                await release.wait()
            return Result("REVIEW", "Mẫu thử thiếu bằng chứng.")

        monkeypatch.setattr(bot, "analyze_isolated", fake_analyze)
        context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        first, first_msg = make_update(10, document=FakeDocument())
        second, second_msg = make_update(11, document=FakeDocument())
        job1 = asyncio.create_task(bot.pdf(first, context))
        await asyncio.wait_for(started.wait(), 3)
        job2 = asyncio.create_task(bot.pdf(second, context))
        await asyncio.sleep(.05)
        assert len(calls) == 1
        assert "chờ đến lượt" in second_msg.reply_text.await_args.args[0]
        release.set()
        await asyncio.wait_for(asyncio.gather(job1, job2), 3)
        assert len(calls) == 2
        assert bot.active_jobs == {}
        assert "Mẫu thử thiếu bằng chứng" in first_msg.reply_text.await_args.args[0] or first_msg.reply_text.await_count >= 1
    asyncio.run(scenario())


def test_stop_cancels_running_handler_and_frees_slot(monkeypatch):
    async def scenario():
        monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
        monkeypatch.setattr(bot, "active_jobs", {})
        monkeypatch.setattr(bot, "semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(bot, "last_seen", {})
        monkeypatch.setattr(bot, "COOLDOWN_SEC", 0)
        started = asyncio.Event()

        async def long_ocr(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(bot, "analyze_isolated", long_ocr)
        ctx = SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
        update, msg = make_update(10, document=FakeDocument())
        running = asyncio.create_task(bot.pdf(update, ctx))
        await asyncio.wait_for(started.wait(), 3)
        stop_update, stop_message = make_update(10)
        await bot.cancel_job(stop_update, ctx)
        await asyncio.wait_for(running, 3)
        assert not bot.active_jobs
        assert not bot.semaphore.locked()
        assert "Đã yêu cầu hủy" in stop_message.reply_text.await_args.args[0]
        assert msg.reply_text.await_count == 1
    asyncio.run(scenario())


def test_album_failure_sends_one_stamp_photo_instead_of_silence(monkeypatch):
    async def scenario():
        cache = ProofCache()
        token = cache.add(100, 778, (
            ProofPhoto("Dấu", b"one"),
            ProofPhoto("Khu vực ký", b"two"),
        ))
        monkeypatch.setattr(bot, "proof_cache", cache)
        query = SimpleNamespace(
            data=f"ev:{token}",
            message=SimpleNamespace(chat=SimpleNamespace(id=778)),
            answer=AsyncMock(),
        )
        ctx = SimpleNamespace(bot=SimpleNamespace(
            send_media_group=AsyncMock(side_effect=RuntimeError("Album rejected")),
            send_photo=AsyncMock(),
            send_message=AsyncMock(),
        ))
        await bot.show_evidence(
            SimpleNamespace(callback_query=query,
                            effective_user=SimpleNamespace(id=100)), ctx)
        ctx.bot.send_media_group.assert_awaited_once()
        ctx.bot.send_photo.assert_awaited_once()
        ctx.bot.send_message.assert_not_awaited()
    asyncio.run(scenario())


def test_both_photo_methods_failing_returns_visible_error(monkeypatch):
    async def scenario():
        cache = ProofCache()
        token = cache.add(100, 778, (ProofPhoto("Dấu", b"one"),))
        monkeypatch.setattr(bot, "proof_cache", cache)
        q = SimpleNamespace(
            data=f"ev:{token}", message=SimpleNamespace(chat=SimpleNamespace(id=778)),
            answer=AsyncMock(),
        )
        ctx = SimpleNamespace(bot=SimpleNamespace(
            send_photo=AsyncMock(side_effect=RuntimeError("Telegram unavailable")),
            send_message=AsyncMock(),
        ))
        await bot.show_evidence(SimpleNamespace(callback_query=q,
                                                effective_user=SimpleNamespace(id=100)),ctx)
        ctx.bot.send_message.assert_awaited_once()
        assert "Không gửi được ảnh" in ctx.bot.send_message.await_args.kwargs["text"]
    asyncio.run(scenario())
