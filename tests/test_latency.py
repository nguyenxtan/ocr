"""Verdict latency must not depend on optional photo generation."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app import bot
from app.analysis import Result


def prepare(monkeypatch, evidence):
    events = []
    progress = SimpleNamespace(
        edit_text=AsyncMock(side_effect=lambda *a, **kw: events.append(('verdict', a[0]))),
        edit_reply_markup=AsyncMock(side_effect=lambda **kw: events.append(('button', kw))),
    )
    async def download(custom_path):
        Path(custom_path).write_bytes(b'%PDF-fixture')
    doc = SimpleNamespace(file_name='file.pdf',file_size=20,
                          get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=download)))
    msg = SimpleNamespace(chat_id=100, document=doc, reply_text=AsyncMock(return_value=progress))
    update=SimpleNamespace(effective_message=msg,effective_user=SimpleNamespace(id=1))
    context=SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))
    monkeypatch.setattr(bot,'ACCESS_MODE','PUBLIC')
    monkeypatch.setattr(bot,'active_jobs',{})
    monkeypatch.setattr(bot,'last_seen',{})
    monkeypatch.setattr(bot,'semaphore',asyncio.Semaphore(1))
    monkeypatch.setattr(bot,'analyze_isolated',AsyncMock(return_value=Result('PASS','ok','NAME_FALLBACK',1,name_match_pct=100)))
    monkeypatch.setattr(bot,'build_evidence_isolated',evidence)
    return update,context,events,progress


def test_verdict_arrives_while_optional_proofs_are_still_running(monkeypatch):
    async def scenario():
        started,release=asyncio.Event(),asyncio.Event()
        async def slow_proof(*args):
            started.set(); await release.wait(); return []
        update,ctx,events,_=prepare(monkeypatch,slow_proof)
        job=asyncio.create_task(bot.pdf(update,ctx))
        await asyncio.wait_for(started.wait(),2)
        published=any(event[0]=='verdict' and 'HỒ SƠ ĐẠT' in event[1] for event in events)
        release.set(); await asyncio.wait_for(job,2)
        assert published, 'OCR verdict is being held behind evidence rendering'
    asyncio.run(scenario())


def test_proof_failure_cannot_replace_completed_verdict(monkeypatch):
    async def scenario():
        async def broken(*args): raise OSError('proof only')
        update,ctx,events,_=prepare(monkeypatch,broken)
        await bot.pdf(update,ctx)
        assert events and 'HỒ SƠ ĐẠT' in events[0][1]
        assert not any('CẦN KIỂM TRA' in event[1] for event in events if event[0]=='verdict')
    asyncio.run(scenario())


def test_cancel_after_verdict_preserves_result_and_cleans_request(monkeypatch):
    async def scenario():
        started=asyncio.Event()
        async def slow(*args): started.set(); await asyncio.Event().wait()
        update,ctx,events,_=prepare(monkeypatch,slow)
        job=asyncio.create_task(bot.pdf(update,ctx))
        await asyncio.wait_for(started.wait(),2)
        job.cancel(); await asyncio.wait_for(job,2)
        assert any('HỒ SƠ ĐẠT' in e[1] for e in events if e[0]=='verdict')
        assert not any('CẦN KIỂM TRA' in e[1] for e in events if e[0]=='verdict')
        assert not bot.active_jobs and not bot.semaphore.locked()
    asyncio.run(scenario())


def test_button_attached_after_verdict_not_by_resending_result(monkeypatch):
    async def scenario():
        async def proof(pdf,*args):
            (pdf.parent/'proof_seal.jpg').write_bytes(b'jpeg_fixture'); return ['proof_seal.jpg']
        update,ctx,events,progress=prepare(monkeypatch,proof)
        await bot.pdf(update,ctx)
        assert [event[0] for event in events]==['verdict','button']
        assert update.effective_message.reply_text.await_count==1
        assert progress.edit_reply_markup.await_count==1
    asyncio.run(scenario())
