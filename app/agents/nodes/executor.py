"""Tool execution node: timeout, fallback, idempotency, unified evidence."""

from __future__ import annotations

import hashlib
import json
import time

from app.agents.state import AgentState
from app.config.settings import Settings
from app.core.enums import ToolExecutionStatus
from app.core.exceptions import (
    AppError,
    InvalidRequestError,
    ToolExecutionError,
    ToolPermissionError,
    ToolTimeoutError,
)
from app.core.request_scope import get_db_session
from app.observability.metrics import TOOL_CALLS
from app.repositories.idempotency import IdempotencyRepository
from app.schemas.agent import PlanStep, ToolResult
from app.schemas.chat import ToolTraceItem
from app.schemas.common import LatencyBreakdown
from app.schemas.evidence import EvidenceItem, EvidenceKind, tool_evidence
from app.tools.base import Tool, ToolContext
from app.tools.permissions import WRITE_RISKS, assert_permitted
from app.tools.registry import ToolRegistry

# A failed read degrades to knowledge instead of fabricating a host state.
# Anything not listed here simply reports the failure upward.
READ_FALLBACKS: dict[str, list[str]] = {
    "get_system_info": ["search_knowledge"],
    "get_cpu_memory": ["search_knowledge"],
    "get_disk_usage": ["search_knowledge"],
    "get_service_status": ["search_knowledge"],
    "get_service_logs": ["search_knowledge"],
    "get_rpm_info": ["search_knowledge"],
    "check_rpm_dependencies": ["search_knowledge", "get_rpm_info"],
}


def _fingerprint(tool_name: str, arguments: dict) -> str:
    payload = json.dumps(
        {"tool": tool_name, "arguments": arguments}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def fallback_arguments(tool_name: str, step: PlanStep, query: str) -> dict:
    if tool_name == "search_knowledge":
        return {"query": query[:200]}
    return dict(step.arguments)


def evidence_from_result(result: ToolResult, step_id: int) -> list[EvidenceItem]:
    """Turn a tool result into citable evidence.

    `search_knowledge` returns several chunks, so each chunk becomes knowledge
    evidence; other tools contribute one tool-kind item describing what was read.
    """
    output = result.output or {}
    chunks = output.get("chunks")
    if isinstance(chunks, list) and chunks:
        items: list[EvidenceItem] = []
        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict) or not chunk.get("chunk_id"):
                continue
            items.append(
                EvidenceItem(
                    evidence_id=f"kb:{chunk['chunk_id']}",
                    kind=EvidenceKind.KNOWLEDGE,
                    source=str(chunk.get("title", "")),
                    reference=str(chunk["chunk_id"]),
                    title=str(chunk.get("title", chunk["chunk_id"])),
                    excerpt=str(chunk.get("content", ""))[:400],
                    rank=index + 1,
                    metadata={
                        "category": str(chunk.get("category", "")),
                        "source_type": str(chunk.get("source_type", "")),
                        "via_tool": result.name,
                    },
                )
            )
        return items
    if not result.success:
        return []
    return [
        tool_evidence(
            tool_name=result.name,
            step_id=step_id,
            output=output,
            fallback_from=str(output.get("fallback_from") or "") or None,
        )
    ]


_UNAVAILABLE_CODES = {
    "host_not_found",
    "service_not_found",
    "package_not_found",
    "vector_db_unavailable",
    "backend_unavailable",
}


def _failure_kind(exc: BaseException) -> str:
    if isinstance(exc, ToolTimeoutError):
        return ToolExecutionStatus.TIMEOUT.value
    if isinstance(exc, ToolPermissionError):
        return ToolExecutionStatus.DENIED.value
    if isinstance(exc, InvalidRequestError):
        return ToolExecutionStatus.INVALID_ARGUMENTS.value
    if isinstance(exc, AppError):
        code = exc.error_code.value.lower()
        return code
    return ToolExecutionStatus.FAILED.value


def _status_for_exception(exc: BaseException) -> ToolExecutionStatus:
    if isinstance(exc, ToolTimeoutError):
        return ToolExecutionStatus.TIMEOUT
    if isinstance(exc, ToolPermissionError):
        return ToolExecutionStatus.DENIED
    if isinstance(exc, InvalidRequestError):
        return ToolExecutionStatus.INVALID_ARGUMENTS
    if isinstance(exc, AppError):
        code = exc.error_code.value.lower()
        if code in _UNAVAILABLE_CODES:
            return ToolExecutionStatus.UNAVAILABLE
    return ToolExecutionStatus.FAILED


def _merge_evidence(existing: list[EvidenceItem], new: list[EvidenceItem]) -> None:
    """Append evidence without repeating a chunk id already cited."""
    seen = {item.evidence_id for item in existing}
    for item in new:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        existing.append(item)


