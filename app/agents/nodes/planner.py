"""Planner that turns intent, skills and complexity into ops tool plans.

Two invariants are enforced here, not in the prompt:
1. A step may only call a registered tool with arguments that pass that tool's
   pydantic schema, so a command string can never reach execution.
2. Write tools are dropped unless the user explicitly asked for the change;
   then a pending confirmation is proposed instead of executing.
"""

from __future__ import annotations

import hashlib
import json

from app.agents.nodes.sufficiency import required_tools
from app.agents.state import AgentState
from app.core.exceptions import InvalidRequestError, LLMOutputError, LLMProviderError
from app.core.ids import new_id
from app.ops.targets import (
    extract_host,
    extract_package,
    extract_service,
    extract_service_target,
)
from app.prompts.planner import PLANNER_SYSTEM, PLANNER_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.agent import AgentPlan, PlanStep
from app.schemas.chat import ActionProposal
from app.skills.loader import match_skill
from app.tools.permissions import WRITE_RISKS
from app.tools.registry import ToolRegistry

_ALWAYS_AVAILABLE = ("search_knowledge", "escalate_to_human")
_WRITE_ACTIONS = ("restart_service",)


class Planner:
    def __init__(self, llm: LLMProvider, registry: ToolRegistry) -> None:
        self._llm = llm
        self._registry = registry

    def _tool_catalog(self, allowed: set[str] | None = None) -> str:
        lines = []
        for tool in self._registry.all():
            if allowed is not None and tool.name not in allowed:
                continue
            lines.append(f"- {tool.name}: {tool.description} [{tool.risk.value}]")
        return "\n".join(lines) or "- (no tools)"

    async def create_plan(
        self,
        query: str,
        intent_label: str,
        summary: str,
        host_id: str | None = None,
        *,
        knowledge_available: bool = False,
        critic_feedback: list[str] | None = None,
    ) -> AgentPlan:
        skill = match_skill(query, intent_label)
        allowed = _allowed_tools(skill, self._registry)
        plan: AgentPlan | None = None
        if isinstance(self._llm, OfflineLLMProvider):
            plan = (
                skill_to_plan(skill, query, self._registry, host_id)
                if skill
                else heuristic_plan(query, self._registry, host_id)
            )
        else:
            try:
                response = await self._llm.generate(
                    [
                        {
                            "role": "system",
                            "content": PLANNER_SYSTEM.format(
                                tools=self._tool_catalog(allowed),
                                skill_context=_format_skill(skill),
                            ),
                        },
                        {
                            "role": "user",
                            "content": PLANNER_USER.format(
                                query=query, intent=intent_label, summary=summary or "无"
                            ),
                        },
                    ],
                    temperature=0.0,
                    max_tokens=512,
                    response_format={"type": "json_object"},
                )
                parsed = parse_model(response.content, AgentPlan)
                parsed = _sanitize_plan(parsed, self._registry, allowed)
                if parsed.steps:
                    if skill:
                        parsed.rationale = f"skill:{skill['name']};{parsed.rationale}"
                    plan = parsed
            except (LLMOutputError, LLMProviderError):
                pass
        if plan is None:
            if skill:
                plan = skill_to_plan(skill, query, self._registry, host_id)
            else:
                plan = heuristic_plan(query, self._registry, host_id)
        return _finalize_plan(
            plan,
            query,
            self._registry,
            host_id,
            knowledge_available=knowledge_available,
            critic_feedback=critic_feedback,
        )


def _allowed_tools(skill: dict | None, registry: ToolRegistry) -> set[str] | None:
    if skill is None:
        return None
    names = set(registry.names())
    allowed = {name for name in skill.get("tools", []) if name in names}
    allowed.update(name for name in _ALWAYS_AVAILABLE if name in names)
    return allowed or None


def _format_skill(skill: dict | None) -> str:
    if skill is None:
        return "无（通用工具集）"
    steps = "、".join(skill.get("steps") or [])
    tools = ", ".join(skill.get("tools") or [])
    return f"{skill['name']}：{skill.get('description', '')}。步骤：{steps}。工具：{tools}"


def _step_is_valid(step: PlanStep, registry: ToolRegistry) -> bool:
    """Drop any step whose tool is unknown or whose arguments fail validation."""
    if not step.tool_name:
        return True
    if step.tool_name not in registry.names():
        return False
    try:
        registry.get(step.tool_name).parse(step.arguments)
    except InvalidRequestError:
        return False
    return True


