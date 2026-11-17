"""Evidence sufficiency gate.

Deterministic, code-level judgement. The prompt is never asked whether it has
enough evidence, because a prompt can always claim it does. This node derives
what a question *requires* from its own wording, then checks the actual tool
results and evidence list.

Outputs feed three consumers: the graph conditional edge (retrieve again / call
tools), `generate` (honest insufficiency banner) and the API response.
"""

from __future__ import annotations

import re

from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.enums import RetrievalStrategy
from app.schemas.agent import ToolResult

# tool name -> (human label, doc topics used to build the next retrieval query)
TOOL_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "get_system_info": ("系统与内核版本", "操作系统 版本 内核 发行版"),
    "get_cpu_memory": ("CPU 与内存使用情况", "CPU 负载 内存 swap 排查"),
    "get_disk_usage": ("磁盘使用情况", "磁盘空间 inode 排查"),
    "get_service_status": ("服务运行状态", "systemd 服务 状态 failed 排查"),
    "get_service_logs": ("服务日志", "journalctl systemd 日志 启动失败 排查"),
    "get_rpm_info": ("软件包版本信息", "rpm 软件包 版本 升级"),
    "check_rpm_dependencies": ("软件包依赖关系", "rpm 依赖冲突 升级失败 模块 兼容"),
    "list_supervisor_programs": (
        "Supervisor 托管程序清单",
        "supervisor 托管程序 状态 频繁退出",
    ),
    "get_supervisor_program_config": (
        "Supervisor 程序启动与重启配置",
        "supervisor autorestart startsecs startretries 配置",
    ),
    "search_elasticsearch_logs": (
        "Elasticsearch 日志检索结果",
        "elasticsearch kibana 日志 查询 error",
    ),
    "aggregate_error_logs": (
        "ERROR 日志聚合结果",
        "elasticsearch error 聚合 高频异常 统计",
    ),
    "get_logstash_pipeline_status": (
        "Logstash Pipeline 状态",
        "logstash pipeline 采集 处理 队列 故障",
    ),
}

_KNOWLEDGE_GAP = "知识库未检索到可用资料"
_DIAGNOSTIC_CUES = (
    "故障",
    "原因",
    "排查",
    "诊断",
    "失败",
    "异常",
    "冲突",
    "报错",
    "启动失败",
    "起不来",
    "退出",
    "重启",
)


def required_tools(query: str) -> list[str]:
    """Tools whose result a complete answer would need, derived from the question."""
    lowered = query.lower()
    wanted: list[str] = []
    elk = any(
        cue in lowered
        for cue in (
            "elasticsearch",
            "logstash",
            "kibana",
            "elk",
            "es 日志",
            "es日志",
            "应用日志",
            "大量 error",
            "大量error",
            "错误日志",
        )
    )
    supervisor = any(
        cue in lowered for cue in ("supervisor", "supervisord", "app-worker", "托管程序")
    )
    if elk:
        wanted += ["search_elasticsearch_logs", "aggregate_error_logs"]
        if "logstash" in lowered or "pipeline" in lowered:
            wanted.append("get_logstash_pipeline_status")
    if supervisor:
        wanted.append("list_supervisor_programs")
        if any(
            cue in lowered
            for cue in (
                "配置",
                "策略",
                "autorestart",
                "startretries",
                "startsecs",
                "频繁退出",
                "反复重启",
                "频繁重启",
                "自动重启",
            )
        ):
            wanted.append("get_supervisor_program_config")
    if any(cue in lowered for cue in ("依赖", "冲突", "兼容", "dlopen", "模块", "lib")):
        wanted.append("check_rpm_dependencies")
    if any(cue in lowered for cue in ("rpm", "yum", "dnf", "软件包", "包", "升级", "安装")):
        wanted.append("get_rpm_info")
    # Local service state/logs are not required for a pure Elasticsearch query.
    local_service = not elk
    if local_service and (
        any(
            cue in lowered
            for cue in (
                "启动",
                "起不来",
                "失败",
                "状态",
                "systemctl",
                "systemd",
                "supervisor",
                "app-worker",
                "退出",
                "重启",
            )
        )
        or re.search(r"服务(?!器)", lowered)
    ):
        wanted.append("get_service_status")
    if local_service and any(
        cue in lowered
        for cue in (
            "日志",
            "log",
            "journal",
            "报错",
            "error",
            "异常",
            "退出",
            "重启",
            "频繁退出",
            "反复重启",
            "启动失败",
            "起不来",
        )
    ):
        wanted.append("get_service_logs")
    if any(cue in lowered for cue in ("cpu", "内存", "负载", "oom", "swap")):
        wanted.append("get_cpu_memory")
    if any(cue in lowered for cue in ("磁盘", "空间", "inode")):
        wanted.append("get_disk_usage")
    if any(cue in lowered for cue in ("内核", "系统版本", "发行版", "架构")):
        wanted.append("get_system_info")
    return list(dict.fromkeys(wanted))