async def execute_with_fallback(
    tool: Tool,
    step: PlanStep,
    context: ToolContext,
    registry: ToolRegistry,
    query: str,
) -> ToolResult:
    """Execution-layer fallback: a failed read tool tries the next mapped tool."""
    try:
        result = await tool.run(step.arguments, context)
        if result.success:
            return result
        raise ToolExecutionError(result.error or f"{tool.name} returned success=false")
    except ToolPermissionError:
        raise
    except (AppError, InvalidRequestError) as exc:
        last_error = str(exc)
        kind = _failure_kind(exc)
        for fallback_name in READ_FALLBACKS.get(tool.name, []):
            if fallback_name not in registry.names():
                continue
            fallback = registry.get(fallback_name)
            try:
                fb_result = await fallback.run(
                    fallback_arguments(fallback_name, step, query), context
                )
                if fb_result.success:
                    merged = {
                        **fb_result.output,
                        "fallback_from": tool.name,
                        "fallback_error": last_error,
                    }
                    TOOL_CALLS.labels(tool=fallback_name, status="fallback").inc()
                    return fb_result.model_copy(
                        update={
                            "output": merged,
                            "status": ToolExecutionStatus.FALLBACK,
                            "requested_name": tool.name,
                            "failure_kind": kind,
                        }
                    )
            except (AppError, InvalidRequestError):
                continue
        raise