def _sanitize_plan(
    plan: AgentPlan,
    registry: ToolRegistry,
    allowed: set[str] | None,
) -> AgentPlan:
    steps = []
    for step in plan.steps:
        if allowed is not None and step.tool_name and step.tool_name not in allowed:
            continue
        if not _step_is_valid(step, registry):
            continue
        steps.append(step)
    return AgentPlan(steps=steps[:6], rationale=plan.rationale)


def skill_to_plan(
    skill: dict, query: str, registry: ToolRegistry, host_id: str | None = None
) -> AgentPlan:
    steps: list[PlanStep] = []
    for index, tool_name in enumerate(skill.get("tools", []), start=1):
        if tool_name not in registry.names():
            continue
        arguments = tool_arguments(tool_name, query, host_id)
        step = PlanStep(
            step_id=index,
            goal=skill["name"],
            tool_name=tool_name,
            arguments=arguments,
            needs_retrieval=tool_name == "search_knowledge",
        )
        if _step_is_valid(step, registry):
            steps.append(step)
    if steps:
        return AgentPlan(steps=steps, rationale=f"skill:{skill['name']}")
    return heuristic_plan(query, registry, host_id)


def tool_arguments(tool_name: str, query: str, host_id: str | None = None) -> dict:
    """Fill tool arguments from the question using deterministic extractors."""
    host = extract_host(query) or host_id
    base = {"host_id": host} if host else {}
    if tool_name == "search_knowledge":
        return {"query": query[:200]}
    if tool_name == "get_system_info":
        return base
    if tool_name == "get_cpu_memory":
        return {**base, "top_n": 5}
    if tool_name == "get_disk_usage":
        return base
    service = extract_service(query)
    if tool_name == "get_service_status":
        return {**base, "service": service} if service else {}
    if tool_name == "get_service_logs":
        return {**base, "service": service, "lines": 50} if service else {}
    if tool_name == "list_supervisor_programs":
        return base
    if tool_name == "get_supervisor_program_config":
        return {**base, "program": service} if service else {}
    if tool_name == "search_elasticsearch_logs":
        arguments: dict = {
            **base,
            "index_pattern": "app-logs-*",
            "limit": 100,
            "sort": "desc",
        }
        if service:
            arguments["service"] = service
        lowered = query.lower()
        if "warn" in lowered or "警告" in query:
            arguments["level"] = "WARN"
        elif "error" in lowered or "错误" in query or "异常" in query:
            arguments["level"] = "ERROR"
        return arguments
    if tool_name == "aggregate_error_logs":
        arguments = {
            **base,
            "index_pattern": "app-logs-*",
            "group_by": "error_type",
            "interval": "5m",
            "limit": 20,
        }
        if service:
            arguments["service"] = service
        return arguments
    if tool_name == "get_logstash_pipeline_status":
        return base
    if tool_name == "restart_service":
        return {**base, "service": service, "reason": query[:200]} if service else {}
    package = extract_package(query)
    if tool_name in {"get_rpm_info", "check_rpm_dependencies"}:
        return {**base, "package": package} if package else {}
    return base


def heuristic_plan(query: str, registry: ToolRegistry, host_id: str | None = None) -> AgentPlan:
    """Deterministic ops plan used when the LLM is offline or returns junk."""
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
        wanted += ["list_supervisor_programs"]
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
    if any(cue in lowered for cue in ("依赖", "冲突", "兼容", "dlopen", "模块")):
        wanted += ["check_rpm_dependencies", "get_rpm_info"]
    elif any(cue in lowered for cue in ("rpm", "yum", "dnf", "包", "升级", "安装")):
        wanted.append("get_rpm_info")
    if not elk and any(cue in lowered for cue in ("日志", "log", "journal", "报错", "error")):
        wanted.append("get_service_logs")
    if not elk and any(
        cue in lowered
        for cue in ("服务", "启动", "起不来", "failed", "状态", "systemctl", "supervisor")
    ):
        wanted += ["get_service_status"]
    if any(cue in lowered for cue in ("cpu", "内存", "负载", "oom")):
        wanted.append("get_cpu_memory")
    if "磁盘" in lowered:
        wanted.append("get_disk_usage")
    if any(cue in lowered for cue in ("内核", "版本", "发行版")):
        wanted.append("get_system_info")
    if "重启" in lowered:
        wanted.append("restart_service")

    steps: list[PlanStep] = []
    seen: set[str] = set()
    for tool_name in wanted:
        if tool_name in seen or tool_name not in registry.names():
            continue
        arguments = tool_arguments(tool_name, query, host_id)
        if not arguments and tool_name != "search_knowledge":
            continue  # missing target, e.g. no service name found
        seen.add(tool_name)
        steps.append(
            PlanStep(
                step_id=len(steps) + 1,
                goal=tool_name,
                tool_name=tool_name,
                arguments=arguments,
            )
        )
    if not steps and "search_knowledge" in registry.names():
        return AgentPlan(
            steps=[
                PlanStep(
                    step_id=1,
                    goal="knowledge lookup",
                    tool_name="search_knowledge",
                    arguments={"query": query[:200]},
                    needs_retrieval=True,
                )
            ],
            rationale="fallback_knowledge",
        )
    return AgentPlan(steps=steps, rationale="heuristic_ops_plan")


