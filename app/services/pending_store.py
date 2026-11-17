"""Confirmation storage for side-effect actions.

Design (D6):
- pending actions live in Redis with a 15-minute TTL, bound to user_id and
  session_id, consumed exactly once by a Lua script (check-then-delete atomically);
- after consumption a short-lived `used` marker lets the API answer
  "already consumed" instead of "not found", so a double-click is not treated
  as an expired action;
- if Redis is not available the store refuses to operate. Falling back to a
  process-local dict would silently break the one-shot and multi-worker
  guarantees, so `auto` resolves to `disabled` instead.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Protocol

from app.config.settings import Settings
from app.core.exceptions import (
    ActionAlreadyConsumedError,
    ConfirmationStoreUnavailableError,
    InvalidRequestError,
)
from app.schemas.chat import ActionProposal

_KEY_PREFIX = "ops:pending:"
_USED_PREFIX = "ops:pending:used:"

# KEYS[1]=pending key, KEYS[2]=used marker; ARGV[1]=session_id, ARGV[2]=user_id,
# ARGV[3]=used-marker TTL. Returns nothing when absent, "__mismatch__" when the
# caller does not own the action, else the stored JSON.
_CONSUME_LUA = """
local value = redis.call('GET', KEYS[1])
if not value then
  return nil
end
local data = cjson.decode(value)
if data.session_id ~= ARGV[1] or data.user_id ~= ARGV[2] then
  return "__mismatch__"
end
redis.call('DEL', KEYS[1])
redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[3]))
return value
"""


class PendingActionStore(Protocol):
    """One-shot store for confirmable actions."""

    async def save(self, action: ActionProposal, *, session_id: str, user_id: str) -> None:
        """Persist a freshly proposed action."""
        ...

    async def consume(self, action_id: str, *, session_id: str, user_id: str) -> ActionProposal:
        """Consume the action exactly once, or raise."""
        ...


class RedisPendingStore:
    def __init__(self, redis, ttl_seconds: int = 900) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def save(self, action: ActionProposal, *, session_id: str, user_id: str) -> None:
        payload = json.dumps(
            {
                "session_id": session_id,
                "user_id": user_id,
                "action": action.model_dump(mode="json"),
                "created_at": time.time(),
            },
            ensure_ascii=False,
        )
        try:
            await self._redis.set(_KEY_PREFIX + action.action_id, payload, ex=self._ttl)
        except Exception as exc:  # redis connection / timeout
            raise ConfirmationStoreUnavailableError(
                "确认服务不可用（Redis 写入失败），为避免重复执行已拒绝发起确认。"
            ) from exc

    async def consume(self, action_id: str, *, session_id: str, user_id: str) -> ActionProposal:
        try:
            raw = await self._redis.eval(
                _CONSUME_LUA,
                2,
                _KEY_PREFIX + action_id,
                _USED_PREFIX + action_id,
                session_id,
                user_id,
                self._ttl,
            )
        except Exception as exc:
            raise ConfirmationStoreUnavailableError(
                "确认服务不可用（Redis 读取失败），无法验证待确认操作。"
            ) from exc
        if raw is None:
            used = await self._used_marker(action_id)
            if used:
                raise ActionAlreadyConsumedError("该操作已被确认或已执行，请勿重复提交。")
            raise InvalidRequestError("待确认操作不存在或已过期，请重新发起。")
        if raw == b"__mismatch__" or raw == "__mismatch__":
            raise InvalidRequestError("待确认操作不存在或已过期，请重新发起。")
        data = json.loads(raw)
        return ActionProposal.model_validate(data["action"])

    async def _used_marker(self, action_id: str) -> bool:
        try:
            return bool(await self._redis.exists(_USED_PREFIX + action_id))
        except Exception:
            return False


class MemoryPendingStore:
    """Process-local store, for tests only. Never selected by `auto`."""

    def __init__(self, ttl_seconds: int = 900) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[str, str, ActionProposal, float]] = {}
        self._used: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def save(self, action: ActionProposal, *, session_id: str, user_id: str) -> None:
        async with self._lock:
            self._items[action.action_id] = (
                session_id,
                user_id,
                action,
                time.monotonic() + self._ttl,
            )

    async def consume(self, action_id: str, *, session_id: str, user_id: str) -> ActionProposal:
        async with self._lock:
            now = time.monotonic()
            entry = self._items.pop(action_id, None)
            if entry is None:
                if action_id in self._used:
                    raise ActionAlreadyConsumedError("该操作已被确认或已执行，请勿重复提交。")
                raise InvalidRequestError("待确认操作不存在或已过期，请重新发起。")
            saved_session, saved_user, action, expires_at = entry
            if saved_session != session_id or saved_user != user_id or expires_at < now:
                raise InvalidRequestError("待确认操作不存在或已过期，请重新发起。")
            self._used[action_id] = now + self._ttl
            return action


class DisabledPendingStore:
    """Explicit failure instead of a silent, unsafe dict fallback."""

    async def save(self, action: ActionProposal, *, session_id: str, user_id: str) -> None:
        raise ConfirmationStoreUnavailableError(
            "确认服务不可用（未配置 Redis），需要人工确认的操作暂不可执行。"
            "请设置 PENDING_STORE_BACKEND=redis 并保证 Redis 可用。"
        )

    async def consume(self, action_id: str, *, session_id: str, user_id: str) -> ActionProposal:
        raise ConfirmationStoreUnavailableError(
            "确认服务不可用（未配置 Redis），无法验证待确认操作。"
        )


def build_pending_store(settings: Settings, redis=None) -> PendingActionStore:
    backend = settings.pending_store_backend
    if backend == "memory":
        return MemoryPendingStore(ttl_seconds=settings.pending_action_ttl_seconds)
    if backend == "redis":
        if redis is None:
            return DisabledPendingStore()
        return RedisPendingStore(redis, ttl_seconds=settings.pending_action_ttl_seconds)
    if backend == "disabled":
        return DisabledPendingStore()
    # auto: Redis when actually connected, otherwise refuse to guess.
    if redis is not None:
        return RedisPendingStore(redis, ttl_seconds=settings.pending_action_ttl_seconds)
    return DisabledPendingStore()
