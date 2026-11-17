"""Read-only ops tool failure degrades to knowledge search, and says so."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.agents.nodes.executor import _status_for_exception, execute_with_fallback
from app.core.enums import ToolExecutionStatus, ToolRisk
from app.core.exceptions import ServiceNotFoundError, ToolExecutionError
from app.schemas.agent import PlanStep, ToolResult
from app.tools.base import Tool, ToolContext
from app.tools.registry import ToolRegistry


class _Query(BaseModel):
    query: str = Field(default="")
    service: str = Field(default="")


class _FailingStatus(Tool):
    name = "get_service_status"
    description = "fail"
    risk = ToolRisk.READ
    input_model = _Query

    async def execute(self, parsed: BaseModel, context: ToolContext) -> ToolResult:
        raise ToolExecutionError("mock backend unavailable")


class _Knowledge(Tool):
    name = "search_knowledge"
    description = "kb"
    risk = ToolRisk.DESTRUCTIVE  # never executed in this test; only looked up
    input_model = _Query

    async def execute(self, parsed: BaseModel, context: ToolContext) -> ToolResult:
        return ToolResult(name=self.name, success=True, output={"chunks": [{"content": "文档"}]})


@pytest.mark.asyncio
async def test_read_tool_falls_back_to_knowledge() -> None:
    registry = ToolRegistry()
    registry.register(_FailingStatus())
    registry.register(_Knowledge())
    result = await execute_with_fallback(
        registry.get("get_service_status"),
        PlanStep(
            step_id=1,
            goal="status",
            tool_name="get_service_status",
            arguments={"query": "x", "service": "nginx"},
        ),
        ToolContext(user_id="u", session_id="s", trace_id="t"),
        registry,
        "nginx 服务状态",
    )
    assert result.success is True
    assert result.name == "search_knowledge"
    assert result.output["fallback_from"] == "get_service_status"
    assert result.status == ToolExecutionStatus.FALLBACK
    assert result.requested_name == "get_service_status"
    assert result.failure_kind == "tool_execution_failed"


def test_not_found_maps_to_unavailable_not_a_generic_failure() -> None:
    status = _status_for_exception(ServiceNotFoundError("service missing"))
    assert status == ToolExecutionStatus.UNAVAILABLE
