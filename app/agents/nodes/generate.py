"""Answer generation and refusal nodes.

Citation and honesty rules that used to live in the prompt are now code:
- citations are derived from the unified evidence list, so AGENT runs cite too;
- an insufficient-evidence notice is prepended by the node itself, not by the model.
"""

from __future__ import annotations

import json
import time

from pydantic import BaseModel, Field

from app.agents.state import AgentState
from app.core.enums import RetrievalStrategy
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.ops.targets import extract_package
from app.prompts.answer import ANSWER_SYSTEM, ANSWER_USER
from app.providers.base import LLMProvider
from app.providers.fake import OfflineLLMProvider
from app.providers.json_parser import parse_model
from app.schemas.common import LatencyBreakdown, TokenUsage
from app.schemas.evidence import EvidenceItem, EvidenceKind, knowledge_evidence
from app.schemas.retrieval import Citation

INSUFFICIENT_BANNER = "【证据不足】{missing}。以下内容只基于已获取的证据，未确认部分不作断言。"


class AnswerPayload(BaseModel):
    answer: str
    citation_ids: list[str] = Field(default_factory=list)
    refused: bool = False


def citations_from_evidence(evidence: list[EvidenceItem], selected: set[str]) -> list[Citation]:
    """Derive public citations from evidence ids chosen by the answer."""
    citations: list[Citation] = []
    for item in evidence:
        if selected and item.evidence_id not in selected:
            continue
        citations.append(
            Citation(
                citation_id=item.evidence_id,
                kind=item.kind.value,
                document_id=item.metadata.get("document_id", ""),
                title=item.title,
                chunk_id=item.reference if item.kind == EvidenceKind.KNOWLEDGE else "",
                section=item.metadata.get("section") or None,
                locator=item.reference,
                excerpt=item.excerpt,
            )
        )
    return citations


def _evidence_block(evidence: list[EvidenceItem], limit: int = 8) -> str:
    if not evidence:
        return "(无证据)"
    return "\n\n".join(item.prompt_block() for item in evidence[:limit])


def _tool_text(results) -> str:
    if not results:
        return "(无)"
    payload = json.dumps([r.model_dump() for r in results], ensure_ascii=False)
    return payload[:4000]


def _insufficiency_prefix(state: AgentState) -> str:
    if state.get("evidence_sufficient", True):
        return ""
    gaps = state.get("evidence_gaps") or ["关键证据未取得"]
    return INSUFFICIENT_BANNER.format(missing="；".join(gaps[:3])) + "\n\n"


def _critic_note(state: AgentState) -> str:
    """Surface critic warnings (fallback, failure, conflict) in the answer."""
    result = state.get("critic_result")
    if result is None:
        return ""
    notes = [
        issue.message
        for issue in result.issues
        if issue.code in {"fallback_warning", "evidence_conflict"} and issue.severity == "warning"
    ]
    if not notes:
        return ""
    return "【证据提示】" + "；".join(dict.fromkeys(notes))[:300] + "\n\n"


