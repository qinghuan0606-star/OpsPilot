"""Pre-answer diagnosis critic.

Deterministic checks only, before the answer is generated:
- the plan actually covers the tools the question requires;
- required tools produced evidence (fallback is not tool evidence);
- the diagnostic path has both knowledge and tool evidence;
- no structured contradictions between tool outputs;
- no missing service/package target and no repeated plan.

This is deliberately separate from ``faithfulness_node`` (post-answer text
grounding). The critic decides whether to spend another retrieval/tool hop; the
faithfulness checker only edits or refuses the generated answer.
"""

from __future__ import annotations

from app.agents.nodes.sufficiency import (
    _KNOWLEDGE_GAP,
    gap_query,
    needs_knowledge_evidence,
    required_tools,
)
from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.enums import RetrievalStrategy, ToolExecutionStatus
from app.ops.targets import extract_service_target
from app.schemas.agent import ToolResult
from app.schemas.critic import CriticIssue, CriticResult

_SERVICE_TOOLS = {"get_service_status", "get_service_logs", "restart_service"}
_PROGRAM_TOOLS = {"get_supervisor_program_config"}


def _status(result: ToolResult) -> ToolExecutionStatus:
    return (
        result.status
        if isinstance(result.status, ToolExecutionStatus)
        else ToolExecutionStatus(str(result.status))
    )


def _successful_tool_result(tool: str, results: list[ToolResult]) -> ToolResult | None:
    for result in results:
        if result.name == tool and result.success and _status(result) == ToolExecutionStatus.OK:
            return result
    return None


def _failed_tool_result(tool: str, results: list[ToolResult]) -> ToolResult | None:
    """The requested tool itself failed, even if a fallback produced evidence."""
    for result in results:
        if result.name != tool and result.output.get("fallback_from") != tool:
            continue
        if not result.success or _status(result) == ToolExecutionStatus.FALLBACK:
            return result
    return None


def _plan_has_tool(state: AgentState, tool: str) -> bool:
    plan = state.get("plan")
    return bool(plan and any(step.tool_name == tool for step in plan.steps))


def _target_mismatch(state: AgentState) -> str | None:
    """The plan must read the service the user actually named."""
    target = extract_service_target(state["user_query"])
    if target.name is None:
        return None
    plan = state.get("plan")
    if plan is None:
        return None
    for step in plan.steps:
        if step.tool_name in _SERVICE_TOOLS and step.arguments.get("service"):
            if step.arguments["service"] != target.name:
                return f"计划查询 {step.arguments['service']}，用户目标是 {target.name}"
        if step.tool_name in _PROGRAM_TOOLS and step.arguments.get("program"):
            if step.arguments["program"] != target.name:
                return f"计划查询 Supervisor 程序 {step.arguments['program']}，用户目标是 {target.name}"
    return None


def _structured_conflicts(results: list[ToolResult]) -> list[str]:
    """Only explicit, structured inconsistencies; no prose guessing."""
    issues: list[str] = []
    service_states: dict[tuple[str, str], set[str]] = {}
    package_states: dict[tuple[str, str], set[str]] = {}
    for result in results:
        if result.name == "get_service_status" and result.success:
            key = (str(result.output.get("host", "")), str(result.output.get("service", "")))
            service_states.setdefault(key, set()).add(str(result.output.get("state", "")))
        if result.name == "get_rpm_info" and result.success:
            key = (str(result.output.get("host", "")), str(result.output.get("name", "")))
            package_states.setdefault(key, set()).add(str(result.output.get("state", "")))
    program_states: dict[tuple[str, str], set[str]] = {}
    for result in results:
        if result.name == "list_supervisor_programs" and result.success:
            for item in result.output.get("programs") or []:
                if not isinstance(item, dict):
                    continue
                key = (str(result.output.get("host", "")), str(item.get("program", "")))
                program_states.setdefault(key, set()).add(str(item.get("state", "")))
    for label, grouped in (
        ("服务", service_states),
        ("软件包", package_states),
        ("Supervisor 程序", program_states),
    ):
        for key, states in grouped.items():
            states.discard("")
            if len(states) > 1:
                issues.append(f"{label} {key[1] or key[0]} 同时出现多个状态：{sorted(states)}")

    service_map = {
        (str(result.output.get("host", "")), str(result.output.get("service", ""))): result
        for result in results
        if result.name == "get_service_status" and result.success
    }
    for result in results:
        if result.name != "list_supervisor_programs" or not result.success:
            continue
        for item in result.output.get("programs") or []:
            if not isinstance(item, dict):
                continue
            key = (
                str(result.output.get("host", "")),
                str(item.get("service", item.get("program", ""))),
            )
            status = service_map.get(key)
            if status is not None and str(status.output.get("state", "")) != str(
                item.get("state", "")
            ):
                issues.append(
                    f"Supervisor 程序 {item.get('program')} 在清单与 get_service_status 中状态不一致"
                )

    rpm_info = {
        str(result.output.get("name", "")): result
        for result in results
        if result.name == "get_rpm_info" and result.success
    }
    for result in results:
        if result.name != "check_rpm_dependencies" or not result.success:
            continue
        package = str(result.output.get("package", ""))
        info = rpm_info.get(package)
        missing = result.output.get("missing") or []
        conflicts = result.output.get("conflicts") or []
        if (
            info is not None
            and str(info.output.get("state", "")) == "installed"
            and (missing or conflicts)
        ):
            issues.append(f"{package} 显示已安装，但依赖检查存在缺失/冲突")
    return issues


