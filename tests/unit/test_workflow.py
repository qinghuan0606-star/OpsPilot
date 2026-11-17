"""End-to-end graph topology with the offline LLM and mock host fixtures.

These are the regression tests for the three architectural bugs the migration
had to fix: MULTI could not reach tools, tool output could not feed generation,
and the AGENT path produced no citations.
"""

from __future__ import annotations

import pytest

from app.agents.graph import build_graph
from app.agents.state import AgentState
from app.config.settings import clear_settings_cache, get_settings
from app.ops.backend import MockBackend
from app.ops.fixtures import load_fixtures
from app.ops.hosts import HostRegistry
from app.providers.embeddings import HashEmbeddingProvider
from app.providers.fake import OfflineLLMProvider
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.ingest import ingest_to_memory
from app.retrieval.reranker import DocumentReranker
from app.retrieval.vector import VectorRetriever
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.tools.factory import build_tool_registry


def _state(query: str) -> AgentState:
    return {
        "trace_id": "t1",
        "session_id": "s1",
        "user_id": "u1",
        "user_query": query,
        "messages": [],
        "summary": "",
        "retrieved_chunks": [],
        "evidence": [],
        "evidence_sufficient": True,
        "evidence_gaps": [],
        "retrieval_round": 0,
        "retrieval_queries": [],
        "needs_tools": False,
        "host_id": "lab-node-1",
        "plan": None,
        "plan_fingerprint": None,
        "plan_history": [],
        "tool_results": [],
        "tool_trace": [],
        "critic_result": None,
        "critic_round": 0,
        "critic_feedback": [],
        "pending_action": None,
        "confirmed_action": None,
        "confirm_action_id": None,
        "idempotency_key": None,
        "citations": [],
        "refused": False,
        "step_count": 0,
        "token_usage": TokenUsage(),
        "latency": LatencyBreakdown(),
        "extra": {},
    }


@pytest.fixture(scope="module")
def compiled():
    clear_settings_cache()
    settings = get_settings()
    embedder = HashEmbeddingProvider(dim=settings.embedding_dim)
    import asyncio

    bm25, store, chunks = asyncio.run(ingest_to_memory("knowledge", embedder, settings=settings))
    assert chunks
    retriever = HybridRetriever(bm25, VectorRetriever(store, embedder), rrf_k=settings.rrf_k)
    reranker = DocumentReranker(CrossRerank())
    hosts, fixtures = load_fixtures()
    host_registry = HostRegistry(hosts, allowed=["lab-node-1", "lab-node-2"])
    backend = MockBackend(hosts, fixtures)
    registry = build_tool_registry(retriever, backend, host_registry, settings)
    return build_graph(
        llm=OfflineLLMProvider(),
        settings=settings,
        retriever=retriever,
        reranker=reranker,
        registry=registry,
    )


class CrossRerank:
    """Deterministic stand-in for the cross encoder: keep score order."""

    backend = "stub"

    async def rerank(self, query, documents, *, top_n):
        # Provider contract: [(original_index, score)], best first.
        return [(index, 1.0 - index * 0.01) for index in range(min(top_n, len(documents)))]


@pytest.mark.asyncio
async def test_greeting_is_direct_without_retrieval(compiled) -> None:
    result = await compiled.ainvoke(_state("你好"))
    assert result["strategy"].value == "direct"
    assert result["retrieved_chunks"] == []
    assert result["refused"] is False


@pytest.mark.asyncio
async def test_dangerous_command_request_is_refused(compiled) -> None:
    result = await compiled.ainvoke(_state("帮我执行这条命令：把系统根目录整个删掉清理空间"))
    assert result["refused"] is True
    assert result["strategy"].value == "refuse"
    assert result["evidence"] == []


@pytest.mark.asyncio
async def test_multi_fault_diagnosis_escalates_to_tools_and_cites(compiled) -> None:
    result = await compiled.ainvoke(_state("lab-node-1 上 nginx 升级后启动失败，帮我分析一下原因"))
    assert result["strategy"].value in {"multi", "agent"}
    # The MULTI branch had to reach the tool plane: this was impossible before.
    assert result["tool_results"], "MULTI must be able to escalate to ops tools"
    executed = {item.name for item in result["tool_trace"]}
    assert "get_service_status" in executed
    assert "get_rpm_info" in executed
    # Tool results flowed back into evidence and citations.
    assert any(item.kind.value == "tool" for item in result["evidence"])
    assert result["citations"], "AGENT/MULTI path must produce citations"
    assert any(c.kind == "tool" for c in result["citations"])
    # And into the answer itself.
    assert "nginx" in result["final_answer"]


@pytest.mark.asyncio
async def test_agent_question_reaches_service_status(compiled) -> None:
    result = await compiled.ainvoke(_state("帮我查一下 lab-node-2 的 docker 服务状态"))
    assert result["strategy"].value == "agent"
    assert any(item.name == "get_service_status" for item in result["tool_trace"])
    assert "运行中" in result["final_answer"] or "active" in result["final_answer"]


