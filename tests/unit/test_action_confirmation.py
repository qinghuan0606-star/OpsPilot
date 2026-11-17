"""restart_service: explicit request -> proposal -> confirmed execution, once only."""

from __future__ import annotations

import pytest

from app.agents.nodes.planner import Planner, planner_node
from app.config.settings import get_settings
from app.core.enums import IntentLabel, ToolRisk
from app.core.exceptions import ActionAlreadyConsumedError, InvalidRequestError
from app.ops.backend import MockBackend
from app.ops.fixtures import load_fixtures
from app.ops.hosts import HostRegistry
from app.providers.embeddings import HashEmbeddingProvider
from app.providers.fake import OfflineLLMProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_to_memory
from app.retrieval.vector import VectorRetriever
from app.schemas.agent import IntentResult
from app.schemas.chat import ActionProposal, ChatRequest, ChatResponse
from app.services.chat_service import ChatService
from app.services.pending_store import MemoryPendingStore
from app.tools.factory import build_tool_registry


async def _planner() -> Planner:
    settings = get_settings().model_copy(
        update={"ops_default_host": "lab-node-1", "ops_enable_write_tools": True}
    )
    embedder = HashEmbeddingProvider(dim=settings.embedding_dim)
    bm25, store, _ = await ingest_to_memory("knowledge", embedder, settings=settings)
    retriever = HybridRetriever(bm25, VectorRetriever(store, embedder), rrf_k=settings.rrf_k)
    hosts, fixtures = load_fixtures()
    registry = build_tool_registry(
        retriever,
        MockBackend(hosts, fixtures),
        HostRegistry(hosts, allowed=["lab-node-1", "lab-node-2"]),
        settings,
    )
    return Planner(OfflineLLMProvider(), registry)


def _intent() -> IntentResult:
    return IntentResult(
        label=IntentLabel.FAULT_DIAGNOSIS, confidence=0.9, rationale="t", prompt_version="v"
    )


@pytest.mark.asyncio
async def test_restart_requires_explicit_request_and_proposes_confirmation() -> None:
    planner = await _planner()
    proposal = await planner_node(
        {
            "user_query": "帮我重启 lab-node-1 上的 nginx",
            "intent": _intent(),
            "host_id": "lab-node-1",
        },
        planner,
    )
    pending: ActionProposal = proposal["pending_action"]
    assert pending.tool_name == "restart_service"
    assert pending.risk == ToolRisk.DESTRUCTIVE
    assert "mock" in pending.summary
    assert pending.arguments["service"] == "nginx"


@pytest.mark.asyncio
async def test_question_about_restart_does_not_propose_action() -> None:
    planner = await _planner()
    question = await planner_node(
        {"user_query": "nginx 服务重启失败一般是什么原因？", "intent": _intent()},
        planner,
    )
    assert question["pending_action"] is None


@pytest.mark.asyncio
async def test_restart_without_target_asks_for_service_name() -> None:
    planner = await _planner()
    result = await planner_node(
        {"user_query": "帮我重启一下这个服务", "intent": _intent()},
        planner,
    )
    assert result["extra"]["missing_target"] is True
    assert result["plan"].steps == []


@pytest.mark.asyncio
async def test_confirmed_action_becomes_a_single_step_plan() -> None:
    planner = await _planner()
    action = ActionProposal(
        action_id="act_1",
        tool_name="restart_service",
        arguments={"host_id": "lab-node-1", "service": "nginx", "reason": "验证修复"},
        risk=ToolRisk.DESTRUCTIVE,
        summary="mock restart",
    )
    confirmed = await planner_node(
        {"user_query": "确认执行", "confirmed_action": action, "intent": _intent()},
        planner,
    )
    assert len(confirmed["plan"].steps) == 1
    assert confirmed["plan"].steps[0].tool_name == "restart_service"


@pytest.mark.asyncio
async def test_pending_action_is_one_shot_per_user_and_session() -> None:
    store = MemoryPendingStore(ttl_seconds=900)
    service = ChatService.__new__(ChatService)
    service._pending_store = store
    action = ActionProposal(
        action_id="act_2",
        tool_name="restart_service",
        arguments={"host_id": "lab-node-1", "service": "nginx", "reason": "验证修复"},
        risk=ToolRisk.DESTRUCTIVE,
        summary="mock restart",
    )
    request = ChatRequest(message="帮我重启 nginx", user_id="u1", session_id="s1")
    response = ChatResponse(answer="请确认", session_id="s1", trace_id="t1", pending_action=action)
    saved = await service._remember_pending(request, response)
    assert saved.pending_action is not None

    ok = ChatRequest(message="确认", user_id="u1", session_id="s1", confirm_action_id="act_2")
    assert await service._resolve_confirmation(ok, "s1") == action
    with pytest.raises(ActionAlreadyConsumedError):
        await service._resolve_confirmation(ok, "s1")

    forged = ok.model_copy(update={"user_id": "u2"})
    store2 = MemoryPendingStore(ttl_seconds=900)
    await store2.save(action, session_id="s1", user_id="u1")
    service._pending_store = store2
    with pytest.raises(InvalidRequestError):
        await service._resolve_confirmation(forged, "s1")


@pytest.mark.asyncio
async def test_confirmation_store_outage_blocks_the_action() -> None:
    from app.services.pending_store import DisabledPendingStore

    service = ChatService.__new__(ChatService)
    service._pending_store = DisabledPendingStore()
    action = ActionProposal(
        action_id="act_3",
        tool_name="restart_service",
        arguments={"service": "nginx", "reason": "x"},
        risk=ToolRisk.DESTRUCTIVE,
        summary="mock restart",
    )
    request = ChatRequest(message="帮我重启 nginx", user_id="u1", session_id="s1")
    response = ChatResponse(answer="请确认", session_id="s1", trace_id="t1", pending_action=action)
    degraded = await service._remember_pending(request, response)
    assert degraded.pending_action is None
    assert degraded.refused is True
    assert degraded.error_code == "CONFIRMATION_STORE_UNAVAILABLE"