def _step_key(step: PlanStep) -> tuple[str, str]:
    payload = json.dumps(step.arguments or {}, sort_keys=True, ensure_ascii=False, default=str)
    return (step.tool_name or "", payload)


def plan_fingerprint(plan: AgentPlan) -> str:
    """Stable digest of the executable steps, ignoring goal wording."""
    payload = [
        {"tool": step.tool_name, "arguments": step.arguments}
        for step in plan.steps
        if step.tool_name
    ]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _finalize_plan(
    plan: AgentPlan,
    query: str,
    registry: ToolRegistry,
    host_id: str | None,
    *,
    knowledge_available: bool,
    critic_feedback: list[str] | None = None,
) -> AgentPlan:
    """Deduplicate, skip already-retrieved knowledge, and add required tools."""
    steps: list[PlanStep] = []
    seen: set[tuple[str, str]] = set()
    for step in plan.steps:
        if knowledge_available and step.tool_name == "search_knowledge":
            continue
        if not _step_is_valid(step, registry):
            continue
        key = _step_key(step)
        if key in seen:
            continue
        seen.add(key)
        steps.append(step)

    for tool_name in required_tools(query):
        if knowledge_available and tool_name == "search_knowledge":
            continue
        if tool_name not in registry.names() or any(s.tool_name == tool_name for s in steps):
            continue
        arguments = tool_arguments(tool_name, query, host_id)
        if not arguments and tool_name != "search_knowledge":
            continue  # target missing: the planner node turns this into clarification
        step = PlanStep(
            step_id=len(steps) + 1,
            goal=tool_name,
            tool_name=tool_name,
            arguments=arguments,
            needs_retrieval=tool_name == "search_knowledge",
        )
        if _step_is_valid(step, registry) and _step_key(step) not in seen:
            seen.add(_step_key(step))
            steps.append(step)

    if not steps and not knowledge_available and "search_knowledge" in registry.names():
        steps.append(
            PlanStep(
                step_id=1,
                goal="knowledge lookup",
                tool_name="search_knowledge",
                arguments={"query": query[:200]},
                needs_retrieval=True,
            )
        )

    steps = [
        step.model_copy(update={"step_id": index}) for index, step in enumerate(steps[:6], start=1)
    ]
    rationale = plan.rationale
    if critic_feedback:
        rationale = f"{rationale};critic_feedback:{'; '.join(critic_feedback)[:200]}"
    return AgentPlan(steps=steps, rationale=rationale)


def _missing_target_kind(query: str) -> str | None:
    """Required tool family whose target the user never named."""
    required = required_tools(query)
    package_tools = {"get_rpm_info", "check_rpm_dependencies"}
    service_tools = {"get_service_status", "get_service_logs"}
    if package_tools.intersection(required) and extract_package(query) is None:
        return "package"
    if service_tools.intersection(required):
        target = extract_service_target(query)
        if target.name is None:
            return "service"
    return None


def _explicit_write_request(query: str) -> bool:
    """A write runs only on an explicit imperative, never on a question."""
    if any(
        cue in query
        for cue in ("怎么", "如何", "能不能", "可不可以", "是否", "可以吗", "为什么", "原因")
    ):
        return False
    return any(
        cue in query
        for cue in ("帮我重启", "重启一下", "请重启", "执行重启", "重新启动", "restart")
    )