def _downgrade_if_exhausted(
    state: AgentState, settings: Settings, issues: list[CriticIssue], action: str
) -> str:
    """After the correction budget, never request another hop."""
    if (
        action in {"retrieve", "plan"}
        and int(state.get("critic_round") or 0) >= settings.max_correction_rounds
    ):
        for issue in issues:
            if issue.action == action and issue.severity == "blocking":
                issue.severity = "warning"
                issue.action = "accept"
                issue.message = f"{issue.message}（修正轮数已用尽，改为在答案中说明证据不足）"
        return "accept"
    return action


def critic_node(state: AgentState, settings: Settings) -> dict:
    query = state["user_query"]
    strategy = state.get("strategy")
    required = (
        required_tools(query)
        if strategy in {RetrievalStrategy.AGENT, RetrievalStrategy.MULTI}
        or state.get("plan") is not None
        else []
    )
    results = list(state.get("tool_results") or [])
    evidence = state.get("evidence") or []
    knowledge_present = any(item.kind.value == "knowledge" for item in evidence)
    tool_present = any(item.kind.value == "tool" for item in evidence)
    issues: list[CriticIssue] = []
    checked = [
        "plan_coverage",
        "tool_status",
        "evidence_kinds",
        "evidence_conflict",
        "missing_target",
        "plan_repeat",
    ]

    if state.get("pending_action") is not None:
        return {
            "critic_result": CriticResult(
                passed=True,
                issues=[
                    CriticIssue(
                        code="missing_tool",
                        message="操作已生成人工确认单，等待用户确认后再执行",
                        severity="warning",
                        action="accept",
                    )
                ],
                next_action="accept",
                checked=["pending_confirmation"],
            ),
            "critic_round": int(state.get("critic_round") or 0),
        }

    extra = state.get("extra") or {}
    if extra.get("missing_target"):
        kind = str(extra.get("missing_target_kind") or "service")
        label = "服务名或 Supervisor 托管程序名" if kind == "service" else "RPM 软件包名"
        issues.append(
            CriticIssue(
                code="missing_target",
                message=f"缺少{label}，不能猜测后继续执行",
                severity="blocking",
                action="clarify",
            )
        )

    # Plan coverage: a required tool missing from both plan and results.
    for tool in required:
        if _plan_has_tool(state, tool):
            continue
        if _successful_tool_result(tool, results) is not None:
            continue
        failed = _failed_tool_result(tool, results)
        if failed is not None:
            detail = failed.error or str(failed.output.get("fallback_error") or "") or "未返回原因"
            issues.append(
                CriticIssue(
                    code="tool_failed",
                    message=f"{tool} 执行失败：{detail[:100]}",
                    severity="warning",
                    action="accept",
                    tool=tool,
                )
            )
            continue
        issues.append(
            CriticIssue(
                code="missing_tool",
                message=f"计划未覆盖必要工具 {tool}",
                severity="blocking",
                action="plan",
                tool=tool,
            )
        )

    # Tool status: a required tool that ran but produced no usable result.
    for tool in required:
        failed = _failed_tool_result(tool, results)
        if (
            failed is None
            and _plan_has_tool(state, tool)
            and _successful_tool_result(tool, results) is None
            and not state.get("pending_action")
        ):
            issues.append(
                CriticIssue(
                    code="missing_tool",
                    message=f"{tool} 在计划中但本轮没有执行结果",
                    severity="blocking",
                    action="plan",
                    tool=tool,
                )
            )
        if failed is not None and not any(issue.tool == tool for issue in issues):
            detail = failed.error or str(failed.output.get("fallback_error") or "") or "未返回原因"
            issues.append(
                CriticIssue(
                    code="tool_failed",
                    message=f"{tool} 执行失败：{detail[:100]}",
                    severity="warning",
                    action="accept",
                    tool=tool,
                )
            )
        for result in results:
            if result.name != tool and result.output.get("fallback_from") != tool:
                continue
            status = _status(result)
            if status == ToolExecutionStatus.FALLBACK:
                issues.append(
                    CriticIssue(
                        code="fallback_warning",
                        message=f"{result.requested_name or tool} 不可用，已降级为 {result.name}",
                        severity="warning",
                        action="accept",
                        tool=tool,
                    )
                )

    # Diagnostic AGENT needs knowledge as well as live tool evidence.
    if not state.get("confirmed_action") and needs_knowledge_evidence(query, strategy, required):
        if not knowledge_present:
            exhausted = int(state.get("retrieval_round") or 0) >= settings.max_evidence_hops
            issues.append(
                CriticIssue(
                    code="missing_knowledge",
                    message=(
                        _KNOWLEDGE_GAP if not exhausted else f"{_KNOWLEDGE_GAP}，且检索轮数已用尽"
                    ),
                    severity="warning" if exhausted else "blocking",
                    action="accept" if exhausted else "retrieve",
                )
            )

    if strategy == RetrievalStrategy.AGENT and required and not state.get("confirmed_action"):
        if not tool_present:
            missing = [tool for tool in required if not _plan_has_tool(state, tool)]
            if missing and not any(issue.tool == missing[0] for issue in issues):
                issues.append(
                    CriticIssue(
                        code="missing_tool",
                        message="尚未取得任何工具证据",
                        severity="blocking",
                        action="plan",
                        tool=missing[0],
                    )
                )

    mismatch = _target_mismatch(state)
    if mismatch:
        issues.append(
            CriticIssue(
                code="target_mismatch",
                message=mismatch,
                severity="blocking",
                action="plan",
            )
        )

    for conflict in _structured_conflicts(results):
        issues.append(
            CriticIssue(
                code="evidence_conflict",
                message=conflict,
                severity="warning",
                action="accept",
            )
        )

    fingerprint = state.get("plan_fingerprint")
    history = list(state.get("plan_history") or [])
    repeated_plan = bool(fingerprint and fingerprint in history[:-1])
    if repeated_plan:
        issues.append(
            CriticIssue(
                code="plan_repeat",
                message="重新规划得到与上一轮相同的工具计划，停止重复执行",
                severity="blocking",
                action="accept",
            )
        )

    blocking = [issue for issue in issues if issue.severity == "blocking"]
    if state.get("evidence_sufficient") is False and not blocking:
        gaps = state.get("evidence_gaps") or []
        if gaps:
            issues.append(
                CriticIssue(
                    code="tool_failed",
                    message="；".join(gaps)[:200],
                    severity="warning",
                    action="accept",
                )
            )

    if any(issue.action == "clarify" for issue in issues):
        action = "clarify"
    elif any(issue.action == "retrieve" for issue in blocking):
        action = "retrieve"
    elif any(issue.action == "plan" for issue in blocking):
        action = "plan"
    else:
        action = "accept"
    if repeated_plan and action == "plan":
        action = "accept"
    action = _downgrade_if_exhausted(state, settings, issues, action)

    gap = ""
    if action == "retrieve":
        gaps = [issue.message for issue in issues if issue.action == "retrieve"]
        gap = gap_query(query, gaps) or f"{query} {_KNOWLEDGE_GAP}"
    next_round = int(state.get("critic_round") or 0)
    if action in {"retrieve", "plan"}:
        next_round += 1
    return {
        "critic_result": CriticResult(
            passed=not any(issue.severity == "blocking" for issue in issues)
            or action in {"clarify", "accept"},
            issues=issues,
            next_action=action,  # type: ignore[arg-type]
            gap_query=gap or None,
            checked=checked,
        ),
        "critic_round": next_round,
        "critic_feedback": [issue.message for issue in issues if issue.severity == "blocking"],
    }
