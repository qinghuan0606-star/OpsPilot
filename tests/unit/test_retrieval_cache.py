"""Short-TTL retrieval cache: key stability, expiry and Redis degrade paths."""

from __future__ import annotations

import pytest

from app.retrieval.cache import MemoryRetrievalCache, RedisRetrievalCache, cache_key
from app.schemas.retrieval import RetrievedChunk


def _chunk(chunk_id: str = "c1") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc1",
        title="RPM 依赖",
        content="nothing provides libGeoIP.so.1",
        score=0.8,
        rank=1,
    )


def test_cache_key_is_stable_and_prefixed() -> None:
    assert cache_key("nginx 启动失败", 4) == cache_key("nginx 启动失败", 4)
    assert cache_key("nginx 启动失败", 4) != cache_key("nginx 启动失败", 5)
    assert cache_key("nginx 启动失败", 4).startswith("ret:")


def test_cache_key_is_case_and_space_insensitive() -> None:
    assert cache_key(" Nginx  Upgrade ", 4) == cache_key("nginx upgrade", 4)


@pytest.mark.asyncio
async def test_memory_cache_roundtrip() -> None:
    cache = MemoryRetrievalCache(ttl_seconds=300)
    assert await cache.get("nginx 启动失败", 4) is None
    await cache.set("nginx 启动失败", 4, [_chunk()])
    hits = await cache.get("nginx 启动失败", 4)
    assert hits and hits[0].chunk_id == "c1"


@pytest.mark.asyncio
async def test_memory_cache_expires(monkeypatch) -> None:
    cache = MemoryRetrievalCache(ttl_seconds=1)
    await cache.set("q", 2, [_chunk()])
    monkeypatch.setattr("app.retrieval.cache.time.monotonic", lambda: 10_000.0)
    assert await cache.get("q", 2) is None


class _BrokenRedis:
    async def get(self, key):
        raise RuntimeError("redis down")

    async def set(self, *args, **kwargs):
        raise RuntimeError("redis down")


class _EchoRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


@pytest.mark.asyncio
async def test_redis_cache_roundtrip() -> None:
    cache = RedisRetrievalCache(_EchoRedis(), ttl_seconds=300)
    await cache.set("q", 3, [_chunk()])
    hits = await cache.get("q", 3)
    assert hits and hits[0].content.startswith("nothing provides")


@pytest.mark.asyncio
async def test_redis_cache_degrades_instead_of_raising() -> None:
    cache = RedisRetrievalCache(_BrokenRedis(), ttl_seconds=300)
    assert await cache.get("q", 3) is None
    await cache.set("q", 3, [_chunk()])  # must not raise
