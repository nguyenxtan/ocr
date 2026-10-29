"""In-memory, short-lived, sender-owned Telegram evidence photo cache."""
from __future__ import annotations

from dataclasses import dataclass
import secrets
import time


@dataclass(frozen=True)
class ProofPhoto:
    caption: str
    data: bytes


@dataclass(frozen=True)
class ProofBundle:
    owner_id: int
    chat_id: int
    created_at: float
    photos: tuple[ProofPhoto, ...]

    @property
    def size(self) -> int:
        return sum(len(photo.data) for photo in self.photos)


class ProofCache:
    """Cache only image bytes; do not persist any PDF, image path or document text."""

    def __init__(self, *, ttl_seconds: int = 600,
                 max_items: int = 32, max_bytes: int = 24 * 1024 * 1024):
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.items: dict[str, ProofBundle] = {}

    def prune(self) -> None:
        now = time.monotonic()
        for token, bundle in list(self.items.items()):
            if now - bundle.created_at >= self.ttl_seconds:
                del self.items[token]

    def add(self, owner_id: int, chat_id: int, photos: tuple[ProofPhoto, ...]) -> str | None:
        self.prune()
        if not photos or len(photos) > 3 or any(len(p.data) > 550_000 or not p.data for p in photos):
            return None
        bundle = ProofBundle(owner_id, chat_id, time.monotonic(), photos)
        if bundle.size > self.max_bytes:
            return None
        while self.items and (
            len(self.items) >= self.max_items
            or sum(item.size for item in self.items.values()) + bundle.size > self.max_bytes
        ):
            oldest = min(self.items, key=lambda key: self.items[key].created_at)
            del self.items[oldest]
        token = secrets.token_urlsafe(12)
        while token in self.items:
            token = secrets.token_urlsafe(12)
        self.items[token] = bundle
        return token

    def get(self, token: str, owner_id: int, chat_id: int) -> tuple[ProofPhoto, ...] | None:
        self.prune()
        bundle = self.items.get(token)
        if bundle is None or bundle.owner_id != owner_id or bundle.chat_id != chat_id:
            return None
        return bundle.photos