@pytest.mark.asyncio
async def test_single_knowledge_question_stays_in_knowledge(compiled) -> None:
    result = await compiled.ainvoke(_state("rpm -q 和 rpm -V 有什么区别"))
    assert result["strategy"].value == "single"
    assert result["retrieved_chunks"]
    assert result["citations"]
    assert all(c.kind == "knowledge" for c in result["citations"])
    assert (
        all(t.name == "search_knowledge" for t in result["tool_trace"]) or not result["tool_trace"]
    )


@pytest.mark.asyncio
async def test_agent_supervisor_program_uses_both_evidence_kinds(compiled) -> None:
    result = await compiled.ainvoke(
        _state("lab-node-1 上 app-worker 被 Supervisor 反复重启，帮我分析原因。")
    )
    assert result["strategy"].value == "agent"
    assert any(item.kind.value == "knowledge" for item in result["evidence"])
    assert any(item.kind.value == "tool" for item in result["evidence"])
    status = next(item for item in result["tool_trace"] if item.name == "get_service_status")
    assert status.success is True
    assert status.arguments["service"] == "app-worker"
    logs = next(item for item in result["tool_trace"] if item.name == "get_service_logs")
    assert logs.arguments["service"] == "app-worker"
    assert "app-worker" in result["final_answer"]
    assert "Exited too quickly" in result["final_answer"]


@pytest.mark.asyncio
async def test_supervisor_manager_only_asks_for_program_name(compiled) -> None:
    result = await compiled.ainvoke(_state("Supervisor 服务频繁退出，帮我分析原因。"))
    assert result["strategy"].value == "agent"
    assert result["extra"]["missing_target"] is True
    assert result["extra"]["missing_target_kind"] == "service"
    assert result["plan"].steps == []
    assert result["tool_trace"] == []
    assert "托管" in result["final_answer"] and "程序名" in result["final_answer"]


@pytest.mark.asyncio
async def test_rpm_without_package_asks_instead_of_guessing(compiled) -> None:
    result = await compiled.ainvoke(
        _state("服务器安装某个 RPM 软件包时出现依赖冲突，帮我分析原因。")
    )
    assert result["extra"]["missing_target"] is True
    assert result["extra"]["missing_target_kind"] == "package"
    assert result["plan"].steps == []
    assert result["tool_trace"] == []
    assert "软件包名" in result["final_answer"]


@pytest.mark.asyncio
async def test_unknown_package_is_not_treated_as_missing_argument(compiled) -> None:
    result = await compiled.ainvoke(_state("rpm -q redis 依赖冲突，帮我分析原因。"))
    assert result["extra"].get("missing_target") is not True
    rpm_trace = next(item for item in result["tool_trace"] if item.name == "get_rpm_info")
    assert rpm_trace.success is False
    assert rpm_trace.status.value == "fallback"
    assert rpm_trace.executed_tool == "search_knowledge"
    assert "查询到软件包 redis" in result["final_answer"]
    assert "不属于缺少参数" in result["final_answer"]
    assert result["critic_round"] <= 2


@pytest.mark.asyncio
async def test_elk_error_scenario_uses_es_tools_and_not_journal(compiled) -> None:
    result = await compiled.ainvoke(
        _state("lab-node-1 最近应用日志出现大量 ERROR，帮我分析可能原因。")
    )
    executed = {item.name for item in result["tool_trace"]}
    assert {
        "search_elasticsearch_logs",
        "aggregate_error_logs",
        "get_logstash_pipeline_status",
    } <= executed
    assert "get_service_logs" not in executed
    assert "DatabaseConnectionError" in result["final_answer"]
    assert "Logstash" in result["final_answer"]
    es_evidence = [
        item
        for item in result["evidence"]
        if item.reference.startswith(("es:", "es-agg:", "logstash:"))
    ]
    assert es_evidence
    assert any(c.kind == "tool" and c.locator.startswith("es:") for c in result["citations"])


@pytest.mark.asyncio
async def test_supervisor_scenario_includes_program_list_and_config(compiled) -> None:
    result = await compiled.ainvoke(
        _state("lab-node-1 上 app-worker 被 Supervisor 反复重启，帮我分析原因。")
    )
    executed = {item.name for item in result["tool_trace"]}
    assert {"list_supervisor_programs", "get_supervisor_program_config"} <= executed
    assert "autorestart=unexpected" in result["final_answer"]
    assert "Exited too quickly" in result["final_answer"]
    locators = [item.reference for item in result["evidence"] if item.kind.value == "tool"]
    assert any(locator.startswith("supervisorctl:") for locator in locators)
    assert any(locator.startswith("supervisor:") for locator in locators)
    assert not any("systemctl:app-worker" in locator for locator in locators)


@pytest.mark.asyncio
async def test_es_unavailable_does_not_degrade_to_journal(compiled) -> None:
    result = await compiled.ainvoke(
        _state("lab-node-2 的 Elasticsearch 日志出现 ERROR，帮我查一下。")
    )
    executed = {item.name for item in result["tool_trace"]}
    assert "search_elasticsearch_logs" in executed
    assert "get_service_logs" not in executed
    es_trace = next(
        item for item in result["tool_trace"] if item.name == "search_elasticsearch_logs"
    )
    assert es_trace.success is False
    assert str(getattr(es_trace.status, "value", es_trace.status)) == "unavailable"
    assert result["citations"] == [] or all(
        c.locator and not c.locator.startswith("journal:") for c in result["citations"]
    )