async def generate_node(state: AgentState, llm: LLMProvider) -> dict:
    started = time.perf_counter()
    evidence = state.get("evidence") or []
    if not evidence:
        # Defensive: a caller that only supplied retrieved chunks still yields a
        # citable answer instead of an unexplained refusal.
        evidence = [knowledge_evidence(chunk) for chunk in state.get("retrieved_chunks") or []]
    tools = state.get("tool_results") or []
    prefix = _insufficiency_prefix(state) + _critic_note(state)

    if tools and all(not tool.success for tool in tools) and not evidence:
        return {
            "final_answer": prefix
            + "所有运维工具调用均失败，无法确认目标主机状态。请检查主机授权或稍后重试。",
            "citations": [],
            "evidence_sufficient": False,
        }
    extra = state.get("extra") or {}
    if extra.get("missing_target"):
        kind = extra.get("missing_target_kind") or "service"
        if kind == "service":
            label = "服务名，或 Supervisor 托管的程序名"
            example = "nginx 或 app-worker"
        else:
            label = "RPM 软件包名"
            example = "nginx"
        return {
            "final_answer": (
                f"请提供{label}（例如 {example}）。"
                "缺少目标时不能猜测服务或软件包，确认后我才能继续排查。"
            ),
            "citations": [],
        }
    # The user did provide a package, but rpm has no such package on the host.
    # This is "not found", not "missing argument".
    package = extract_package(state["user_query"])
    if package:
        package_failure = next(
            (
                tool
                for tool in tools
                if (tool.name == "get_rpm_info" or tool.requested_name == "get_rpm_info")
                and (
                    not tool.success
                    or str(getattr(tool.status, "value", tool.status)) == "fallback"
                )
            ),
            None,
        )
        if package_failure is not None:
            error = " ".join(
                [
                    package_failure.error or "",
                    str(package_failure.output.get("fallback_error") or ""),
                    str(package_failure.failure_kind or ""),
                ]
            ).lower()
            if (
                "not found" in error
                or "not installed" in error
                or "未找到" in error
                or "package_not_found" in error
            ):
                host = state.get("host_id") or "目标主机"
                citations = citations_from_evidence(evidence, set())
                return {
                    "final_answer": (
                        prefix + f"未在 {host} 查询到软件包 {package} 的信息"
                        f"（工具返回：{package_failure.error or package_failure.output.get('fallback_error')}）。"
                        "这不属于缺少参数：包名已提供，但当前主机或仓库中没有该包，"
                        "请核对包名、主机与软件源后重试。"
                    ),
                    "citations": citations,
                    "evidence_sufficient": False,
                }
    pending = state.get("pending_action")
    if pending:
        latency = state.get("latency") or LatencyBreakdown()
        latency.llm_ms = (time.perf_counter() - started) * 1000
        return {
            "final_answer": f"{prefix}{pending.summary}",
            "citations": [],
            "refused": False,
            "latency": latency,
        }

    block = _evidence_block(evidence)
    tool_text = _tool_text(tools)
    intent = state.get("intent")
    strategy = state.get("strategy") or RetrievalStrategy.DIRECT
    if isinstance(llm, OfflineLLMProvider):
        answer, selected = _offline_answer(state, evidence)
        return {
            "final_answer": prefix + answer,
            "citations": citations_from_evidence(evidence, selected),
            "refused": False,
        }
    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {
            "role": "user",
            "content": ANSWER_USER.format(
                query=state["user_query"],
                intent=intent.label.value if intent else "unknown",
                strategy=strategy.value,
                evidence=block,
                tool_results=tool_text,
            ),
        },
    ]
    try:
        response = await llm.generate(
            messages,
            temperature=0.2,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        payload = parse_model(response.content, AnswerPayload)
        usage = response.usage
    except (LLMProviderError, LLMOutputError):
        fallback_text, selected = _offline_answer(state, evidence)
        payload = AnswerPayload(answer=fallback_text, citation_ids=sorted(selected))
        usage = TokenUsage()
    if not payload.citation_ids and evidence:
        # Never ship a diagnosis with zero citations when evidence exists.
        payload.citation_ids = [item.evidence_id for item in evidence[:4]]
    citations = citations_from_evidence(evidence, set(payload.citation_ids))
    latency = state.get("latency") or LatencyBreakdown()
    latency.llm_ms = (time.perf_counter() - started) * 1000
    prev_usage = state.get("token_usage") or TokenUsage()
    merged = TokenUsage(
        prompt_tokens=prev_usage.prompt_tokens + usage.prompt_tokens,
        completion_tokens=prev_usage.completion_tokens + usage.completion_tokens,
        total_tokens=prev_usage.total_tokens + usage.total_tokens,
    )
    return {
        "final_answer": prefix + payload.answer,
        "citations": citations,
        "refused": payload.refused,
        "latency": latency,
        "token_usage": merged,
    }


async def refuse_node(state: AgentState) -> dict:
    return {
        "final_answer": (
            "这个问题超出操作系统运维支持范围，我无法协助。"
            "如果是危险命令或越权操作，请通过变更工单与人工审批流程处理；"
            "如果是知识问题，请补充具体系统版本、服务名或报错信息。"
        ),
        "refused": True,
        "citations": [],
    }


def _extractive_fallback(query: str, evidence: str, tool_text: str) -> str:
    if evidence and evidence != "(无证据)":
        snippet = evidence.split("\n", 1)[-1][:240].strip()
        return f"暂时无法生成完整答复。相关证据节选：\n\n> {snippet}\n\n请以原文为准。"
    if tool_text and tool_text != "(无)":
        return "已查询到主机数据，但暂时无法可靠地整理答复。请稍后重试或转人工。"
    return "暂时无法基于现有信息给出可靠答复，请补充主机、服务或报错信息。"


def _service_state_cn(state: str) -> str:
    return {
        "active": "运行中",
        "failed": "启动失败",
        "inactive": "未运行",
        "activating": "启动中",
        "deactivating": "停止中",
    }.get(state, state or "未知")


_OFFLINE_PRIORITY = (
    "get_system_info",
    "get_service_status",
    "check_rpm_dependencies",
    "get_rpm_info",
    "get_disk_usage",
    "get_cpu_memory",
    "get_service_logs",
    "aggregate_error_logs",
    "search_elasticsearch_logs",
    "get_logstash_pipeline_status",
    "list_supervisor_programs",
    "get_supervisor_program_config",
    "restart_service",
    "search_knowledge",
)


def _ordered_tool_results(results) -> list:
    """Most decision-relevant evidence first; logs are supporting, not primary.

    A deterministic offline answer must not lead with the last tool that happened
    to run (a log tail) when a failed state is the finding.
    """
    ranked = {name: index for index, name in enumerate(_OFFLINE_PRIORITY)}
    return sorted(
        results,
        key=lambda r: (ranked.get(r.name, len(_OFFLINE_PRIORITY)), 0),
    )


def _failed_service_diagnosis(results) -> str | None:
    """Merge status + logs + package facts for a failed service, offline.

    The old renderer returned after the first successful tool and dropped the
    log tail, so a failed service was described but not explained. This keeps
    every sentence anchored to a structured tool field.
    """
    status = next(
        (
            result
            for result in results
            if result.name == "get_service_status"
            and result.success
            and str(result.output.get("state")) in {"failed", "inactive"}
        ),
        None,
    )
    if status is None:
        return None
    data = status.output
    service = str(data.get("service", ""))
    host = data.get("host") or "目标主机"
    parts = [
        f"{host} 服务 {service}（{data.get('manager', 'systemd')}）状态："
        f"{_service_state_cn(str(data.get('state')))}"
        + (f"，退出码 {data.get('exit_code')}" if data.get("exit_code") not in (None, 0) else "")
        + f"，重启次数 {data.get('restart_count', 0)}"
        + (f"，最近失败时间 {data.get('last_failure_at')}" if data.get("last_failure_at") else "")
    ]
    logs = next(
        (
            result
            for result in results
            if result.name == "get_service_logs"
            and result.success
            and str(result.output.get("service")) == service
        ),
        None,
    )
    if logs is not None:
        entries = logs.output.get("entries") or []
        severe = {"emerg", "alert", "crit", "err", "error", "fatal", "warn", "warning"}
        interesting = [
            entry
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("level", "")).lower() in severe
        ]
        selected = (interesting or entries)[:3]
        recent = [
            f"[{entry.get('level', '')}] {str(entry.get('msg', ''))[:180]}"
            for entry in selected
            if isinstance(entry, dict)
        ]
        if recent:
            parts.append("关键日志：" + "；".join(recent))
    rpm = next(
        (
            result
            for result in results
            if result.name == "check_rpm_dependencies" and result.success
        ),
        None,
    )
    if rpm is not None:
        output = rpm.output
        details = []
        if output.get("missing"):
            details.append(f"缺失依赖 {output.get('missing')}")
        if output.get("conflicts"):
            details.append(f"冲突 {output.get('conflicts')}")
        if output.get("broken_by"):
            details.append(f"被 {output.get('broken_by')} 破坏")
        if output.get("stale_files"):
            details.append(f"残留文件 {output.get('stale_files')}")
        if details:
            parts.append("软件包检查：" + "；".join(details))
    supervisor = next(
        (
            result
            for result in results
            if result.name == "get_supervisor_program_config" and result.success
        ),
        None,
    )
    if supervisor is not None:
        cfg = supervisor.output
        parts.append(
            "Supervisor 配置："
            f"command={cfg.get('command', '')}；"
            f"autostart={cfg.get('autostart')}；"
            f"autorestart={cfg.get('autorestart')}；"
            f"startsecs={cfg.get('startsecs')}；"
            f"startretries={cfg.get('startretries')}"
        )
        if "exited too quickly" in str(data.get("last_error", "")).lower():
            parts.append(
                "重启策略判断："
                f"autorestart={cfg.get('autorestart')}、startsecs={cfg.get('startsecs')}、"
                f"startretries={cfg.get('startretries')}；日志中的 Exited too quickly 表示"
                "程序在 startsecs 内提前退出，FATAL 表示重试耗尽后的保护状态，"
                "不能仅归因于 Supervisor 配置"
            )
    return "。".join(parts) + "。"


