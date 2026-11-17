"""Confirmable action storage: one-shot consumption, ownership binding, no silent fallback."""

from __future__ import annotations

import pytest

from app.config.settings import get_settings
from app.core.enums import ToolRisk
from app.core.exceptions import (
    ActionAlreadyConsumedError,
    ConfirmationStoreUnavailableError,
    InvalidRequestError,
)
from app.schemas.chat import ActionProposal
from app.services.pending_store import (
    DisabledPendingStore,
    MemoryPendingStore,
    RedisPendingStore,
    build_pending_store,
)


def _action(action_id: str = "act_1") -> ActionProposal:
    return ActionProposal(
        action_id=action_id,
        tool_name="restart_service",
        arguments={"host_id": "lab-node-1", "service": "nginx"},
        risk=ToolRisk.DESTRUCTIVE,
        summary="确认后将在 lab-node-1 上重启 nginx（mock 后端）",
    )


@pytest.mark.asyncio
async def test_memory_store_is_one_shot() -> None:
    store = MemoryPendingStore(ttl_seconds=900)
    await store.save(_action(), session_id="s1", user_id="u1")
    assert await store.consume("act_1", session_id="s1", user_id="u1") == _action()
    with pytest.raises(ActionAlreadyConsumedError):
        await store.consume("act_1", session_id="s1", user_id="u1")


@pytest.mark.asyncio
async def test_memory_store_binds_user_and_session() -> None:
    store = MemoryPendingStore(ttl_seconds=900)
    await store.save(_action(), session_id="s1", user_id="u1")
    with pytest.raises(InvalidRequestError):
        await store.consume("act_1", session_id="s1", user_id="u2")
    with pytest.raises(InvalidRequestError):
        await store.consume("act_1", session_id="s2", user_id="u1")


@pytest.mark.asyncio
async def test_memory_store_expires() -> None:
    store = MemoryPendingStore(ttl_seconds=0)
    await store.save(_action(), session_id="s1", user_id="u1")
    with pytest.raises(InvalidRequestError):
        await store.consume("act_1", session_id="s1", user_id="u1")


@pytest.mark.asyncio
async def test_disabled_store_refuses_instead_of_degrading_to_dict() -> None:
    store = DisabledPendingStore()
    with pytest.raises(ConfirmationStoreUnavailableError):
        await store.save(_action(), session_id="s1", user_id="u1")
    with pytest.raises(ConfirmationStoreUnavailableError):
        await store.consume("act_1", session_id="s1", user_id="u1")


def test_auto_without_redis_is_disabled_not_memory() -> None:
    settings = get_settings().model_copy(update={"pending_store_backend": "auto"})
    assert isinstance(build_pending_store(settings, redis=None), DisabledPendingStore)


def test_explicit_memory_is_only_for_tests() -> None:
    settings = get_settings().model_copy(update={"pending_store_backend": "memory"})
    assert isinstance(build_pending_store(settings, redis=None), MemoryPendingStore)


def test_redis_backend_selected_when_client_exists() -> None:
    settings = get_settings().model_copy(update={"pending_store_backend": "auto"})
    assert isinstance(build_pending_store(settings, redis=object()), RedisPendingStore)


class _StubRedis:
    """Stands in for the Redis contract so parsing of the Lua return value is tested.

    This does NOT execute the Lua script; the real atomic path needs a live Redis
    (see docs/第二阶段-业务迁移记录.md, "未验证项").
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.used: dict[str, str] = {}
        self.mode = "ok"

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def eval(self, script, numkeys, key1, key2, session_id, user_id, ttl):
        if self.mode == "mismatch":
            return b"__mismatch__"
        value = self.values.pop(key1, None)
        if value is None:
            return None
        self.used[key2] = "1"
        return value

    async def exists(self, key: str) -> bool:
        return key in self.used


@pytest.mark.asyncio
async def test_redis_store_consumes_and_marks_used() -> None:
    redis = _StubRedis()
    store = RedisPendingStore(redis, ttl_seconds=900)
    await store.save(_action(), session_id="s1", user_id="u1")
    consumed = await store.consume("act_1", session_id="s1", user_id="u1")
    assert consumed.tool_name == "restart_service"
    with pytest.raises(ActionAlreadyConsumedError):
        await store.consume("act_1", session_id="s1", user_id="u1")


@pytest.mark.asyncio
async def test_redis_store_rejects_other_owner() -> None:
    redis = _StubRedis()
    redis.mode = "mismatch"
    store = RedisPendingStore(redis, ttl_seconds=900)
    await store.save(_action(), session_id="s1", user_id="u1")
    with pytest.raises(InvalidRequestError):
        await store.consume("act_1", session_id="s1", user_id="u2")
