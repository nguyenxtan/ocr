"""Evidence is temporary, sender-only, and bounded in memory."""
from unittest.mock import AsyncMock
from types import SimpleNamespace
import asyncio

from app.proof_cache import ProofCache, ProofPhoto
from app import bot


def photo(size=100):
    return ProofPhoto("Ảnh bằng chứng", b"x" * size)


def test_cache_sender_only():
    cache = ProofCache()
    token = cache.add(100, 777, (photo(),))
    assert token
    assert cache.get(token, 100, 777)
    assert cache.get(token, 101, 777) is None
    assert cache.get(token, 100, 778) is None


def test_cache_expiry(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("app.proof_cache.time.monotonic", lambda: clock[0])
    cache = ProofCache(ttl_seconds=600)
    token = cache.add(1, 1, (photo(),))
    clock[0] = 609.9
    assert cache.get(token, 1, 1)
    clock[0] = 610.1
    assert cache.get(token, 1, 1) is None
    assert len(cache.items) == 0


def test_cache_lru_limit_and_memory_cap():
    cache = ProofCache(max_items=2, max_bytes=250)
    first = cache.add(1, 1, (photo(100),))
    second = cache.add(1, 1, (photo(100),))
    third = cache.add(1, 1, (photo(100),))
    assert first not in cache.items
    assert second in cache.items and third in cache.items
    assert sum(item.size for item in cache.items.values()) <= 250


def test_cache_rejects_invalid_payloads():
    cache = ProofCache()
    assert cache.add(1, 1, ()) is None
    assert cache.add(1, 1, (ProofPhoto("empty", b""),)) is None
    assert cache.add(1, 1, (photo(550_001),)) is None
    assert cache.add(1, 1, (photo(),) * 4) is None


def test_callback_only_sends_to_original_sender(monkeypatch):
    cache = ProofCache()
    token = cache.add(100, 777, (photo(),))
    monkeypatch.setattr(bot, "proof_cache", cache)

    def make_update(user_id):
        answer = AsyncMock()
        query = SimpleNamespace(
            data=f"ev:{token}",
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=answer,
        )
        return SimpleNamespace(callback_query=query,
                               effective_user=SimpleNamespace(id=user_id)), answer

    fake_send = AsyncMock()
    context = SimpleNamespace(bot=SimpleNamespace(send_photo=fake_send))
    outsider, outsider_answer = make_update(222)
    asyncio.run(bot.show_evidence(outsider, context))
    assert outsider_answer.await_count == 1
    assert fake_send.await_count == 0

    user, user_answer = make_update(100)
    asyncio.run(bot.show_evidence(user, context))
    assert user_answer.await_count == 1
    assert fake_send.await_count == 1
    kwargs = fake_send.await_args.kwargs
    assert kwargs["chat_id"] == 777 and kwargs["caption"] == "Ảnh bằng chứng"


def test_expired_callback_shows_alert(monkeypatch):
    cache = ProofCache()
    monkeypatch.setattr(bot, "proof_cache", cache)
    answer = AsyncMock()
    update = SimpleNamespace(
        callback_query=SimpleNamespace(
            data="ev:invalidinvalidab",
            message=SimpleNamespace(chat=SimpleNamespace(id=777)),
            answer=answer,
        ),
        effective_user=SimpleNamespace(id=100),
    )
    fake_send = AsyncMock()
    asyncio.run(bot.show_evidence(
        update, SimpleNamespace(bot=SimpleNamespace(send_photo=fake_send))
    ))
    assert answer.await_args.kwargs.get("show_alert") is True
    assert fake_send.await_count == 0