def _elk_diagnosis(results) -> str | None:
    """Render Elasticsearch aggregation/search/Logstash facts, not root-cause prose."""
    aggregate = next(
        (result for result in results if result.name == "aggregate_error_logs" and result.success),
        None,
    )
    if aggregate is None:
        return None
    data = aggregate.output
    host = data.get("host") or "目标主机"
    buckets = data.get("buckets") or []
    parts = [
        f"{host} Elasticsearch 在索引模式 {data.get('index_pattern')} 中命中 "
        f"{data.get('total_errors', 0)} 条 ERROR（聚合维度 {data.get('group_by')}）"
    ]
    if buckets:
        top = [
            f"{bucket.get('key')}：{bucket.get('count')} 次"
            for bucket in buckets[:3]
            if isinstance(bucket, dict)
        ]
        parts.append("主要聚合：" + "；".join(top))
        samples = [
            str(bucket.get("sample_message", ""))[:160]
            for bucket in buckets[:2]
            if isinstance(bucket, dict) and bucket.get("sample_message")
        ]
        if samples:
            parts.append("典型消息：" + "；".join(samples))
        services = sorted(
            {
                service
                for bucket in buckets
                if isinstance(bucket, dict)
                for service in (bucket.get("services") or [])
            }
        )
        if services:
            parts.append("涉及服务：" + "、".join(services[:6]))
    else:
        parts.append("当前过滤条件下没有 ERROR 记录")
    search = next(
        (
            result
            for result in results
            if result.name == "search_elasticsearch_logs" and result.success
        ),
        None,
    )
    if search is not None:
        total = search.output.get("total", 0)
        entries = search.output.get("entries") or []
        parts.append(f"原始检索命中 {total} 条，返回 {len(entries)} 条")
        if entries:
            first = entries[0]
            parts.append(
                f"最新一条：{first.get('timestamp')} [{first.get('level')}] "
                f"{str(first.get('message', ''))[:160]}"
            )
    logstash = next(
        (
            result
            for result in results
            if result.name == "get_logstash_pipeline_status" and result.success
        ),
        None,
    )
    if logstash is not None:
        summary = logstash.output.get("summary") or {}
        failed = [
            pipeline.get("pipeline_id")
            for pipeline in logstash.output.get("pipelines") or []
            if isinstance(pipeline, dict) and pipeline.get("state") != "running"
        ]
        parts.append(
            f"Logstash Pipeline：共 {summary.get('total', 0)} 个，"
            f"running={summary.get('running', 0)}，failed={summary.get('failed', 0)}，"
            f"unavailable={summary.get('unavailable', 0)}"
        )
        if failed:
            parts.append("异常 Pipeline：" + "、".join(str(item) for item in failed))
    parts.append("以上为日志与采集状态事实；根因需结合知识库排查项和业务变更进一步核实")
    return "。".join(parts) + "。"