async def executor_node(
    state: AgentState,
    *,
    registry: ToolRegistry,
    settings: Settings,
) -> dict:
    plan = state.get("plan")
    if plan is None:
        return {"tool_results": []}
    if state.get("pending_action") and not state.get("confirm_action_id"):
        return {"tool_results": []}

    started = time.perf_counter()
    results: list[ToolResult] = list(state.get("tool_results") or [])
    trace: list[ToolTraceItem] = list(state.get("tool_trace") or [])
    evidence: list[EvidenceItem] = list(state.get("evidence") or [])
    has_knowledge = any(item.kind == EvidenceKind.KNOWLEDGE for item in evidence)
    seen_calls: set[tuple[str, str]] = {
        (item.name, json.dumps(item.arguments or {}, sort_keys=True, default=str)) for item in trace
    }
    context = ToolContext(
        user_id=state["user_id"],
        session_id=state["session_id"],
        trace_id=state["trace_id"],
        confirmed_action_id=state.get("confirm_action_id"),
        idempotency_key=state.get("idempotency_key"),
        timeout_seconds=settings.tool_timeout_seconds,
        host_id=state.get("host_id"),
    )
    idempotency: IdempotencyRepository | None = None
    try:
        idempotency = IdempotencyRepository(get_db_session())
    except RuntimeError:
        # No request-scoped session (unit tests calling the node directly):
        # write idempotency is then enforced by the pending-store consumption.
        idempotency = None
    calls = 0
    query = state["user_query"]
    for step in plan.steps:
        if (
            calls >= settings.max_tool_calls
            or (state.get("step_count") or 0) >= settings.max_agent_steps
        ):
            break
        if not step.tool_name:
            continue
        if step.tool_name == "search_knowledge" and has_knowledge:
            # The AGENT path already retrieved docs before planning. Never burn
            # a second retrieval just because a stale plan still lists one.
            continue
        call_key = (
            step.tool_name,
            json.dumps(step.arguments or {}, sort_keys=True, default=str),
        )
        if call_key in seen_calls:
            continue
        seen_calls.add(call_key)
        tool = registry.get(step.tool_name)
        confirmed = bool(state.get("confirm_action_id"))
        call_started = time.perf_counter()
        try:
            if tool.risk in WRITE_RISKS:
                assert_permitted(tool, confirmed=confirmed)
                idem_key = context.confirmed_action_id or context.idempotency_key
                if idem_key and idempotency is not None:
                    fp = _fingerprint(tool.name, step.arguments)
                    existing = await idempotency.get_if_matches(idem_key, fp)
                    if existing is not None:
                        result = ToolResult(
                            name=tool.name,
                            success=True,
                            output=existing,
                            risk=tool.risk,
                            status=ToolExecutionStatus.OK,
                            requested_name=tool.name,
                        )
                        TOOL_CALLS.labels(tool=tool.name, status="idempotent").inc()
                        result = result.model_copy(
                            update={"latency_ms": (time.perf_counter() - call_started) * 1000}
                        )
                        results.append(result)
                        calls += 1
                        _merge_evidence(evidence, evidence_from_result(result, step.step_id))
                        trace.append(
                            ToolTraceItem(
                                step_id=step.step_id,
                                name=tool.name,
                                arguments=step.arguments,
                                success=True,
                                status=ToolExecutionStatus.OK,
                                risk=tool.risk,
                                latency_ms=result.latency_ms,
                                executed_tool=tool.name,
                                idempotent=True,
                            )
                        )
                        continue
                result = await tool.run(step.arguments, context)
                if idempotency is not None:
                    await idempotency.put(idem_key or "", fp, result.output)
                TOOL_CALLS.labels(tool=tool.name, status="ok").inc()
            else:
                result = await execute_with_fallback(tool, step, context, registry, query)
                TOOL_CALLS.labels(tool=tool.name, status="ok").inc()
            result = result.model_copy(
                update={"latency_ms": (time.perf_counter() - call_started) * 1000}
            )
            if not result.success and result.status == ToolExecutionStatus.OK:
                result = result.model_copy(
                    update={
                        "status": ToolExecutionStatus.FAILED,
                        "failure_kind": result.failure_kind or "tool_returned_failure",
                    }
                )
            _merge_evidence(evidence, evidence_from_result(result, step.step_id))
            results.append(result)
            trace.append(
                ToolTraceItem(
                    step_id=step.step_id,
                    name=tool.name,
                    arguments=step.arguments,
                    success=result.success and result.status == ToolExecutionStatus.OK,
                    status=result.status,
                    risk=tool.risk,
                    latency_ms=result.latency_ms,
                    error=result.error,
                    fallback_from=(
                        result.output.get("fallback_from")
                        if result.status == ToolExecutionStatus.FALLBACK
                        else None
                    ),
                    executed_tool=result.name,
                    failure_kind=result.failure_kind,
                )
            )
        except ToolTimeoutError as exc:
            TOOL_CALLS.labels(tool=tool.name, status="timeout").inc()
            results.append(
                ToolResult(
                    name=tool.name,
                    success=False,
                    error=str(exc),
                    risk=tool.risk,
                    status=ToolExecutionStatus.TIMEOUT,
                    requested_name=tool.name,
                    failure_kind=ToolExecutionStatus.TIMEOUT.value,
                )
            )
            trace.append(
                ToolTraceItem(
                    step_id=step.step_id,
                    name=tool.name,
                    arguments=step.arguments,
                    success=False,
                    status=ToolExecutionStatus.TIMEOUT,
                    risk=tool.risk,
                    error=str(exc),
                    executed_tool=tool.name,
                    failure_kind=ToolExecutionStatus.TIMEOUT.value,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                )
            )
        except InvalidRequestError as exc:
            TOOL_CALLS.labels(tool=tool.name, status="invalid_arguments").inc()
            results.append(
                ToolResult(
                    name=tool.name,
                    success=False,
                    error=str(exc),
                    risk=tool.risk,
                    status=ToolExecutionStatus.INVALID_ARGUMENTS,
                    requested_name=tool.name,
                    failure_kind=ToolExecutionStatus.INVALID_ARGUMENTS.value,
                )
            )
            trace.append(
                ToolTraceItem(
                    step_id=step.step_id,
                    name=tool.name,
                    arguments=step.arguments,
                    success=False,
                    status=ToolExecutionStatus.INVALID_ARGUMENTS,
                    risk=tool.risk,
                    error=str(exc),
                    executed_tool=tool.name,
                    failure_kind=ToolExecutionStatus.INVALID_ARGUMENTS.value,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                )
            )
        except ToolPermissionError as exc:
            TOOL_CALLS.labels(tool=tool.name, status="denied").inc()
            results.append(
                ToolResult(
                    name=tool.name,
                    success=False,
                    error=str(exc),
                    risk=tool.risk,
                    status=ToolExecutionStatus.DENIED,
                    requested_name=tool.name,
                    failure_kind=ToolExecutionStatus.DENIED.value,
                )
            )
            trace.append(
                ToolTraceItem(
                    step_id=step.step_id,
                    name=tool.name,
                    arguments=step.arguments,
                    success=False,
                    status=ToolExecutionStatus.DENIED,
                    risk=tool.risk,
                    error=str(exc),
                    executed_tool=tool.name,
                    failure_kind=ToolExecutionStatus.DENIED.value,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                )
            )
        except AppError as exc:
            status = "conflict" if exc.error_code.value == "IDEMPOTENCY_CONFLICT" else "error"
            TOOL_CALLS.labels(tool=tool.name, status=status).inc()
            failure_kind = _failure_kind(exc)
            execution_status = _status_for_exception(exc)
            results.append(
                ToolResult(
                    name=tool.name,
                    success=False,
                    error=str(exc),
                    risk=tool.risk,
                    status=execution_status,
                    requested_name=tool.name,
                    failure_kind=failure_kind,
                )
            )
            trace.append(
                ToolTraceItem(
                    step_id=step.step_id,
                    name=tool.name,
                    arguments=step.arguments,
                    success=False,
                    status=execution_status,
                    risk=tool.risk,
                    error=str(exc),
                    executed_tool=tool.name,
                    failure_kind=failure_kind,
                    latency_ms=(time.perf_counter() - call_started) * 1000,
                )
            )
        calls += 1
    latency = state.get("latency") or LatencyBreakdown()
    latency.tool_ms = (time.perf_counter() - started) * 1000
    return {
        "tool_results": results,
        "tool_trace": trace,
        "evidence": evidence,
        "step_count": (state.get("step_count") or 0) + calls,
        "latency": latency,
    }
