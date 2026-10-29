"""PUBLIC is opt-in by configuration; PRIVATE stays allowlisted."""
from types import SimpleNamespace
import pytest
from app import bot


def update_with_id(user_id):
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id))


@pytest.mark.parametrize("user_id", [1, 1095120130, 987654321])
def test_public_mode_accepts_any_private_chat_user(monkeypatch, user_id):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
    monkeypatch.setattr(bot, "ALLOWED", set())
    assert bot.is_allowed(update_with_id(user_id))


def test_public_mode_does_not_require_allowlist(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
    monkeypatch.setattr(bot, "ALLOWED", set())
    monkeypatch.setattr(bot, "TOKEN", "fake-testing-token")
    bot.validate_config()


def test_private_mode_requires_matching_id(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PRIVATE")
    monkeypatch.setattr(bot, "ALLOWED", {1095120130})
    assert bot.is_allowed(update_with_id(1095120130))
    assert not bot.is_allowed(update_with_id(987654321))


def test_private_mode_empty_allowlist_denies(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PRIVATE")
    monkeypatch.setattr(bot, "ALLOWED", set())
    assert not bot.is_allowed(update_with_id(1095120130))


def test_missing_telegram_identity_denied(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
    assert not bot.is_allowed(SimpleNamespace(effective_user=None))


def test_unknown_access_mode_rejected(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "OPEN")
    monkeypatch.setattr(bot, "TOKEN", "fake-testing-token")
    with pytest.raises(RuntimeError, match="BOT_ACCESS_MODE"):
        bot.validate_config()


def test_public_mode_cannot_disable_cooldown(monkeypatch):
    monkeypatch.setattr(bot, "ACCESS_MODE", "PUBLIC")
    monkeypatch.setattr(bot, "TOKEN", "fake-testing-token")
    monkeypatch.setattr(bot, "COOLDOWN_SEC", 1)
    with pytest.raises(RuntimeError, match="USER_COOLDOWN_SEC"):
        bot.validate_config()