def _ensure_write_step(plan: AgentPlan, state: AgentState, planner: Planner) -> AgentPlan:
    """An explicit restart request must be plannable even when the matched skill
    only shrinks to read tools. Without this the write path silently disappears.
    """
    if not _explicit_write_request(state["user_query"]):
        return plan
    names = planner._registry.names()
    if "restart_service" not in names:
        return plan
    if any(step.tool_name == "restart_service" for step in plan.steps):
        return plan
    service = extract_service(state["user_query"])
    if not service:
        return plan
    arguments: dict = {"service": service, "reason": state["user_query"][:200]}
    if state.get("host_id"):
        arguments["host_id"] = state["host_id"]
    kept = plan.steps[:3]
    return plan.model_copy(
        update={
            "steps": [
                *kept,
                PlanStep(
                    step_id=len(kept) + 1,
                    goal="restart_service",
                    tool_name="restart_service",
                    arguments=arguments,
                ),
            ]
        }
    )


def _action_summary(tool_name: str, arguments: dict) -> str:
    service = arguments.get("service", "该服务")
    host = arguments.get("host_id", "默认主机")
    if tool_name == "restart_service":
        return f"确认后将在 {host} 上重启 {service}（当前为 mock 后端，不会真正重启任何进程）。"
    return "确认后将提交该操作。"


async def planner_node(state: AgentState, planner: Planner) -> dict:
    confirmed = state.get("confirmed_action")
    if confirmed is not None:
        plan = AgentPlan(
            steps=[
                PlanStep(
                    step_id=1,
                    goal="confirmed action",
                    tool_name=confirmed.tool_name,
                    arguments=confirmed.arguments,
                )
            ],
            rationale="confirmed_action",
        )
        return {
            "plan": plan,
            "plan_fingerprint": plan_fingerprint(plan),
            "pending_action": None,
        }
    intent = state.get("intent")
    knowledge_available = any(
        item.kind.value == "knowledge" for item in state.get("evidence") or []
    )
    plan = await planner.create_plan(
        state["user_query"],
        intent.label.value if intent else "linux_basics",
        state.get("summary") or "",
        state.get("host_id"),
        knowledge_available=knowledge_available,
        critic_feedback=state.get("critic_feedback") or [],
    )
    missing_kind = _missing_target_kind(state["user_query"])
    if (
        missing_kind is None
        and _explicit_write_request(state["user_query"])
        and "restart_service" in planner._registry.names()
        and not extract_service(state["user_query"])
    ):
        missing_kind = "service"
    if missing_kind is not None:
        return {
            "plan": plan.model_copy(update={"steps": []}),
            "plan_fingerprint": plan_fingerprint(plan.model_copy(update={"steps": []})),
            "extra": {
                **(state.get("extra") or {}),
                "missing_target": True,
                "missing_target_kind": missing_kind,
            },
        }
    plan = _ensure_write_step(plan, state, planner)
    write_steps = [
        step
        for step in plan.steps
        if step.tool_name and planner._registry.get(step.tool_name).risk in WRITE_RISKS
    ]
    if write_steps and not _explicit_write_request(state["user_query"]):
        # The user asked about the action, not for it: keep the read steps only.
        plan = plan.model_copy(update={"steps": [s for s in plan.steps if s not in write_steps]})
        write_steps = []
    if write_steps and any(not step.arguments.get("service") for step in write_steps):
        return {
            "plan": plan.model_copy(update={"steps": []}),
            "plan_fingerprint": plan_fingerprint(plan.model_copy(update={"steps": []})),
            "extra": {
                **(state.get("extra") or {}),
                "missing_target": True,
                "missing_target_kind": "service",
            },
        }
    # Final pass after the write step was inserted: required read tools stay in,
    # duplicate (tool, arguments) pairs and already-answered knowledge lookups go.
    plan = _finalize_plan(
        plan,
        state["user_query"],
        planner._registry,
        state.get("host_id"),
        knowledge_available=knowledge_available,
        critic_feedback=state.get("critic_feedback") or [],
    )
    pending = None
    for step in write_steps:
        if state.get("confirm_action_id"):
            continue
        tool = planner._registry.get(step.tool_name or "")
        pending = ActionProposal(
            action_id=new_id("act_"),
            tool_name=tool.name,
            arguments=step.arguments,
            risk=tool.risk,
            summary=_action_summary(tool.name, step.arguments),
        )
        break
    fingerprint = plan_fingerprint(plan)
    history = list(state.get("plan_history") or [])
    return {
        "plan": plan,
        "plan_fingerprint": fingerprint,
        "plan_history": [*history, fingerprint],
        "pending_action": pending,
        "extra": {
            key: value
            for key, value in (state.get("extra") or {}).items()
            if key not in {"missing_target", "missing_target_kind"}
        },
    }