def needs_knowledge_evidence(
    query: str, strategy: RetrievalStrategy | None, required: list[str]
) -> bool:
    """SINGLE/MULTI always need documents; AGENT diagnostics do too.

    A pure live resource lookup (CPU, disk, version) is served by tools alone.
    """
    if strategy in {RetrievalStrategy.SINGLE, RetrievalStrategy.MULTI}:
        return True
    if strategy == RetrievalStrategy.AGENT and required:
        lowered = query.lower()
        return any(cue in lowered for cue in _DIAGNOSTIC_CUES)
    return False


def evaluate(
    query: str,
    strategy: RetrievalStrategy | None,
    evidence_kinds: list[str],
    tool_results: list[ToolResult],
) -> tuple[bool, list[str]]:
    """Return (sufficient, gaps). Pure function so tests can call it directly."""
    gaps: list[str] = []
    # Tool requirements are derived for every strategy: the planner decides
    # whether to escalate, while sufficiency reports what a complete answer
    # would need if the question is tool-shaped.
    required = required_tools(query)
    for tool_name in required:
        label, _topics = TOOL_REQUIREMENTS[tool_name]
        ok = any(r.name == tool_name and r.success for r in tool_results)
        if ok:
            continue
        failed = next(
            (
                r
                for r in tool_results
                if (r.name == tool_name and not r.success)
                or r.output.get("fallback_from") == tool_name
            ),
            None,
        )
        if failed is not None:
            detail = (
                failed.error or str(failed.output.get("fallback_error") or "") or "未返回有效数据"
            )[:80]
            gaps.append(f"{label}获取失败（{tool_name}：{detail}）")
        else:
            gaps.append(f"未获取{label}（需要 {tool_name}）")
    if needs_knowledge_evidence(query, strategy, required) and "knowledge" not in evidence_kinds:
        gaps.append(_KNOWLEDGE_GAP)
    if strategy == RetrievalStrategy.MULTI and required and "tool" not in evidence_kinds:
        gaps.append("未取得任何工具证据")
    return (not gaps, gaps)


def gap_query(query: str, gaps: list[str]) -> str:
    """Build a second-round retrieval query focused on what is missing."""
    topics: list[str] = []
    for label, topic in ((item[0], item[1]) for item in TOOL_REQUIREMENTS.values()):
        if any(label in gap for gap in gaps):
            topics.append(topic)
    if _KNOWLEDGE_GAP in gaps and not topics:
        topics.append("运维 故障 排查")
    if not topics:
        return ""
    return f"{query} {' '.join(dict.fromkeys(topics))}"[:400]


async def sufficiency_node(state: AgentState, settings: Settings) -> dict:
    """Assess evidence and decide whether another round is worth attempting."""
    strategy = state.get("strategy")
    evidence = state.get("evidence") or []
    gaps_before = state.get("evidence_gaps") or []
    sufficient, gaps = evaluate(
        state["user_query"],
        strategy,
        [item.kind.value for item in evidence],
        state.get("tool_results") or [],
    )
    update: dict = {"evidence_sufficient": sufficient, "evidence_gaps": gaps}
    # An already-exhausted hop budget must not be reset by a new gap list.
    if not sufficient and gaps != gaps_before:
        update["gap_query"] = gap_query(state["user_query"], gaps)
    return update
