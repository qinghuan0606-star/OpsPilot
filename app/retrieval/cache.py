"""Retrieval cache. Key is query + top_k; ops knowledge is not user-specific.

Tool results are never cached here: they describe live host state, so caching
them would let a stale service status be cited as current evidence.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Protocol

from app.schemas.retrieval import RetrievedChunk


def cache_key(query: str, top_k: int) -> str:
    payload = f"{' '.join(query.split()).lower()}|{top_k}"
    return "ret:" + hashlib.sha256(payload.encode()).hexdigest()[:32]


class RetrievalCache(Protocol):
    async def get(self, query: str, top_k: int) -> list[RetrievedChunk] | None: ...

    async def set(self, query: str, top_k: int, chunks: list[RetrievedChunk]) -> None: ...


class MemoryRetrievalCache:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 256) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._items: dict[str, tuple[float, str]] = {}

    async def get(self, query: str, top_k: int) -> list[RetrievedChunk] | None:
        key = cache_key(query, top_k)
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, payload = item
        if expires_at < time.monotonic():
            self._items.pop(key, None)
            return None
        return [RetrievedChunk.model_validate(chunk) for chunk in json.loads(payload)]

    async def set(self, query: str, top_k: int, chunks: list[RetrievedChunk]) -> None:
        if len(self._items) >= self._max:
            oldest = min(self._items.items(), key=lambda kv: kv[1][0])[0]
            self._items.pop(oldest, None)
        self._items[cache_key(query, top_k)] = (
            time.monotonic() + self._ttl,
            json.dumps([c.model_dump(mode="json") for c in chunks], ensure_ascii=False),
        )


class RedisRetrievalCache:
    def __init__(self, redis, ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, query: str, top_k: int) -> list[RetrievedChunk] | None:
        try:
            raw = await self._redis.get(cache_key(query, top_k))
        except Exception:
            return None
        if not raw:
            return None
        return [RetrievedChunk.model_validate(chunk) for chunk in json.loads(raw)]

    async def set(self, query: str, top_k: int, chunks: list[RetrievedChunk]) -> None:
        payload = json.dumps([c.model_dump(mode="json") for c in chunks], ensure_ascii=False)
        try:
            await self._redis.set(cache_key(query, top_k), payload, ex=self._ttl)
        except Exception:
            return None