def _offline_answer(state: AgentState, evidence: list[EvidenceItem]) -> tuple[str, set[str]]:
    """Render answer strictly from retrieved text or whitelisted tool fields."""
    strategy = state.get("strategy")
    if strategy == RetrievalStrategy.DIRECT:
        return (
            "你好，我可以帮你查询操作系统知识、RPM 包信息、服务状态与系统日志。",
            set(),
        )
    if strategy in {RetrievalStrategy.AGENT, RetrievalStrategy.MULTI}:
        diagnosis = _failed_service_diagnosis(state.get("tool_results") or [])
        if diagnosis:
            return (diagnosis, set())
        elk = _elk_diagnosis(state.get("tool_results") or [])
        if elk:
            return (elk, set())

    for result in _ordered_tool_results(state.get("tool_results") or []):
        if not result.success:
            continue
        data = result.output
        host = data.get("host") or data.get("host_id") or state.get("host_id") or "目标主机"
        if result.name == "get_system_info":
            return (
                f"{host}：{data.get('os_name', '')} {data.get('os_version', '')}，"
                f"内核 {data.get('kernel', '')}（{data.get('arch', '')}）。",
                set(),
            )
        if result.name == "get_cpu_memory":
            cpu = data.get("cpu") or {}
            mem = data.get("memory") or {}
            return (
                f"{host} CPU 使用率 {cpu.get('usage_pct', '?')}%，1 分钟负载 {cpu.get('load_1', '?')}；"
                f"内存使用率 {mem.get('usage_pct', '?')}%，可用 {mem.get('available_kb', '?')} KB。",
                set(),
            )
        if result.name == "get_disk_usage":
            filesystems = data.get("filesystems") or []
            lines = [
                f"{f.get('mount')} 使用 {f.get('use_pct')}%（可用 {f.get('avail_kb')} KB）"
                for f in filesystems
                if isinstance(f, dict)
            ]
            return (f"{host} 文件系统：" + "；".join(lines[:4]) + "。", set())
        if result.name == "get_service_status":
            return (
                f"服务 {data.get('service')}（{data.get('manager')}）当前状态："
                f"{_service_state_cn(str(data.get('state')))}"
                f"{'，退出码 ' + str(data.get('exit_code')) if data.get('exit_code') not in (None, 0) else ''}"
                f"；重启次数 {data.get('restart_count', 0)}。"
                + (f" 最近错误：{data.get('last_error')}" if data.get("last_error") else ""),
                set(),
            )
        if result.name == "get_service_logs":
            entries = data.get("entries") or []
            if entries:
                last = entries[-1]
                return (
                    f"服务 {data.get('service')} 最近日志（{len(entries)} 行），最后一条："
                    f"[{last.get('level')}] {last.get('msg')}",
                    set(),
                )
            return (f"服务 {data.get('service')} 没有可用的日志记录。", set())
        if result.name == "get_rpm_info":
            return (
                f"软件包 {data.get('name')} 当前版本 {data.get('epoch')}:{data.get('version')}-"
                f"{data.get('release')}.{data.get('arch')}，安装于 {data.get('install_time')}。",
                set(),
            )
        if result.name == "check_rpm_dependencies":
            missing = data.get("missing") or []
            broken = data.get("broken_by") or []
            stale = data.get("stale_files") or []
            return (
                f"{data.get('package')} 依赖检查：缺失 {len(missing)} 项"
                + (f"（{', '.join(map(str, missing[:3]))}）" if missing else "")
                + (f"；被 {', '.join(map(str, broken[:2]))} 破坏" if broken else "")
                + (f"；残留文件 {', '.join(map(str, stale[:2]))}" if stale else "")
                + "。",
                set(),
            )
        if result.name == "restart_service":
            return (
                f"已提交对 {data.get('service')} 的重启请求（模拟后端，未真实执行）；"
                f"当前状态 {data.get('state', 'unknown')}。",
                set(),
            )
        if result.name == "search_knowledge":
            found = data.get("chunks") or []
            if found and isinstance(found[0], dict):
                chunk_item = found[0]
                title = str(chunk_item.get("title") or "相关知识")
                excerpt = str(chunk_item.get("content") or "").strip()[:260]
                chunk_id = chunk_item.get("chunk_id")
                return (
                    f"当前未配置生成模型。找到《{title}》中的资料节选，请核对原文：\n\n> {excerpt}",
                    {f"kb:{chunk_id}"} if chunk_id else set(),
                )

    if evidence:
        item = evidence[0]
        excerpt = item.excerpt.strip()[:260]
        return (
            f"当前未配置生成模型，以下是《{item.title}》的证据节选，请核对原文：\n\n> {excerpt}",
            {item.evidence_id},
        )
    return ("当前无法可靠回答这个问题。请补充主机、服务名或报错信息，或转人工。", set())
