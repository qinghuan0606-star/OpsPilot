"""Evidence sufficiency is deterministic code, not a prompt promise."""

from __future__ import annotations

from app.agents.nodes.sufficiency import evaluate, gap_query, required_tools
from app.core.enums import RetrievalStrategy
from app.schemas.agent import ToolResult


def _ok(name: str, output: dict | None = None) -> ToolResult:
    return ToolResult(name=name, success=True, output=output or {})


def _fail(name: str, error: str = "timeout") -> ToolResult:
    return ToolResult(name=name, success=False, error=error)


def test_service_and_log_questions_require_tools() -> None:
    tools = required_tools("nginx 服务启动失败，看看日志")
    assert "get_service_status" in tools
    assert "get_service_logs" in tools


def test_rpm_upgrade_question_requires_package_evidence() -> None:
    tools = required_tools("升级 rpm 软件包后依赖冲突")
    assert "get_rpm_info" in tools
    assert "check_rpm_dependencies" in tools


def test_gaps_are_named_when_tools_were_never_called() -> None:
    sufficient, gaps = evaluate(
        "nginx 服务启动失败，日志报什么",
        RetrievalStrategy.AGENT,
        ["knowledge"],
        [],
    )
    assert sufficient is False
    assert any("服务运行状态" in gap for gap in gaps)
    assert any("服务日志" in gap for gap in gaps)


def test_successful_tool_results_clear_the_gaps() -> None:
    sufficient, gaps = evaluate(
        "nginx 服务启动失败",
        RetrievalStrategy.AGENT,
        ["knowledge", "tool"],
        [
            _ok("get_service_status", {"state": "failed"}),
            _ok("get_service_logs", {"entries": []}),
        ],
    )
    assert sufficient is True
    assert gaps == []


def test_agent_diagnosis_with_only_tools_still_needs_knowledge() -> None:
    """3.3: AGENT diagnostics retrieve docs before tools; tool-only is not enough."""
    sufficient, gaps = evaluate(
        "nginx 服务启动失败",
        RetrievalStrategy.AGENT,
        ["tool"],
        [_ok("get_service_status", {"state": "failed"})],
    )
    assert sufficient is False
    assert "知识库未检索到可用资料" in gaps


def test_failed_tool_is_reported_as_failure_not_absence() -> None:
    sufficient, gaps = evaluate(
        "nginx 服务启动失败",
        RetrievalStrategy.AGENT,
        ["tool"],
        [_fail("get_service_status", "tool timed out after 8.0s")],
    )
    assert sufficient is False
    assert "获取失败" in gaps[0]
    assert "timed out" in gaps[0]


def test_fallback_counts_as_original_failure() -> None:
    fallback = _ok("search_knowledge", {"fallback_from": "get_service_status", "chunks": []})
    sufficient, gaps = evaluate(
        "nginx 服务状态",
        RetrievalStrategy.SINGLE,
        ["knowledge"],
        [fallback],
    )
    assert sufficient is False
    assert any("服务运行状态获取失败" in gap for gap in gaps)


def test_single_hop_answer_needs_at_least_one_knowledge_item() -> None:
    sufficient, gaps = evaluate("rpm -q 是什么意思", RetrievalStrategy.SINGLE, [], [])
    assert sufficient is False
    assert "知识库未检索到可用资料" in gaps


def test_gap_query_targets_the_missing_evidence() -> None:
    _sufficient, gaps = evaluate("nginx 启动失败", RetrievalStrategy.AGENT, ["tool"], [])
    query = gap_query("nginx 启动失败", gaps)
    assert "nginx 启动失败" in query
    assert "systemd" in query or "日志" in query
